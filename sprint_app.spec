# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Sprint Report GUI.

Build:
    pyinstaller sprint_app.spec --noconfirm --clean

Output:
    dist/SprintReport.exe   (Windows, single-file)
    dist/SprintReport       (macOS / Linux)
"""

from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, copy_metadata

ROOT = Path.cwd()

block_cipher = None

# Project root sources we want to ship with the bundle so the GUI's
# ``import config_parser`` etc. keeps working from the frozen exe.
hidden_imports = [
    "config_parser",
    "report_generator",
    "report_html",
    "report_style",
    "report_format",
    "burndown_chart",
    "fetch_sprint_data",
    "utils",
    # PySide6 sub-modules sometimes missed by the analyser:
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "PySide6.QtSvg",  # Help tab README images (SVG hero / workflow)
]

# matplotlib backend must be importable.
hidden_imports += ["matplotlib.backends.backend_agg"]

# markdown package — collect ALL submodules because Markdown discovers
# extensions dynamically via importlib.metadata at runtime, which the
# PyInstaller analyser can't see by static inspection.
hidden_imports += collect_submodules("markdown")

datas = []

# Include .env.defaults if present (read at runtime as fallback).
env_defaults = ROOT / ".env.defaults"
if env_defaults.exists():
    datas.append((str(env_defaults), "."))

# In-app Help tab: GUI README + images (hero, workflow, burndown proof).
readme = ROOT / "README.md"
if readme.exists():
    datas.append((str(readme), "."))
assets_readme = ROOT / "assets" / "readme"
if assets_readme.is_dir():
    datas.append((str(assets_readme), "assets/readme"))
assets_app = ROOT / "assets" / "app"
if assets_app.is_dir():
    datas.append((str(assets_app), "assets/app"))

# Markdown reads its own package metadata at runtime to enumerate built-in
# extensions. Without this, "tables" / "fenced_code" silently disappear.
try:
    datas += copy_metadata("markdown")
except Exception:
    pass

a = Analysis(
    ["gui/app.py"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "PyQt5",
        "PyQt6",
        "PySide2",
        # NOTE: do NOT exclude `unittest` or `test` — matplotlib imports
        # `unittest.mock` internally during figure rendering.
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="SprintReport",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,             # windowed app on Windows
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # Embedded into the Windows .exe so File Explorer shows this icon
    # (runtime QIcon only affects the open window / taskbar).
    icon=str(ROOT / "assets" / "app" / "icon.ico"),
)
