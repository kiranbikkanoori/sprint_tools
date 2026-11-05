"""
Shared Jira authentication for Silabs Server/DC and Atlassian Cloud.

Both backends use the same REST client; only the Authorization scheme differs:

* ``server`` — Bearer personal access token (optional Basic user/password)
* ``cloud``  — Basic auth with Atlassian account email + API token
"""

from __future__ import annotations

from typing import Any

import requests
from requests.auth import AuthBase, HTTPBasicAuth

BACKEND_SERVER = "server"
BACKEND_CLOUD = "cloud"
BACKEND_CHOICES = (BACKEND_SERVER, BACKEND_CLOUD)

BACKEND_LABELS = {
    BACKEND_SERVER: "Silabs Jira (Server / Data Center)",
    BACKEND_CLOUD: "Atlassian Jira Cloud",
}

DEFAULT_URLS = {
    BACKEND_SERVER: "https://jira.silabs.com",
    BACKEND_CLOUD: "https://siliconlabs.atlassian.net",
}


class JiraAuthError(ValueError):
    """Missing or invalid credentials for the selected backend."""


class BearerAuth(AuthBase):
    def __init__(self, token: str) -> None:
        self.token = token

    def __call__(self, r: requests.PreparedRequest) -> requests.PreparedRequest:
        r.headers["Authorization"] = f"Bearer {self.token}"
        return r


def normalize_backend(value: str | None) -> str:
    raw = (value or BACKEND_SERVER).strip().lower()
    aliases = {
        "server": BACKEND_SERVER,
        "dc": BACKEND_SERVER,
        "datacenter": BACKEND_SERVER,
        "data-center": BACKEND_SERVER,
        "silabs": BACKEND_SERVER,
        "cloud": BACKEND_CLOUD,
        "atlassian": BACKEND_CLOUD,
        "jira-cloud": BACKEND_CLOUD,
    }
    backend = aliases.get(raw, raw)
    if backend not in BACKEND_CHOICES:
        raise JiraAuthError(
            f"Unknown Jira backend '{value}'. Use '{BACKEND_SERVER}' or '{BACKEND_CLOUD}'."
        )
    return backend


def build_auth(creds: dict[str, str]) -> tuple[str, AuthBase]:
    """
    Build ``(base_url, requests auth)`` from a credentials dict.

    Expected keys (same as ``AppSettings.effective_credentials`` / ``.env``):
    ``JIRA_BACKEND``, ``JIRA_BASE_URL``, ``JIRA_TOKEN``, ``JIRA_USER``, ``JIRA_PASSWORD``.
    """
    backend = normalize_backend(creds.get("JIRA_BACKEND"))
    base_url = (creds.get("JIRA_BASE_URL") or "").strip().rstrip("/")
    if not base_url:
        raise JiraAuthError(
            f"Jira base URL is required for {BACKEND_LABELS[backend]}."
        )

    token = (creds.get("JIRA_TOKEN") or "").strip()
    user = (creds.get("JIRA_USER") or "").strip()
    password = (creds.get("JIRA_PASSWORD") or "").strip()

    if backend == BACKEND_CLOUD:
        if not user:
            raise JiraAuthError(
                "Atlassian Cloud requires your account email "
                "(Settings → Email / Username)."
            )
        if not token:
            raise JiraAuthError(
                "Atlassian Cloud requires an API token "
                "(https://id.atlassian.com/manage-profile/security/api-tokens)."
            )
        return base_url, HTTPBasicAuth(user, token)

    # Server / Data Center
    if token:
        return base_url, BearerAuth(token)
    if user and password:
        return base_url, HTTPBasicAuth(user, password)
    raise JiraAuthError(
        "Silabs Jira requires a personal access token, "
        "or a username + password."
    )


def describe_auth(creds: dict[str, str]) -> str:
    """Short label for status / test-connection messages (no secrets)."""
    try:
        backend = normalize_backend(creds.get("JIRA_BACKEND"))
    except JiraAuthError:
        backend = BACKEND_SERVER
    if backend == BACKEND_CLOUD:
        return f"{BACKEND_LABELS[backend]} (Basic email + API token)"
    token = (creds.get("JIRA_TOKEN") or "").strip()
    if token:
        return f"{BACKEND_LABELS[backend]} (Bearer PAT)"
    return f"{BACKEND_LABELS[backend]} (Basic user + password)"


def credentials_from_environ(environ: dict[str, str] | None = None) -> dict[str, str]:
    """Read credential keys from ``os.environ``-like mapping."""
    import os

    env = environ if environ is not None else os.environ
    return {
        "JIRA_BACKEND": env.get("JIRA_BACKEND", BACKEND_SERVER),
        "JIRA_BASE_URL": env.get("JIRA_BASE_URL", ""),
        "JIRA_TOKEN": env.get("JIRA_TOKEN", ""),
        "JIRA_USER": env.get("JIRA_USER", ""),
        "JIRA_PASSWORD": env.get("JIRA_PASSWORD", ""),
    }


def probe_connection(base_url: str, auth: AuthBase, timeout: float = 30) -> dict[str, Any]:
    """
    Lightweight connectivity check used by Settings → Test connection.

    Prefers agile boards (what the app needs); falls back to ``/myself``.
    """
    session = requests.Session()
    session.auth = auth
    session.headers.update({"Accept": "application/json", "Content-Type": "application/json"})
    url = base_url.rstrip("/")

    boards_resp = session.get(
        f"{url}/rest/agile/1.0/board",
        params={"type": "scrum", "maxResults": 50},
        timeout=timeout,
    )
    boards_resp.raise_for_status()
    boards = boards_resp.json().get("values", [])

    me_name = ""
    me_resp = session.get(f"{url}/rest/api/2/myself", timeout=timeout)
    if me_resp.ok:
        me_name = me_resp.json().get("displayName") or me_resp.json().get("name") or ""

    return {"boards": boards, "display_name": me_name}
