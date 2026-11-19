import argparse
from pathlib import Path
import re
import tempfile

from .builder import protect_game, render_huds
from .config import COMPACT_PRESET, PROJECT, load
from .release_info import AUTHOR

ASSETS = PROJECT / "workshop"
MOD_VERSION = "1.0.0"
DEFAULT_COMPATIBILITY = "1.62.*"


def stage(source: Path, output: Path, compatibility: str = DEFAULT_COMPATIBILITY) -> Path:
    if not re.fullmatch(r"\d+\.\d+(?:\.\d+)*(?:\.\*)?", compatibility, re.ASCII):
        raise ValueError("Use a game version pattern such as 1.62.*.")
    output = output.resolve()
    protect_game(output / "versions.sii")
    if output.exists():
        raise FileExistsError(f"{output} already exists. Choose a new staging directory.")
    hud = render_huds(load(COMPACT_PRESET), source)
    icon = (ASSETS / "mod_icon.jpg").read_bytes()
    package_name = f"compact_{compatibility.rstrip('.*').replace('.', '_')}"
    versions = f'''SiiNunit
{{
package_version_info : .compact {{
    package_name: "{package_name}"
    compatible_versions[]: "{compatibility}"
}}
package_version_info : .unsupported {{
    package_name: "unsupported"
    informational: true
}}
}}
'''
    manifest = f'''SiiNunit
{{
mod_package : .compact {{
    package_version: "{MOD_VERSION}"
    author: "{AUTHOR}"
    category[]: "ui"
    icon: "mod_icon.jpg"
    description_file: "description.txt"
}}
}}
'''
    description = (
        "Moves ETS2's virtual mirrors into compact frames in the top corners.\n\n"
        "Activate this mod in Mod Manager. Use F2 for the in-game virtual mirror controls. "
        "Use only one mod that changes the virtual mirror HUD.\n"
    )
    unsupported = (f"This version of Compact Virtual Mirrors targets ETS2 {compatibility}.\n"
                   "Check the Workshop page for supported game versions.\n")

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".workshop-", dir=output.parent) as temporary:
        staging = Path(temporary) / "item"
        for name, text in ((package_name, description), ("unsupported", unsupported)):
            package = staging / name
            package.mkdir(parents=True)
            (package / "manifest.sii").write_text(manifest, encoding="utf-8")
            (package / "description.txt").write_text(text, encoding="utf-8")
            (package / "mod_icon.jpg").write_bytes(icon)
        for member, contents in hud.items():
            target = staging / package_name / member
            target.parent.mkdir(exist_ok=True)
            target.write_bytes(contents)
        (staging / "versions.sii").write_text(versions, encoding="utf-8")
        staging.rename(output)
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description="Stage Compact Virtual Mirrors for Steam Workshop.")
    parser.add_argument("--source", type=Path, required=True, help="Extracted ETS2 HUD folder")
    parser.add_argument("--output", type=Path, required=True, help="New Workshop staging directory")
    parser.add_argument("--compatibility", default=DEFAULT_COMPATIBILITY,
                        help=f"SCS game version pattern (default: {DEFAULT_COMPATIBILITY})")
    options = parser.parse_args(argv)
    try:
        output = stage(options.source, options.output, options.compatibility)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Workshop staging failed: {exc}\n")
    print(f"Workshop data: {output}")
    print(f"Workshop preview: {ASSETS / 'preview.jpg'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
