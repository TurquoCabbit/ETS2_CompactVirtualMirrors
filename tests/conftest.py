from pathlib import Path

import pytest


@pytest.fixture
def legacy_ini(tmp_path: Path):
    path = tmp_path / "config.ini"
    path.write_text("""[screen]
width = 1440
height = 900
Note = custom

[left]
x = 20
y = 18
width = 160
height = 255
frame_padding = 5

[right]
x = 1260
y = 18
width = 160
height = 255
frame_padding = 5

[external]
PathWithCase = %APPDATA%/{custom}
""", encoding="utf-8")
    return path


def _unit(kind, name, properties, parent, bounds, area, children=()):
    properties = dict(properties)
    properties["my_parent"] = parent
    if children:
        properties["my_children"] = len(children)
        properties.update({f"my_children[{i}]": name for i, name in enumerate(children)})
    for prefix, values in (("coords", bounds), ("area", area)):
        properties.update({f"{prefix}_{edge}": value
                           for edge, value in zip(("l", "r", "t", "b"), values)})
    lines = "\n".join(f" {key}: {value}" for key, value in properties.items())
    return f"{kind} : {name} {{\n{lines}\n}}\n"


@pytest.fixture
def source(tmp_path):
    folder = tmp_path / "extracted HUD" / "ui"
    folder.mkdir(parents=True)
    screen = (0, 1440, 900, 0)
    group_names = ("preset.a", "preset.b", "preset.c", "preset.d")
    local = (1, 0, 0, 1)
    for side in ("left", "right"):
        parent = "root" if side == "left" else "container"
        root_children = group_names if side == "left" else (parent,)
        parts = [_unit("ui_blend_only_window", "root", {
            "keep_aspect": side, "clip_children": "true", "note": '"unrelated { : // }"'
        }, "null", screen, screen, root_children)]
        if side == "right":
            parts.append(_unit("ui::group", parent, {"id": 400, "fitting": "false"},
                               "root", (10, 220, 800, 500), (10, 220, 800, 500), group_names))
        for i, (template, group) in enumerate(zip(("", "3", "2", "4"), group_names), 1):
            mirror_name, frame_name = f"{group}.mirror", f"{group}.frame"
            frame = (10, 220, 800, 500 + i)
            parts.extend((
                _unit("ui::group", group, {"id": 100 + i * 10, "fitting": "true"}, parent,
                      frame, frame, (frame_name, mirror_name)),
                _unit("ui::text", frame_name, {
                    "text": '"<img src=/material/ui/white.mat color=@@clr_mirror_frame@@>"',
                    "layer": 2,
                }, group, frame, local),
                _unit("ui::text_common", mirror_name, {
                    "id": i * 10, "look_template": f"txt.mirrors{template}",
                    "value": "close" if side == "left" else "far",
                    "text": '""', "layer": 3,
                }, group, (15, 215, 795, 510 + i), local),
            ))
        text = "SiiNunit\n{\n// synthetic fixture\n" + "\n".join(parts) + "}\n"
        (folder / f"hud_{side}.sii").write_bytes(text.replace("\n", "\r\n").encode())
    return folder
