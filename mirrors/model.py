from dataclasses import dataclass, replace
from fractions import Fraction
from typing import Literal

Side = Literal["left", "right"]
SIDES = ("left", "right")
FIELDS = ("x", "y", "width", "height", "frame_padding")
# QSpinBox and Qt scene coordinates must share a representable range.
MAX_VALUE = 1_000_000
SNAP_DISTANCE = 8
HANDLES = {
    "nw": (-1, -1), "n": (0, -1), "ne": (1, -1), "e": (1, 0),
    "se": (1, 1), "s": (0, 1), "sw": (-1, 1), "w": (-1, 0),
}


@dataclass(frozen=True)
class Mirror:
    x: int
    y: int
    width: int
    height: int
    frame_padding: int

    def frame(self, width: int, height: int) -> tuple[int, int, int, int]:
        pad = self.frame_padding
        return (
            max(0, self.x - pad), max(0, self.y - pad),
            min(width, self.x + self.width + pad),
            min(height, self.y + self.height + pad),
        )


@dataclass(frozen=True)
class Layout:
    width: int
    height: int
    left: Mirror
    right: Mirror
    game_defaults: frozenset[Side] = frozenset()

    def mirror(self, side: Side) -> Mirror:
        return self.left if side == "left" else self.right

    def with_mirror(self, side: Side, mirror: Mirror, *, use_game_defaults=False) -> "Layout":
        game_defaults = self.game_defaults
        if use_game_defaults:
            game_defaults = game_defaults | {side}
        elif mirror != self.mirror(side):
            game_defaults = game_defaults - {side}
        return replace(self, game_defaults=game_defaults, **{side: mirror})


def clamp(value, low, high):
    return max(low, min(high, value))


def default_mirror(side: Side, width: int, height: int, minimum=(1, 1)) -> Mirror:
    w = clamp(160, minimum[0], width)
    h = clamp(255, minimum[1], height)
    inset = min(20, width - w)
    x = inset if side == "left" else width - w - inset
    return Mirror(x, min(18, height - h), w, h, 5)


DEFAULT_WIDTH = 1920
DEFAULT_HEIGHT = 1080
DEFAULT = Layout(DEFAULT_WIDTH, DEFAULT_HEIGHT,
                 default_mirror("left", DEFAULT_WIDTH, DEFAULT_HEIGHT),
                 default_mirror("right", DEFAULT_WIDTH, DEFAULT_HEIGHT))


def validate(layout: Layout, minimum=(1, 1)) -> None:
    for field, value in (("width", layout.width), ("height", layout.height)):
        if type(value) is not int or not 1 <= value <= MAX_VALUE:
            raise ValueError(f"[screen] {field} must be an integer from 1 to {MAX_VALUE}.")
    for side in SIDES:
        mirror = layout.mirror(side)
        for field in FIELDS:
            value = getattr(mirror, field)
            if type(value) is not int or not 0 <= value <= MAX_VALUE:
                raise ValueError(f"[{side}] {field} must be an integer from 0 to {MAX_VALUE}.")
        if mirror.width < minimum[0]:
            raise ValueError(f"[{side}] width must be at least {minimum[0]}.")
        if mirror.height < minimum[1]:
            raise ValueError(f"[{side}] height must be at least {minimum[1]}.")
        if mirror.x + mirror.width > layout.width:
            raise ValueError(f"[{side}] x + width exceeds the screen width ({layout.width}).")
        if mirror.y + mirror.height > layout.height:
            raise ValueError(f"[{side}] y + height exceeds the screen height ({layout.height}).")


def snap_position(value: int, limit: int) -> int:
    edge = 0 if abs(value) <= abs(limit - value) else limit
    return edge if abs(value - edge) <= SNAP_DISTANCE else value


def move(mirror: Mirror, layout: Layout, x: int, y: int, snap=False) -> Mirror:
    max_x, max_y = layout.width - mirror.width, layout.height - mirror.height
    if snap:
        x, y = snap_position(x, max_x), snap_position(y, max_y)
    return replace(mirror, x=clamp(x, 0, max_x), y=clamp(y, 0, max_y))


def _locked_dimensions(w, h, min_w, min_h, max_w, max_h, ratio, horizontal):
    # Use the dragged axis as the primary dimension. Search integer values
    # against the same rounding rule used to derive the companion dimension.
    if not horizontal:
        size = _locked_dimensions(h, w, min_h, min_w, max_h, max_w, 1 / ratio, True)
        return (size[1], size[0]) if size else None

    def paired(width):
        return max(1, round(Fraction(width) / ratio))

    def first_at_least(target):
        low, high = min_w, max_w + 1
        while low < high:
            mid = (low + high) // 2
            if paired(mid) < target:
                low = mid + 1
            else:
                high = mid
        return low

    low, high = first_at_least(min_h), first_at_least(max_h + 1) - 1
    if low > high:
        return None
    width = clamp(w, low, high)
    return width, paired(width)


def resize(mirror: Mirror, layout: Layout, handle: str, dx: int, dy: int,
           minimum=(1, 1), ratio=None, snap=False, *, numeric=False) -> Mirror:
    horizontal, vertical = HANDLES[handle]
    if not (dx * horizontal or dy * vertical):
        return mirror
    x0, y0, w0, h0 = mirror.x, mirror.y, mirror.width, mirror.height
    x1, y1 = x0 + w0, y0 + h0
    anchor_x = x1 if horizontal < 0 else x0
    anchor_y = y1 if vertical < 0 else y0
    max_w = anchor_x if horizontal < 0 else layout.width - anchor_x
    max_h = anchor_y if vertical < 0 else layout.height - anchor_y
    w, h = w0 + horizontal * dx, h0 + vertical * dy
    if snap:
        if horizontal and abs(max_w - w) <= SNAP_DISTANCE:
            w = max_w
        if vertical and abs(max_h - h) <= SNAP_DISTANCE:
            h = max_h

    center_x = not horizontal and not numeric
    center_y = not vertical and not numeric
    if ratio:
        if center_x:
            max_w = min(2 * x0 + w0 + 1, 2 * (layout.width - x1) + w0)
        if center_y:
            max_h = min(2 * y0 + h0 + 1, 2 * (layout.height - y1) + h0)
        primary_x = bool(horizontal) and (
            not vertical or abs(w - w0) * h0 >= abs(h - h0) * w0
        )
        dimensions = _locked_dimensions(w, h, *minimum, max_w, max_h, ratio, primary_x)
        if dimensions is None:
            return mirror
        w, h = dimensions
    else:
        w = clamp(w, minimum[0], max_w)
        h = clamp(h, minimum[1], max_h)

    x = anchor_x - w if horizontal < 0 else anchor_x
    y = anchor_y - h if vertical < 0 else anchor_y
    if center_x:
        x = (2 * x0 + w0 - w + 1) // 2
    if center_y:
        y = (2 * y0 + h0 - h + 1) // 2
    return Mirror(x, y, w, h, mirror.frame_padding)


def edit(mirror: Mirror, layout: Layout, field: str, value: int, minimum, ratio):
    if field == "x":
        return move(mirror, layout, value, mirror.y)
    if field == "y":
        return move(mirror, layout, mirror.x, value)
    if field == "width":
        return resize(mirror, layout, "e", value - mirror.width, 0, minimum, ratio, numeric=True)
    if field == "height":
        return resize(mirror, layout, "s", 0, value - mirror.height, minimum, ratio, numeric=True)
    if field == "frame_padding":
        return replace(mirror, frame_padding=clamp(value, 0, MAX_VALUE))
    raise ValueError(f"Unknown mirror field: {field}")
