# PyInstaller spec for Sayso. Run from the repo root:  pyinstaller packaging/pyinstaller/sayso.spec
# ONEFILE=1 builds a single exe; otherwise a folder (preferred for corporate machines: no %TEMP% extraction).
# NO_CLOUD=1 leaves the Anthropic SDK out of the bundle.
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all
from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo, StringStruct, StringTable,
                                                 VarFileInfo, VarStruct, VSVersionInfo)

ROOT = Path(SPECPATH).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from sayso import __version__  # noqa: E402

ONEFILE = os.environ.get("ONEFILE") == "1"
NO_CLOUD = os.environ.get("NO_CLOUD") == "1"

datas = [
    (str(ROOT / "assets" / "sayso.svg"), "assets"),
    (str(ROOT / "assets" / "sayso.ico"), "assets"),
    (str(ROOT / "assets" / "sounds"), "assets/sounds"),
    (str(ROOT / "src" / "sayso" / "winsys" / "windows_speech.ps1"), "winsys"),
]
binaries = []
hiddenimports = [
    "sayso.stt.faster_whisper_engine", "sayso.stt.whisper_cpp_engine", "sayso.stt.windows_speech_engine",
    "sayso.llm.openai_compatible", "sayso.llm.offline", "sayso.winsys.hotkeys", "sayso.winsys.injection",
    "sayso.winsys.context", "sayso.winsys.clipboard", "sayso.winsys.credentials", "sayso.winsys.autostart",
    "sayso.runtime_probes", "sounddevice", "winreg",
]
if not NO_CLOUD:
    hiddenimports += ["sayso.stt.cloud_engine", "sayso.llm.anthropic_provider"]

optional = ["faster_whisper", "ctranslate2", "tokenizers", "onnxruntime", "av", "comtypes"]
if not NO_CLOUD:
    optional.append("anthropic")
for pkg in optional:
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        print(f"[sayso.spec] {pkg} not installed; leaving it out")

excludes = [
    "tkinter", "matplotlib", "scipy", "pandas", "IPython", "pytest", "PIL.ImageTk",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick", "PySide6.Qt3DCore",
    "PySide6.Qt3DRender", "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtPdf", "PySide6.QtCharts",
    "PySide6.QtDataVisualization", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtBluetooth", "PySide6.QtNetworkAuth",
]
if NO_CLOUD:
    excludes.append("anthropic")

major, minor, patch = (int(x) for x in (__version__.split(".") + ["0", "0"])[:3])
version = VSVersionInfo(
    ffi=FixedFileInfo(filevers=(major, minor, patch, 0), prodvers=(major, minor, patch, 0), mask=0x3F, flags=0x0,
                      OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
    kids=[
        StringFileInfo([StringTable("040904B0", [
            StringStruct("CompanyName", "Sayso"), StringStruct("FileDescription", "Sayso voice dictation"),
            StringStruct("FileVersion", __version__), StringStruct("InternalName", "Sayso"),
            StringStruct("OriginalFilename", "Sayso.exe"), StringStruct("ProductName", "Sayso"),
            StringStruct("ProductVersion", __version__)])]),
        VarFileInfo([VarStruct("Translation", [1033, 1200])]),
    ],
)

a = Analysis([str(ROOT / "src" / "sayso" / "__main__.py")], pathex=[str(ROOT / "src")], binaries=binaries, datas=datas,
             hiddenimports=hiddenimports, excludes=excludes, noarchive=False)
pyz = PYZ(a.pure)

if ONEFILE:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="Sayso", console=False, upx=False,
              icon=str(ROOT / "assets" / "sayso.ico"), version=version, runtime_tmpdir=None)
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Sayso", console=False, upx=False,
              icon=str(ROOT / "assets" / "sayso.ico"), version=version)
    coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Sayso")
