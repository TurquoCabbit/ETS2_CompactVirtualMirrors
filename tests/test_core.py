from dataclasses import replace
from fractions import Fraction
import subprocess
import sys
import zipfile

import pytest

from mirrors import config, hud
from mirrors.builder import MEMBERS, MOD_NAME, build, install
from mirrors.model import DEFAULT, HANDLES, Layout, Mirror, default_mirror, edit, move, resize, validate
from mirrors.workshop import stage


def test_legacy_config_round_trip_and_backup(legacy_ini):
    original = legacy_ini.read_bytes()
    old = config.load(legacy_ini)
    assert old == Layout(1440, 900, Mirror(20, 18, 160, 255, 5), Mirror(1260, 18, 160, 255, 5))
    changed = old.with_mirror("left", replace(old.left, x=99, frame_padding=0))
    config.save(legacy_ini, changed)
    assert config.load(legacy_ini) == changed
    assert old.right == changed.right
    assert b"Note = custom" in legacy_ini.read_bytes()
    assert b"PathWithCase = %APPDATA%/{custom}" in legacy_ini.read_bytes()
    assert legacy_ini.with_name("config.ini.bak").read_bytes() == original


def test_new_file_and_invalid_config_recovery(tmp_path):
    path = tmp_path / "new.ini"
    config.save(path, DEFAULT)
    assert config.load(path) == DEFAULT
    assert not path.with_name("new.ini.bak").exists()
    path.write_bytes(b"broken INI")
    with pytest.raises(ValueError, match="new.ini"):
        config.load(path)
    with pytest.raises(ValueError):
        config.save(path, DEFAULT)
    assert path.read_bytes() == b"broken INI"
    config.save(path, DEFAULT, replace_invalid=True)
    assert config.load(path) == DEFAULT
    assert path.with_name("new.ini.bak").read_bytes() == b"broken INI"


@pytest.mark.parametrize(("old", "new", "error"), [
    ("width = 1440", "width = 0", r"\[screen\] width"),
    ("x = 20", "x = -1", r"\[left\] x"),
    ("x = 20", "x = 1500", r"\[left\] x \+ width"),
    ("height = 255", "height = 0", r"\[left\] height"),
    ("width = 160", "width = 160.5", r"\[left\] width"),
    ("frame_padding = 5", "frame_padding = -5", r"\[left\] frame_padding"),
    ("y = 18", "Y = 18\ny = 20", r"\[left\] y is duplicated"),
])
def test_invalid_values(legacy_ini, old, new, error):
    legacy_ini.write_text(legacy_ini.read_text().replace(old, new, 1))
    with pytest.raises(ValueError, match=error):
        config.load(legacy_ini)


@pytest.mark.parametrize("handle", HANDLES)
def test_resize_keeps_opposite_edges_and_minimum(handle):
    x_dir, y_dir = HANDLES[handle]
    original = Mirror(80, 90, 200, 180, 5)
    result = resize(original, DEFAULT, handle, -1000 * x_dir, -1000 * y_dir, (40, 30))
    assert result.width == (40 if x_dir else original.width)
    assert result.height == (30 if y_dir else original.height)
    if x_dir < 0:
        assert result.x + result.width == original.x + original.width
    else:
        assert result.x == original.x
    if y_dir < 0:
        assert result.y + result.height == original.y + original.height
    else:
        assert result.y == original.y
    validate(DEFAULT.with_mirror("left", result))


def test_locked_size_numeric_and_pointer():
    original = Mirror(250, 300, 200, 100, 5)
    ratio = Fraction(2)
    assert edit(original, DEFAULT, "width", 100, (1, 1), ratio) == Mirror(250, 300, 100, 50, 5)
    assert edit(original, DEFAULT, "height", 60, (1, 1), ratio) == Mirror(250, 300, 120, 60, 5)
    assert resize(original, DEFAULT, "nw", -40, -20, ratio=ratio) == Mirror(210, 280, 240, 120, 5)
    assert resize(original, DEFAULT, "e", 40, 0, ratio=ratio) == Mirror(250, 290, 240, 120, 5)
    assert resize(original, DEFAULT, "s", 0, 20, ratio=ratio) == Mirror(230, 300, 240, 120, 5)
    result = resize(original, DEFAULT, "w", -1000, 0, (1, 1), ratio)
    validate(DEFAULT.with_mirror("left", result))
    assert result.x == 0
    assert abs(result.width / 2 - result.height) <= 0.5


def test_boundaries_snapping_and_small_canvas_reset():
    mirror = DEFAULT.left
    bottom = DEFAULT.height - mirror.height
    assert move(mirror, DEFAULT, 5, bottom - 3, snap=True) == replace(mirror, x=0, y=bottom)
    assert move(mirror, DEFAULT, -1000, 5000) == replace(mirror, x=0, y=bottom)
    result = resize(mirror, DEFAULT, "w", -14, 0, snap=True)
    assert result.x == 0 and result.width == 180
    assert default_mirror("right", 60, 90) == Mirror(0, 0, 60, 90, 5)
    assert resize(mirror, DEFAULT, "se", 5000, 5000).frame(DEFAULT.width, DEFAULT.height) == (
        15, 13, DEFAULT.width, DEFAULT.height)


def test_real_shape_synthetic_archive_and_all_presets(legacy_ini, source, tmp_path):
    settings = config.load(legacy_ini)
    original = {path.name: path.read_bytes() for path in source.iterdir()}
    target = build(settings, source.parent, tmp_path / "out")
    assert target.name == MOD_NAME
    with zipfile.ZipFile(target) as archive:
        assert tuple(archive.namelist()) == MEMBERS
        assert archive.testzip() is None
        for side, inner, frame in (
            ("left", (20, 180, 882, 627), (15, 185, 887, 622)),
            ("right", (1260, 1420, 882, 627), (1255, 1425, 887, 622)),
        ):
            output = archive.read(f"ui/hud_{side}.sii")
            assert b"// synthetic fixture\r\n" in output
            assert b'note: "unrelated { : // }"' in output
            bounds, container, presets = hud.inspect(output.decode(), side)
            assert bounds == (0, 1440, 900, 0)
            assert {mirror.integer("id") for _, _, mirror in presets} == set(hud.PRESETS)
            for group, border, mirror in presets:
                assert mirror.bounds() == inner
                assert group.bounds() == group.bounds("area") == border.bounds() == frame
            if side == "right":
                assert container.bounds() == container.bounds("area") == frame
    assert {path.name: path.read_bytes() for path in source.iterdir()} == original
    assert hud.transform((20, 18, 180, 273), DEFAULT, (10, 1450, 900, 0)) == (25, 145, 885, 672)


@pytest.mark.parametrize(("old", "new", "reason"), [
    (b"SiiNunit", b"Other", "SiiNunit"),
    (b"coords_l: 15", b"coords_l: bogus", "coords_l"),
    (b"value: far", b"value: close", "binding"),
    (b"id: 10", b"id: 990", "binding"),
    (b"my_children[1]: preset.a.mirror", b"my_children[1]: nowhere", "child link"),
    (b"color=@@clr_mirror_frame@@", b"color=other", "frame marker"),
])
def test_invalid_hud_reports_file_and_keeps_previous_build(source, tmp_path, old, new, reason):
    destination = tmp_path / "out"
    target = build(DEFAULT, source, destination)
    before = target.read_bytes()
    right = source / "hud_right.sii"
    right.write_bytes(right.read_bytes().replace(old, new, 1))
    with pytest.raises(ValueError, match=rf"hud_right.sii.*{reason}.*Extract fresh"):
        build(DEFAULT, source, destination)
    assert target.read_bytes() == before


def test_missing_hud_and_official_game_output_guard(source, tmp_path):
    game = tmp_path / "game"
    game.mkdir()
    with pytest.raises(ValueError, match="outside"):
        build(DEFAULT, source, game / "mods", game=game)
    (source / "hud_left.sii").unlink()
    with pytest.raises(ValueError, match="both"):
        build(DEFAULT, source, tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_install_validates_archive_and_protects_file_collision(source, tmp_path):
    artifact = build(DEFAULT, source, tmp_path / "out")
    mod = tmp_path / "mod"
    target = install(artifact, mod)
    assert target.read_bytes() == artifact.read_bytes()
    target.write_bytes(b"previous")
    with pytest.raises(FileExistsError):
        install(artifact, mod)
    assert target.read_bytes() == b"previous"
    assert install(artifact, mod, overwrite=True).read_bytes() == artifact.read_bytes()
    artifact.write_bytes(b"invalid ZIP")
    with pytest.raises(zipfile.BadZipFile):
        install(artifact, mod, overwrite=True)
    with zipfile.ZipFile(target) as archive:
        assert archive.testzip() is None


def test_cli_workflow(legacy_ini, source, tmp_path):
    arguments = ["-m", "mirrors.cli", "--config", str(legacy_ini), "--source", str(source),
                 "--output", str(tmp_path / "CLI output")]
    result = subprocess.run([sys.executable, *arguments], cwd=config.PROJECT,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "CLI output" / MOD_NAME).is_file()
    (source / "hud_right.sii").unlink()
    result = subprocess.run([sys.executable, *arguments], cwd=config.PROJECT,
                            capture_output=True, text=True)
    assert result.returncode == 1
    assert "hud_right.sii" in result.stderr


def test_workshop_staging_uses_compact_preset_and_versioned_packages(source, tmp_path):
    workshop = stage(source, tmp_path / "workshop")
    versions = (workshop / "versions.sii").read_text(encoding="utf-8")
    assert 'compatible_versions[]: "1.62.*"' in versions
    assert 'package_name: "compact_1_62"' in versions
    assert 'package_name: "unsupported"' in versions and 'informational: true' in versions
    assert {path.name for path in workshop.iterdir()} == {"versions.sii", "compact_1_62", "unsupported"}
    package = workshop / "compact_1_62"
    assert (package / "mod_icon.jpg").read_bytes().startswith(b"\xff\xd8")
    manifest = (package / "manifest.sii").read_text(encoding="utf-8")
    assert 'author: "TurquoCabbit"' in manifest and 'description_file: "description.txt"' in manifest
    assert not (workshop / "unsupported" / "ui").exists()
    local_archive = build(config.load(config.COMPACT_PRESET), source, tmp_path / "local")
    with zipfile.ZipFile(local_archive) as archive:
        for member in MEMBERS:
            assert (package / member).read_bytes() == archive.read(member)
    with pytest.raises(FileExistsError):
        stage(source, workshop)
    with pytest.raises(ValueError, match="version pattern"):
        stage(source, tmp_path / "invalid", '1.62.*"')
    assert not (tmp_path / "invalid").exists()
