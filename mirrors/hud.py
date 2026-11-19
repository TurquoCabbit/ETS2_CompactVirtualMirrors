from dataclasses import dataclass
from fractions import Fraction
import re

from .model import Layout, Mirror, Side, clamp

EDGES = ("l", "r", "t", "b")
PRESETS = {
    10: (110, "txt.mirrors"),
    20: (120, "txt.mirrors3"),
    30: (130, "txt.mirrors2"),
    40: (140, "txt.mirrors4"),
}
TOKEN = re.compile(
    r'(?P<space>\s+|//[^\r\n]*|\#[^\r\n]*|/\*[\s\S]*?\*/)'
    r'|(?P<string>"(?:\\[\s\S]|[^"\\])*")'
    r'|(?P<word>[^\s{}:\[\]"#]+?(?=\s|[{}:\[\]"#]|//|/\*|$))'
    r'|(?P<symbol>[{}:\[\]])'
)
INTEGER = re.compile(r"[+-]?[0-9]+\Z")


@dataclass
class Unit:
    kind: str
    name: str
    properties: dict[str, list[re.Match]]

    def get(self, field):
        tokens = self.properties.get(field, ())
        return tokens[0][0] if len(tokens) == 1 else ""

    def integer(self, field):
        tokens = self.properties.get(field, ())
        if len(tokens) != 1 or not INTEGER.fullmatch(tokens[0][0]):
            raise ValueError(f"{self.name}.{field} must contain one integer.")
        return int(tokens[0][0])

    def bounds(self, prefix="coords"):
        return tuple(self.integer(f"{prefix}_{edge}") for edge in EDGES)


def parse(text):
    tokens = []
    offset = 0
    while offset < len(text):
        match = TOKEN.match(text, offset)
        if match is None:
            line = text.count("\n", 0, offset) + 1
            raise ValueError(f"Unsupported SII token on line {line}.")
        if match.lastgroup == "word" and match[0] == "@include":
            raise ValueError("SII includes are unsupported. Select the standalone extracted HUD.")
        if match.lastgroup != "space":
            tokens.append(match)
        offset = match.end()

    index = 0

    def peek():
        return tokens[index][0] if index < len(tokens) else ""

    def take(expected=None):
        nonlocal index
        if not peek() or (expected is not None and peek() != expected):
            raise ValueError(f"Expected {expected or 'an SII token'}, found {peek() or 'end of file'}.")
        token = tokens[index]
        index += 1
        return token

    def atom():
        token = take()
        if token.lastgroup != "word":
            raise ValueError(f"Expected an SII identifier, found {token[0]}.")
        return token[0]

    def property_start():
        if index + 1 >= len(tokens) or tokens[index].lastgroup != "word":
            return False
        return tokens[index + 1][0] in (":", "[")

    take("SiiNunit")
    take("{")
    units = {}
    while peek() != "}":
        kind = atom()
        take(":")
        if peek() == ":":
            take(":")
            kind += "::" + atom()
            take(":")
        name = atom()
        take("{")
        properties = {}
        while peek() != "}":
            field = atom()
            if peek() == "[":
                take("[")
                field += "[" + ("" if peek() == "]" else atom()) + "]"
                take("]")
            take(":")
            if field in properties:
                raise ValueError(f"Duplicate SII field {name}.{field}.")
            value = [take()]
            if value[0].lastgroup == "symbol":
                raise ValueError(f"Missing or unsupported value for {name}.{field}.")
            while peek() and peek() != "}" and not property_start():
                if peek() == "{":
                    raise ValueError(f"Unsupported nested block in {name}.{field}.")
                value.append(take())
            properties[field] = value
        take("}")
        if name in units:
            raise ValueError(f"Duplicate SII unit {name}.")
        units[name] = Unit(kind, name, properties)
    take("}")
    if peek():
        raise ValueError("Unexpected text after the SiiNunit block.")
    return units


def _children(unit, units):
    count = unit.integer("my_children")
    references = {k for k in unit.properties if k.startswith("my_children[")}
    if count != len(references):
        raise ValueError(f"{unit.name} has an inconsistent my_children count.")
    result = []
    for index in range(count):
        name = unit.get(f"my_children[{index}]")
        if name not in units or units[name].get("my_parent") != unit.name:
            raise ValueError(f"{unit.name} has an invalid child link at my_children[{index}].")
        result.append(units[name])
    if len({child.name for child in result}) != count:
        raise ValueError(f"{unit.name} links to the same child more than once.")
    return result


def _valid_bounds(unit, prefix="coords"):
    left, right, top, bottom = unit.bounds(prefix)
    if left >= right or bottom >= top:
        raise ValueError(f"{unit.name} has empty or inverted {prefix} bounds.")
    return left, right, top, bottom


def inspect(text: str, side: Side):
    units = parse(text)
    roots = [u for u in units.values() if u.kind == "ui_blend_only_window"]
    if len(roots) != 1 or roots[0].get("my_parent") != "null":
        raise ValueError("Expected one top-level ui_blend_only_window.")
    window = roots[0]
    if window.get("keep_aspect") != side or window.get("clip_children") != "true":
        raise ValueError(f"{window.name} has unsupported anchoring or clipping.")
    bounds = _valid_bounds(window)
    if _valid_bounds(window, "area") != bounds:
        raise ValueError(f"{window.name} has different coordinate and area bounds.")
    variants = _children(window, units)
    container = None
    if len(variants) == 1 and variants[0].kind == "ui::group":
        container = variants[0]
        if container.get("fitting") != "false" or container.integer("id") != 400:
            raise ValueError(f"{container.name} is not the expected mirror preset container.")
        variants = _children(container, units)
        if _valid_bounds(container) != _valid_bounds(container, "area"):
            raise ValueError(f"{container.name} has different coordinate and area bounds.")
    if len(variants) != 4 or any(u.kind != "ui::group" for u in variants):
        raise ValueError(f"{window.name} must contain four groups for the native mirror presets.")

    triples = []
    seen = set()
    camera = "close" if side == "left" else "far"
    for group in variants:
        children = _children(group, units)
        mirrors = [u for u in children if u.kind == "ui::text_common"]
        frames = [u for u in children if u.kind == "ui::text"]
        if len(children) != 2 or len(mirrors) != 1 or len(frames) != 1:
            raise ValueError(f"{group.name} must link to one mirror and one frame.")
        mirror, frame = mirrors[0], frames[0]
        preset = mirror.integer("id")
        expected = (group.integer("id"), mirror.get("look_template"))
        if (preset in seen or PRESETS.get(preset) != expected or mirror.get("value") != camera
                or group.get("fitting") != "true"):
            raise ValueError(f"{mirror.name} has an unsupported camera or preset binding.")
        frame_text = frame.get("text")
        attributes = frame_text.removeprefix('"<img ').removesuffix('>"').split()
        if not (frame_text.startswith('"<img ') and "src=/material/ui/white.mat" in attributes
                and "color=@@clr_mirror_frame@@" in attributes):
            raise ValueError(f"{frame.name} is missing the expected mirror frame marker.")
        inner = _valid_bounds(mirror)
        outer = _valid_bounds(frame)
        if not (outer[0] <= inner[0] < inner[1] <= outer[1]
                and outer[3] <= inner[3] < inner[2] <= outer[2]):
            raise ValueError(f"{mirror.name} does not fit within its frame {frame.name}.")
        for unit in (mirror, frame):
            if unit.bounds("area") != (1, 0, 0, 1):
                raise ValueError(f"{unit.name} has unsupported local area bounds.")
        if not _valid_bounds(group, "area") == _valid_bounds(group) == outer:
            raise ValueError(f"{group.name} does not share the bounds of its frame {frame.name}.")
        seen.add(preset)
        triples.append((group, frame, mirror))
    return bounds, container, triples


def transform(rect, layout: Layout, bounds):
    x0, y0, x1, y1 = rect
    left, right, top, bottom = bounds
    scale_x = Fraction(right - left, layout.width)
    scale_y = Fraction(top - bottom, layout.height)
    return (left + round(x0 * scale_x), left + round(x1 * scale_x),
            top - round(y0 * scale_y), top - round(y1 * scale_y))


def game_mirror(source: bytes, side: Side, layout: Layout) -> Mirror:
    bounds, _, triples = inspect(source.decode("utf-8-sig"), side)
    # Preset 10 is the standard txt.mirrors template. HUD group order varies by side.
    frame, mirror = next((frame, mirror) for _, frame, mirror in triples
                         if mirror.integer("id") == 10)
    left, right, top, bottom = bounds
    scale_x = Fraction(layout.width, right - left)
    scale_y = Fraction(layout.height, top - bottom)
    ml, mr, mt, mb = mirror.bounds()
    fl, fr, ft, fb = frame.bounds()
    x0 = clamp(round((ml - left) * scale_x), 0, layout.width - 1)
    y0 = clamp(round((top - mt) * scale_y), 0, layout.height - 1)
    x1 = clamp(round((mr - left) * scale_x), x0 + 1, layout.width)
    y1 = clamp(round((top - mb) * scale_y), y0 + 1, layout.height)
    # The preview has one padding value, while native padding can vary by edge.
    padding = round(((ml - fl + fr - mr) * scale_x + (ft - mt + mb - fb) * scale_y) / 4)
    return Mirror(x0, y0, x1 - x0, y1 - y0, min(padding, max(layout.width, layout.height)))


def rewrite(source: bytes, side: Side, layout: Layout) -> bytes:
    text = source.decode("utf-8-sig")
    bounds, container, triples = inspect(text, side)
    if side in layout.game_defaults:
        return source
    mirror = layout.mirror(side)
    inner = transform((mirror.x, mirror.y, mirror.x + mirror.width, mirror.y + mirror.height),
                      layout, bounds)
    frame = transform(mirror.frame(layout.width, layout.height), layout, bounds)
    if inner[0] >= inner[1] or inner[2] <= inner[3]:
        raise ValueError(f"[{side}] mirror rounds to zero HUD size. Increase its width or height.")
    replacements = []

    def set_bounds(unit, values, prefix="coords"):
        for edge, value in zip(EDGES, values):
            token, = unit.properties[f"{prefix}_{edge}"]
            replacements.append((token.start(), token.end(), str(value)))

    for group, frame_unit, mirror_unit in triples:
        set_bounds(mirror_unit, inner)
        set_bounds(frame_unit, frame)
        set_bounds(group, frame)
        set_bounds(group, frame, "area")
    if container is not None:
        set_bounds(container, frame)
        set_bounds(container, frame, "area")
    for start, end, replacement in sorted(replacements, reverse=True):
        text = text[:start] + replacement + text[end:]
    inspect(text, side)
    return text.encode("utf-8-sig" if source.startswith(b"\xef\xbb\xbf") else "utf-8")
