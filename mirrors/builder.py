import os
from pathlib import Path
import shutil
import tempfile
import zipfile

from .hud import game_mirror, inspect, rewrite
from .model import Layout, Mirror, SIDES, Side, validate

MOD_NAME = "ets2_configurable_mirrors.scs"
MEMBERS = tuple(f"ui/hud_{side}.sii" for side in SIDES)


def _sources(source: Path):
    names = tuple(Path(member).name for member in MEMBERS)
    complete = [path for path in (source, source / "ui")
                if all((path / name).is_file() for name in names)]
    if len(complete) != 1:
        if complete:
            raise ValueError(f"{source}: two HUD pairs found. Select the intended ui directory.")
        raise ValueError(f"{source}: select an extracted folder containing both "
                         "ui/hud_left.sii and ui/hud_right.sii, or select its ui directory.")
    return tuple(complete[0] / name for name in names)


def load_game_mirror(source: Path, side: Side, layout: Layout) -> Mirror:
    path = _sources(source)[SIDES.index(side)]
    try:
        return game_mirror(path.read_bytes(), side, layout)
    except (OSError, ValueError) as exc:
        raise ValueError(f"{path}: {exc}") from exc


def validate_source(source: Path) -> None:
    for side, path in zip(SIDES, _sources(source)):
        try:
            inspect(path.read_text(encoding="utf-8-sig"), side)
        except (OSError, ValueError) as exc:
            raise ValueError(f"{path}: {exc}") from exc


def protect_game(path: Path, game: Path | None = None) -> None:
    resolved = path.resolve()
    if game and resolved.is_relative_to(game.resolve()):
        raise ValueError(f"{path}: choose a directory outside the ETS2 installation.")
    if any((parent / "bin" / "win_x64" / "eurotrucks2.exe").is_file()
           for parent in (resolved.parent, *resolved.parent.parents)):
        raise ValueError(f"{path}: choose a directory outside the ETS2 installation.")


def _check_archive(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        if archive.namelist() != list(MEMBERS) or archive.testzip() is not None:
            raise ValueError(f"{path}: the mod archive failed its integrity check.")


def render_huds(layout: Layout, source: Path) -> dict[str, bytes]:
    validate(layout)
    files = {}
    for side, member, path in zip(SIDES, MEMBERS, _sources(source)):
        try:
            files[member] = rewrite(path.read_bytes(), side, layout)
        except (OSError, ValueError) as exc:
            raise ValueError(f"{path}: {exc} Extract fresh UI files from your target ETS2 "
                             "version. The builder requires the supported four-preset layout.") from exc
    return files


def build(layout: Layout, source: Path, output: Path, *, game: Path | None = None,
          progress=lambda message: None) -> Path:
    target = (output / MOD_NAME).absolute()
    protect_game(target, game)
    progress("Validating extracted HUD files…")
    files = render_huds(layout, source)

    progress("Packaging and checking the mod archive…")
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{MOD_NAME}.", dir=target.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            for member, contents in files.items():
                archive.writestr(member, contents)
        _check_archive(temporary)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def install(artifact: Path, mod_directory: Path, *, overwrite=False, game: Path | None = None,
            progress=lambda message: None) -> Path:
    if artifact.name != MOD_NAME:
        raise ValueError("Select the archive produced by Build Mod.")
    target = (mod_directory / MOD_NAME).absolute()
    protect_game(target, game)
    if target.resolve() == artifact.resolve():
        _check_archive(artifact)
        return target
    if target.exists() and not overwrite:
        raise FileExistsError(f"{target} already exists.")
    progress("Copying the mod archive…")
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{MOD_NAME}.", dir=target.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        shutil.copyfile(artifact, temporary)
        _check_archive(temporary)
        if overwrite:
            temporary.replace(target)
        elif os.name == "nt":
            temporary.rename(target)
        else:
            # Publish a complete file without overwriting a newly created mod.
            os.link(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target
