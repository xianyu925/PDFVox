# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_all


project_root = Path.cwd().resolve()
datas = [(str(project_root / "web"), "web")]
binaries = []
hiddenimports = ["keyring.backends.Windows"]


def collect_package(name):
    package_datas, package_binaries, package_hiddenimports = collect_all(name)
    datas.extend(package_datas)
    binaries.extend(package_binaries)
    hiddenimports.extend(package_hiddenimports)


for package in (
    "webview",
    "keyring",
    "faster_whisper",
    "ctranslate2",
    "av",
):
    collect_package(package)


analysis = Analysis(
    [str(project_root / "desktop_main.py")],
    pathex=[str(project_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "pytest",
        "tests",
        "torch",
        "torch.testing",
        "torch.distributed",
        "torch.utils.tensorboard",
        "pandas",
        "openpyxl",
        "matplotlib",
    ],
    noarchive=False,
)
pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="PDFVox",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)

bundle = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="PDFVox",
)
