"""
PyInstaller spec file for PortkeyDrop.

This spec file configures PyInstaller to build PortkeyDrop as a standalone
application for Windows.

Usage:
    pyinstaller installer/portkeydrop.spec
"""

import sys
from pathlib import Path

import tomllib
from PyInstaller.utils.hooks import collect_all, collect_submodules

# Determine paths
SPEC_DIR = Path(SPECPATH).resolve()
PROJECT_ROOT = SPEC_DIR.parent
SRC_DIR = PROJECT_ROOT / "src"
RESOURCES_DIR = SRC_DIR / "portkeydrop" / "resources"

# App metadata
APP_NAME = "PortkeyDrop"
APP_VERSION = "0.1.0"
APP_BUNDLE_ID = "net.orinks.portkeydrop"

# Read version from pyproject.toml if available
try:
    with open(PROJECT_ROOT / "pyproject.toml", "rb") as f:
        pyproject = tomllib.load(f)
        APP_VERSION = pyproject.get("project", {}).get("version", APP_VERSION)
except Exception:
    pass

# Determine icon path
ICON_PATH = SPEC_DIR / "app.ico"
ICON_PATH = str(ICON_PATH) if ICON_PATH.exists() else None

# Data files to bundle (only if resources dir exists)
datas = []
binaries = []
if RESOURCES_DIR.exists():
    datas.append((str(RESOURCES_DIR), "portkeydrop/resources"))

# Pull full asyncssh package metadata/submodules/binaries for frozen builds
asyncssh_datas, asyncssh_binaries, asyncssh_hiddenimports = collect_all("asyncssh")
datas += asyncssh_datas
binaries += asyncssh_binaries

# Hidden imports for wxPython and other dynamic imports
hiddenimports = [
    "wx",
    "wx.adv",
    "wx.html",
    "wx.lib.agw",
    "wx.lib.agw.aui",
    "wx.lib.mixins",
    "wx.lib.mixins.inspection",
    "keyring",
    "keyring.backends",
    "keyring.backends.Windows",
    "keyring.backends.macOS",
    "keyring.backends.SecretService",
    *collect_submodules("asyncssh"),
    *asyncssh_hiddenimports,
    "prismatoid",
    # Generated build-time file (wrapped in try/except, so PyInstaller misses it)
    "portkeydrop._build_meta",
]

# Excludes to reduce size
excludes = [
    "tkinter",
    "_tkinter",
    "tcl",
    "tk",
    "matplotlib",
    "numpy",
    "pandas",
    "scipy",
    "PIL.ImageTk",
    "test",
    "tests",
    "unittest",
    "pytest",
    "paramiko",
]

# Analysis
a = Analysis(
    [str(SRC_DIR / "portkeydrop" / "main.py")],
    pathex=[str(SRC_DIR)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[str(INSTALLER_DIR / "hooks")],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

# Windows: Create executable + directory distribution for Inno Setup
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON_PATH,
    version_file=None,
)

# Directory-based distribution for Inno Setup installer
coll = COLLECT(
    EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name=APP_NAME,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=ICON_PATH,
    ),
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=f"{APP_NAME}_dir",
)
