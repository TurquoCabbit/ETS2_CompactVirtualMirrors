import os
from pathlib import Path
import re
import sys

from PySide6.QtCore import QDir, QStandardPaths

from .config import PROJECT
from .release_info import APP_NAME

DIRECTORIES = {
    "game": "ETS2 installation",
    "source": "Extracted HUD source",
    "output": "Build output",
    "mod": "ETS2 mod directory",
}


def _steam_roots():
    if os.name == "nt":
        import winreg

        keys = (
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
        )
        for hive, key, value in keys:
            try:
                with winreg.OpenKey(hive, key) as steam:
                    yield Path(winreg.QueryValueEx(steam, value)[0])
            except OSError:
                continue
    program_files = os.environ.get("ProgramFiles(x86)")
    if program_files:
        yield Path(program_files) / "Steam"


def detect_game():
    for steam in _steam_roots():
        libraries = [steam]
        try:
            data = (steam / "steamapps" / "libraryfolders.vdf").read_text(encoding="utf-8-sig")
            libraries.extend(Path(path.replace("\\\\", "\\"))
                             for path in re.findall(r'"path"\s+"([^"]+)"', data))
        except (OSError, UnicodeError):
            pass
        for library in libraries:
            game = _game_under(library)
            if game:
                return game
    for drive in QDir.drives():
        root = Path(drive.absoluteFilePath())
        for name in ("SteamLibrary", "Steam"):
            game = _game_under(root / name)
            if game:
                return game
    return None


def _game_under(library):
    game = library / "steamapps" / "common" / "Euro Truck Simulator 2"
    return game if (game / "bin" / "win_x64" / "eurotrucks2.exe").is_file() else None


def editor_directory():
    if getattr(sys, "frozen", False):
        local = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.GenericDataLocation)
        return (Path(local) if local else Path.home()) / APP_NAME
    return PROJECT


def directory_defaults():
    documents = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
    home = Path(documents) / "Euro Truck Simulator 2" if documents else None
    return {
        "game": detect_game(),
        "source": None if getattr(sys, "frozen", False) else PROJECT / "source_ui",
        "output": editor_directory() / "output",
        "mod": home / "mod" if home and home.is_dir() else None,
    }
