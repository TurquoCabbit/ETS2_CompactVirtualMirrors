import argparse
from pathlib import Path
import sys
import zipfile

from .builder import build
from .config import PROJECT, load
from .release_info import APP_NAME, VERSION


def main(argv=None):
    if sys.version_info < (3, 11):
        print("The builder requires Python 3.11 or newer. See README.md.", file=sys.stderr)
        return 1
    parser = argparse.ArgumentParser(description="Build the ETS2 Configurable Mirrors mod.")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {VERSION}")
    parser.add_argument("--config", type=Path, default=PROJECT / "config.ini")
    parser.add_argument("--source", type=Path, default=PROJECT / "source_ui")
    parser.add_argument("--output", type=Path, default=PROJECT / "output")
    parser.add_argument("--game", type=Path, help="Optional ETS2 installation directory")
    options = parser.parse_args(argv)
    try:
        artifact = build(load(options.config), options.source, options.output, game=options.game)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"Build failed: {exc}", file=sys.stderr)
        return 1
    print(f"Built {artifact}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
