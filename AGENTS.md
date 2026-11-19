# Repository Guidelines

## Project Structure

`main.py` launches the Windows PySide6 editor. In `mirrors/`, `gui.py` and `preview.py` handle the editor, `model.py` handles layout geometry, and `config.py` and `preferences.py` handle INI files and local settings. `cli.py` exposes the command-line builder, `builder.py` packages and installs the mod, and `hud.py` parses and updates ETS2 HUD definitions. `tests/` contains core and GUI tests, with shared fixtures in `conftest.py`.

## Build, Test, and Run

Use 64-bit Python 3.11 or newer on Windows. Run these commands from the project root in PowerShell.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\run_gui.bat
.\build.bat
.\.venv\Scripts\python.exe -m pytest
```

The development requirements install PySide6 and pytest. The GUI can launch without ETS2. The build reads `config.ini` and the extracted `ui/hud_left.sii` and `ui/hud_right.sii` under `source_ui/`, then writes `output/ets2_configurable_mirrors.scs`. Run `.\build.bat --help` for path overrides. Extract game assets into `source_ui/` or a separate working directory. Keep extracted assets and generated mods out of commits.

## Coding Style

Use four-space indentation, `snake_case` for functions and variables, `PascalCase` for classes, and `UPPER_CASE` for constants. Follow nearby type annotations and use `pathlib.Path` for filesystem paths. Keep PySide6 out of the CLI and shared build code so command-line builds remain standard-library only. Match the surrounding formatting. The project has no configured formatter or linter.

## Testing

Use `test_*.py` modules and descriptive `test_*` functions. Put geometry, config, HUD, archive, and CLI cases in `tests/test_core.py` and editor interactions in `tests/test_gui.py`. Use `tmp_path` and synthetic SII fixtures so the suite runs without game files. GUI tests use Qt's offscreen platform. There is no configured coverage threshold.

## Commits and Pull Requests

Git history is unavailable in this checkout. Use a short, imperative commit subject such as `Fix mirror resize bounds`. In pull requests, describe the behavior change, link any related issue, and report the checks you ran. Include a screenshot for visible editor changes and the ETS2 version if you verified HUD compatibility in game.
