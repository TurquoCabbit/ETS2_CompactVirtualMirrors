import configparser
from io import StringIO
import os
from pathlib import Path
import re
import tempfile

from .model import FIELDS, Layout, Mirror, SIDES, validate

PROJECT = Path(__file__).resolve().parent.parent
COMPACT_PRESET = Path(__file__).with_name("compact.ini")


def _parser():
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    return parser


def _integer(parser, section, key, *, default=None):
    matches = [k for k in parser[section] if k.casefold() == key]
    if not matches and default is not None:
        return default
    if len(matches) != 1:
        problem = "is missing" if not matches else "is duplicated"
        raise ValueError(f"[{section}] {key} {problem}.")
    value = parser[section][matches[0]].strip()
    if not re.fullmatch(r"[+-]?[0-9]+", value):
        raise ValueError(f"[{section}] {key} must be an integer.")
    try:
        return int(value)
    except ValueError:
        raise ValueError(f"[{section}] {key} must be an integer.") from None


def _read(path: Path):
    parser = _parser()
    contents = path.read_bytes()
    parser.read_string(contents.decode("utf-8-sig"), source=str(path))
    return parser, contents


def load(path: Path) -> Layout:
    try:
        parser, _ = _read(path)
        parser.defaults().clear()
        for section in ("screen", *SIDES):
            if section not in parser:
                raise ValueError(f"Missing [{section}] section.")
        width, height = (_integer(parser, "screen", key) for key in ("width", "height"))
        mirrors = [Mirror(*(_integer(parser, side, field) for field in FIELDS)) for side in SIDES]
        game_defaults = set()
        for side in SIDES:
            enabled = _integer(parser, side, "use_game_defaults", default=0)
            if enabled not in (0, 1):
                raise ValueError(f"[{side}] use_game_defaults must be 0 or 1.")
            if enabled:
                game_defaults.add(side)
        layout = Layout(width, height, *mirrors, game_defaults=frozenset(game_defaults))
        validate(layout)
        return layout
    except (OSError, configparser.Error, ValueError) as exc:
        raise ValueError(f"{path}: {exc}") from exc


def _replace_bytes(path: Path, contents: bytes):
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(contents)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def save(path: Path, layout: Layout, *, replace_invalid=False, template: Path | None = None) -> None:
    validate(layout)
    try:
        original = None
        parser = _parser()
        if path.exists():
            original = path.read_bytes()
            try:
                parser.read_string(original.decode("utf-8-sig"), source=str(path))
            except (configparser.Error, UnicodeError):
                if not replace_invalid:
                    raise
                parser = _parser()
        elif template is not None and template.is_file():
            try:
                parser, _ = _read(template)
            except (configparser.Error, UnicodeError):
                pass
        settings = {
            "screen": {"width": layout.width, "height": layout.height},
            **{side: {field: getattr(layout.mirror(side), field) for field in FIELDS}
               for side in SIDES},
        }
        defaults = parser.defaults().copy()
        parser.defaults().clear()
        for section, values in settings.items():
            if not parser.has_section(section):
                parser.add_section(section)
            existing_keys = [key for key, _ in parser.items(section, raw=True)]
            if section in SIDES and (section in layout.game_defaults or
                                     any(k.casefold() == "use_game_defaults" for k in existing_keys)):
                values["use_game_defaults"] = int(section in layout.game_defaults)
            for key, value in values.items():
                # Retain spelling for known section keys and leave other settings intact.
                matches = [k for k in existing_keys if k.casefold() == key]
                target = matches[0] if matches else key
                for duplicate in matches[1:]:
                    parser.remove_option(section, duplicate)
                parser.set(section, target, str(value))
        parser.defaults().update(defaults)
        stream = StringIO()
        parser.write(stream)
        if original is not None:
            _replace_bytes(path.with_name(path.name + ".bak"), original)
        _replace_bytes(path, stream.getvalue().encode("utf-8"))
    except (OSError, configparser.Error, ValueError) as exc:
        raise ValueError(f"{path}: {exc}") from exc
