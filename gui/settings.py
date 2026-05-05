"""
Persistent app settings store.

On Windows  : %APPDATA%\\SprintReport\\settings.json
On macOS    : ~/Library/Application Support/SprintReport/settings.json
On Linux    : ~/.config/SprintReport/settings.json

The Jira token is encrypted with a machine-bound key (see ``_machine_key``)
so casual inspection of settings.json does not leak the PAT.  This is *not*
a defence against an attacker who has filesystem access — it is just to
keep tokens off plain disk.

A ``.env`` file (``JIRA_BASE_URL`` / ``JIRA_TOKEN`` / ``JIRA_USER`` /
``JIRA_PASSWORD``) next to the executable or in the project root is used
as a fallback if the user has not configured credentials in the app yet.
"""

from __future__ import annotations

import base64
import getpass
import hashlib
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

try:
    from cryptography.fernet import Fernet, InvalidToken
    _HAS_CRYPTO = True
except ImportError:  # pragma: no cover - cryptography is in requirements
    _HAS_CRYPTO = False


APP_DIR_NAME = "SprintReport"


# ── Paths ──────────────────────────────────────────────────────────────────

def app_data_dir() -> Path:
    """Return platform-specific writable app-data directory (created on demand)."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    out = base / APP_DIR_NAME
    out.mkdir(parents=True, exist_ok=True)
    return out


def settings_path() -> Path:
    return app_data_dir() / "settings.json"


def configs_dir() -> Path:
    out = app_data_dir() / "configs"
    out.mkdir(parents=True, exist_ok=True)
    return out


def output_dir_default() -> Path:
    out = app_data_dir() / "output"
    out.mkdir(parents=True, exist_ok=True)
    return out


def app_executable_dir() -> Path:
    """Directory containing the running script / frozen exe (for .env fallback)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


# ── Encryption (machine-bound, not user-supplied passphrase) ───────────────

def _machine_key() -> bytes:
    seed_parts = [
        os.environ.get("COMPUTERNAME", ""),
        os.environ.get("USERDOMAIN", ""),
        getpass.getuser(),
        sys.platform,
        "sprint-report-app-v1",
    ]
    seed = "|".join(seed_parts).encode("utf-8")
    digest = hashlib.sha256(seed).digest()
    return base64.urlsafe_b64encode(digest)


def _encrypt(plain: str) -> str:
    if not plain:
        return ""
    if not _HAS_CRYPTO:
        return "b64:" + base64.b64encode(plain.encode("utf-8")).decode("ascii")
    f = Fernet(_machine_key())
    return "v1:" + f.encrypt(plain.encode("utf-8")).decode("ascii")


def _decrypt(blob: str) -> str:
    if not blob:
        return ""
    if blob.startswith("b64:"):
        try:
            return base64.b64decode(blob[4:]).decode("utf-8")
        except Exception:
            return ""
    if blob.startswith("v1:"):
        if not _HAS_CRYPTO:
            return ""
        try:
            f = Fernet(_machine_key())
            return f.decrypt(blob[3:].encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError):
            return ""
    return blob


# ── .env fallback loader ───────────────────────────────────────────────────

def _read_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip().strip("'\"")
    return out


def env_fallback() -> dict[str, str]:
    """Look for a .env (or .env.defaults) next to the exe / project root."""
    candidates = [
        app_executable_dir() / ".env",
        app_executable_dir() / ".env.defaults",
        Path.cwd() / ".env",
    ]
    merged: dict[str, str] = {}
    for c in candidates:
        merged.update(_read_env_file(c))
    return merged


# ── Settings dataclass ─────────────────────────────────────────────────────

@dataclass
class AppSettings:
    jira_base_url: str = ""
    jira_token_enc: str = ""
    jira_user: str = ""
    jira_password_enc: str = ""
    last_board_id: int = 0
    last_board_name: str = ""
    last_sprint_name: str = ""
    output_dir: str = ""
    recent_configs: list = field(default_factory=list)

    @property
    def jira_token(self) -> str:
        return _decrypt(self.jira_token_enc)

    @jira_token.setter
    def jira_token(self, value: str) -> None:
        self.jira_token_enc = _encrypt(value)

    @property
    def jira_password(self) -> str:
        return _decrypt(self.jira_password_enc)

    @jira_password.setter
    def jira_password(self, value: str) -> None:
        self.jira_password_enc = _encrypt(value)

    def effective_credentials(self) -> dict[str, str]:
        """
        Merge in-app settings with .env fallback values.

        In-app values win; only blanks fall back to env.
        """
        env = env_fallback()
        return {
            "JIRA_BASE_URL": self.jira_base_url or env.get("JIRA_BASE_URL", ""),
            "JIRA_TOKEN": self.jira_token or env.get("JIRA_TOKEN", ""),
            "JIRA_USER": self.jira_user or env.get("JIRA_USER", ""),
            "JIRA_PASSWORD": self.jira_password or env.get("JIRA_PASSWORD", ""),
        }


def load_settings() -> AppSettings:
    p = settings_path()
    if not p.exists():
        return AppSettings(output_dir=str(output_dir_default()))
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return AppSettings(output_dir=str(output_dir_default()))
    s = AppSettings()
    for k, v in raw.items():
        if hasattr(s, k):
            setattr(s, k, v)
    if not s.output_dir:
        s.output_dir = str(output_dir_default())
    return s


def save_settings(s: AppSettings) -> None:
    p = settings_path()
    p.write_text(json.dumps(asdict(s), indent=2), encoding="utf-8")
