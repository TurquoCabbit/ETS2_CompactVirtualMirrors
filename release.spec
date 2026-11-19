from pathlib import Path
import runpy

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct,
    VSVersionInfo,
)

root = Path(SPECPATH)
info = runpy.run_path(str(root / "mirrors" / "release_info.py"))
version = info["VERSION"]
version_parts = (*map(int, version.split(".")), 0)
app = info["APP_NAME"]
author = info["AUTHOR"]
metadata = VSVersionInfo(
    ffi=FixedFileInfo(filevers=version_parts, prodvers=version_parts, mask=0x3F,
                      flags=0, OS=0x40004, fileType=1, subtype=0, date=(0, 0)),
    kids=[StringFileInfo([StringTable("040904B0", [
        StringStruct("FileDescription", app),
        StringStruct("ProductName", app),
        StringStruct("CompanyName", author),
        StringStruct("FileVersion", version),
        StringStruct("ProductVersion", version),
        StringStruct("LegalCopyright", f"Copyright (C) {author}"),
    ])]), VarFileInfo([VarStruct("Translation", [1033, 1200])])],
)

analysis = Analysis(
    [str(root / "main.py")],
    datas=[(str(root / "mirrors" / name), "mirrors") for name in ("compact.ini", "app.ico")],
)
# Qt imports Windows' ICU forwarder. A third-party DLL with the same name
# can export different symbols and prevent QtCore from loading.
excluded_dlls = {
    "icuuc.dll", "icuin.dll", "icu.dll", "ucrtbase.dll",
    "opengl32sw.dll", "qopensslbackend.dll", "libssl-3-x64.dll", "libcrypto-3-x64.dll",
}
analysis.binaries = [entry for entry in analysis.binaries
                     if Path(entry[0]).name.casefold() not in excluded_dlls
                     and not Path(entry[0]).name.casefold().startswith(("icudt", "api-ms-win-"))]
archive = PYZ(analysis.pure)
exe = EXE(
    archive, analysis.scripts, analysis.binaries, analysis.datas,
    name=f"ETS2-Configurable-Mirrors-v{version}-windows-x64",
    version=metadata, icon=str(root / "mirrors" / "app.ico"), console=False, upx=False,
)
