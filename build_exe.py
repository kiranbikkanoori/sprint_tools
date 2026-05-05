#!/usr/bin/env python3
"""
Build the Sprint Report GUI into a single-file executable.

Usage
-----
    python build_exe.py

Prerequisites
-------------
    pip install -r requirements.txt
    pip install -r requirements-gui.txt

Output
------
    dist/SprintReport.exe   (on Windows)
    dist/SprintReport       (on macOS / Linux)
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent
    spec = root / "sprint_app.spec"
    if not spec.exists():
        print(f"Spec not found: {spec}", file=sys.stderr)
        return 1

    # Clean previous build artefacts so the spec runs fresh.
    for d in ("build", "dist"):
        p = root / d
        if p.exists():
            print(f"Removing {p}")
            shutil.rmtree(p)

    cmd = [sys.executable, "-m", "PyInstaller", str(spec), "--noconfirm", "--clean"]
    print("Running:", " ".join(cmd))
    rc = subprocess.call(cmd, cwd=str(root))
    if rc != 0:
        return rc

    out = root / "dist"
    print("\nDone.")
    print(f"Executable(s) in: {out}")
    for child in out.iterdir():
        print(f"  - {child.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
