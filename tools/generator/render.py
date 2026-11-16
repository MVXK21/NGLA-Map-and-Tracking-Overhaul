"""Draw the world map from LAND records.

First-pass style: height-based colour ramp, hillshading and the land's own
vertex colours. The art style is still to be decided; this is for checking
coverage and alignment.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw

from extract import CELL_UNITS

SAMPLES = 64  # use 64 of the 65 vertices; the last row/column repeats the neighbour's edge
OCEAN_FLOOR = -1500.0


@dataclass
class MapFrame:
    """Where the image sits in world coordinates."""
    min_x: int        # westmost cell column
    max_y: int        # northmost cell row
    cols: int
    rows: int
    px: int           # pixels per cell

    def to_pixel(self, x: float, y: float) -> tuple[float, float]:
        return ((x / CELL_UNITS - self.min_x) * self.px,
                (self.max_y + 1 - y / CELL_UNITS) * self.px)

    def as_dict(self) -> dict:
        return {"minCellX": self.min_x, "maxCellY": self.max_y, "cols": self.cols,
                "rows": self.rows, "pxPerCell": self.px}


def _downsample(a: np.ndarray, px: int) -> np.ndarray:
    f = SAMPLES // px
    a = a[:SAMPLES, :SAMPLES]
    if f == 1:
        return a
    shape = (px, f, px, f) + a.shape[2:]
    return a.reshape(shape).mean(axis=(1, 3))


def render(world, px: int = 16, margin: int = 2):
    if SAMPLES % px:
        raise ValueError("px must divide 64 (8, 16, 32 or 64)")
    grids = [g for g, l in world.land.items() if l.heights is not None]
    xs = [g[0] for g in grids]
    ys = [g[1] for g in grids]
    frame = MapFrame(min(xs) - margin, max(ys) + margin,
                     max(xs) - min(xs) + 1 + 2 * margin, max(ys) - min(ys) + 1 + 2 * margin, px)

    H = np.full((frame.rows * px, frame.cols * px), OCEAN_FLOOR, dtype=np.float32)
    C = np.full((frame.rows * px, frame.cols * px, 3), 255.0, dtype=np.float32)
    for (gx, gy), land in world.land.items():
        if land.heights is None:
            continue
        r = (frame.max_y - gy) * px
        c = (gx - frame.min_x) * px
        H[r:r + px, c:c + px] = _downsample(land.heights, px)[::-1]   # row 0 of LAND is south
        if land.colors is not None:
            C[r:r + px, c:c + px] = _downsample(land.colors.astype(np.float32), px)[::-1]

    # hillshade, light from the north-west
    spacing = CELL_UNITS / px
    gy_, gx_ = np.gradient(H, spacing)
    slope = np.arctan(1.5 * np.hypot(gx_, gy_))
    aspect = np.arctan2(-gx_, gy_)
    az, alt = np.radians(315), np.radians(45)
    shade = np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(az - aspect)
    shade = np.clip(shade, 0, 1)[..., None]

    # colour ramp by height
    stops = np.array([0, 300, 1500, 4000, 8000, 14000], dtype=np.float32)
    cols = np.array([[196, 182, 140], [150, 150, 100], [128, 122, 86],
                     [112, 96, 78], [150, 140, 130], [235, 235, 235]], dtype=np.float32)
    land_rgb = np.stack([np.interp(H, stops, cols[:, i]) for i in range(3)], axis=-1)
    land_rgb = land_rgb * (0.55 + 0.45 * C / 255.0)          # tint with the land's vertex colours
    land_rgb = land_rgb * (0.45 + 0.75 * shade)

    depth = np.clip(-H / 1500.0, 0, 1)[..., None]
    water_rgb = np.array([110, 150, 170], np.float32) * (1 - depth) + np.array([40, 70, 100], np.float32) * depth

    rgb = np.where((H > 0)[..., None], land_rgb, water_rgb)
    img = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB")
    return img, frame


def draw_locations(img: Image.Image, frame: MapFrame, locations) -> Image.Image:
    out = img.copy()
    d = ImageDraw.Draw(out)
    style = {"entrance": (220, 40, 40), "landmark": (255, 220, 0)}
    for loc in locations:
        if loc.space:  # lives on a quasi-exterior sub-map, not the main map
            continue
        x, y = frame.to_pixel(loc.pos[0], loc.pos[1])
        colour = (120, 120, 255) if loc.town_interior else style.get(loc.kind, (255, 255, 255))
        r = 1.5 if loc.town_interior else 2.5
        d.ellipse([x - r, y - r, x + r, y + r], fill=colour, outline=(0, 0, 0))
    return out
