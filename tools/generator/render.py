"""Draw the world map from LAND records.

Ground colour comes from the land's own textures (the average colour of each
ground texture, blended between texture squares) times the land's vertex
colours, as in game. On top: hillshading for relief, depth-shaded water with
a lighter shore band, and a thin coastline. Without a VFS (no texture access)
it falls back to a colour ramp by height.

64 px per cell is the native resolution of the land data (65 height and colour
vertices per cell edge); lower values are averaged down from it.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from extract import CELL_UNITS

SAMPLES = 64  # use 64 of the 65 vertices; the last row/column repeats the neighbour's edge
TEX_PER_CELL = 16
OCEAN_FLOOR = -4000.0            # cells without LAND: past DEPTH_RANGE, so exactly the deep colour

# look
TEX_KNEE = 95.0                   # soft brightness curve for texture means: lum' = 225 * (1 - exp(-lum / knee))
TEX_SATURATION = 0.72
TEX_BLUR = 0.45                   # blur radius in texture squares, so neighbouring textures merge
SUN_AZIMUTH, SUN_ALTITUDE = 315.0, 45.0
RELIEF = 1.6                      # vertical exaggeration for the hillshade
AMBIENT, DIFFUSE = 0.55, 0.6
SHALLOW = np.array([86, 138, 150], np.float32)
DEEP = np.array([26, 50, 76], np.float32)
DEPTH_RANGE = 1800.0              # game units of depth from shallow to deep colour
SHORE_GLOW = np.array([150, 190, 190], np.float32)
COAST_DARKEN = 0.78
# Vertex colours carry hand-painted blob shadows under trees and rocks: right in
# game, speckle on a map. Use a weak, softened version (roads and towns survive).
VC_STRENGTH = 0.35
VC_BLUR = 1.5 / 64                # blur radius as a fraction of a cell
DEEP_RGB = tuple(int(v) for v in DEEP)


ROAD_COLOR = (176, 172, 164)      # warm grey: clearly a road, not glaring
ROAD_EDGE = (40, 32, 24)
ROAD_EDGE_ALPHA = 0.35
ROAD_WIDTH = {64: 3, 32: 2, 16: 2, 8: 1}   # line width in pixels at each pixels-per-cell level


@dataclass
class MapFrame:
    """Where the image sits in world coordinates."""
    min_x: int        # westmost cell column
    max_y: int        # northmost cell row
    cols: int
    rows: int
    px: int           # pixels per cell
    # road network: list of (n, 2) polylines of x, y in texture squares
    # (16 per cell) from the map's top-left corner; None without texture data
    roads: "object | None" = None

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


def _height_ramp(H: np.ndarray) -> np.ndarray:
    stops = np.array([0, 300, 1500, 4000, 8000, 14000], dtype=np.float32)
    cols = np.array([[196, 182, 140], [150, 150, 100], [128, 122, 86],
                     [112, 96, 78], [150, 140, 130], [235, 235, 235]], dtype=np.float32)
    return np.stack([np.interp(H, stops, cols[:, i]) for i in range(3)], axis=-1)


def _thin(mask: np.ndarray) -> np.ndarray:
    """Zhang-Suen thinning: reduce bands of road squares to 1-square centre lines."""
    img = mask.astype(np.uint8)
    while True:
        changed = False
        for step in (0, 1):
            P = np.pad(img, 1)
            p2, p3, p4 = P[:-2, 1:-1], P[:-2, 2:], P[1:-1, 2:]
            p5, p6, p7 = P[2:, 2:], P[2:, 1:-1], P[2:, :-2]
            p8, p9 = P[1:-1, :-2], P[:-2, :-2]
            ring = [p2, p3, p4, p5, p6, p7, p8, p9, p2]
            B = sum(p.astype(np.int16) for p in ring[:8])
            A = sum(((ring[i] == 0) & (ring[i + 1] == 1)).astype(np.int16) for i in range(8))
            if step == 0:
                c = ((p2 & p4 & p6) == 0) & ((p4 & p6 & p8) == 0)
            else:
                c = ((p2 & p4 & p8) == 0) & ((p2 & p6 & p8) == 0)
            m = (img == 1) & (B >= 2) & (B <= 6) & (A == 1) & c
            if m.any():
                img[m] = 0
                changed = True
        if not changed:
            return img.astype(bool)


def _road_segments(road: np.ndarray) -> np.ndarray:
    """Centre-line segments between neighbouring road squares, (N, 4) of x0, y0, x1, y1
    at square centres. Diagonal steps are skipped where an L-shaped path exists."""
    sk = _thin(road)
    # drop specks: single road squares with no road neighbour
    P = np.pad(sk, 1)
    neighbours = sum(P[1 + dy:P.shape[0] - 1 + dy, 1 + dx:P.shape[1] - 1 + dx].astype(np.int8)
                     for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dy or dx)
    sk &= neighbours > 0
    P = np.pad(sk, 1)

    def at(dy, dx):
        return P[1 + dy:P.shape[0] - 1 + dy, 1 + dx:P.shape[1] - 1 + dx]

    segs = []
    for dy, dx, ok in ((0, 1, None), (1, 0, None),
                       (1, 1, ~at(0, 1) & ~at(1, 0)), (1, -1, ~at(0, -1) & ~at(1, 0))):
        m = sk & at(dy, dx)
        if ok is not None:
            m &= ok
        r, c = np.nonzero(m)
        segs.append(np.stack([c, r, c + dx, r + dy], axis=1))
    return np.concatenate(segs)


ROAD_SMOOTH = 1.6       # Gaussian smoothing of road paths, in texture squares
ROAD_MIN_LENGTH = 4     # drop road fragments (whole connected pieces) shorter than this, in squares


def _road_paths(road: np.ndarray) -> list[np.ndarray]:
    """Road network as smooth polylines (each (n, 2) of x, y in texture squares,
    at square centres). Paths run between ends and junctions, which stay fixed
    so roads still meet; everything between is smoothed out of the grid steps."""
    from collections import defaultdict
    adj: dict[tuple, list] = defaultdict(list)
    for x0, y0, x1, y1 in _road_segments(road).tolist():
        adj[(x0, y0)].append((x1, y1))
        adj[(x1, y1)].append((x0, y0))

    # drop small connected pieces
    seen: set = set()
    for start in list(adj):
        if start in seen:
            continue
        comp, stack = [], [start]
        seen.add(start)
        while stack:
            n = stack.pop()
            comp.append(n)
            for m in adj[n]:
                if m not in seen:
                    seen.add(m)
                    stack.append(m)
        if len(comp) < ROAD_MIN_LENGTH:
            for n in comp:
                del adj[n]

    def key(a, b):
        return (a, b) if a < b else (b, a)

    used: set = set()
    paths = []

    def walk(a, b):
        path = [a, b]
        used.add(key(a, b))
        prev, cur = a, b
        while len(adj[cur]) == 2:
            nxt = adj[cur][0] if adj[cur][0] != prev else adj[cur][1]
            if key(cur, nxt) in used:
                break
            used.add(key(cur, nxt))
            path.append(nxt)
            prev, cur = cur, nxt
        return path

    for n, nbrs in adj.items():                 # paths starting at ends and junctions
        if len(nbrs) != 2:
            for m in nbrs:
                if key(n, m) not in used:
                    paths.append(walk(n, m))
    for n, nbrs in adj.items():                 # leftover closed loops
        for m in nbrs:
            if key(n, m) not in used:
                paths.append(walk(n, m))

    # smooth interior points; ends (junctions / road ends) stay put
    r = int(ROAD_SMOOTH * 3)
    kernel = np.exp(-0.5 * (np.arange(-r, r + 1) / ROAD_SMOOTH) ** 2)
    out = []
    for p in paths:
        a = np.array(p, dtype=np.float32) + 0.5
        if len(a) > 2:
            padded = np.concatenate([np.repeat(a[:1], r, 0), a, np.repeat(a[-1:], r, 0)])
            sm = np.stack([np.convolve(padded[:, i], kernel / kernel.sum(), mode="valid") for i in (0, 1)], 1)
            sm[0], sm[-1] = a[0], a[-1]
            a = sm
        out.append(a)
    return out


def draw_roads(img: Image.Image, frame: MapFrame) -> Image.Image:
    """Draw the road network onto a map image of any pixels-per-cell level:
    a solid light line with a soft dark edge, the same width at every zoom."""
    if not frame.roads:
        return img
    level_px = img.width // frame.cols
    width = ROAD_WIDTH.get(level_px, max(1, round(level_px / 21)))
    k = level_px / TEX_PER_CELL
    line = Image.new("L", img.size, 0)
    edge = Image.new("L", img.size, 0)
    dl, de = ImageDraw.Draw(line), ImageDraw.Draw(edge)
    for p in frame.roads:
        pts = [tuple(v) for v in (p * k).tolist()]
        de.line(pts, fill=255, width=width + 2, joint="curve")
        dl.line(pts, fill=255, width=width, joint="curve")
        if width >= 2:   # round the ends, so paths meeting at a junction join cleanly
            for x, y in (pts[0], pts[-1]):
                de.ellipse((x - width / 2 - 1, y - width / 2 - 1, x + width / 2 + 1, y + width / 2 + 1), fill=255)
                dl.ellipse((x - width / 2, y - width / 2, x + width / 2, y + width / 2), fill=255)
    line = line.filter(ImageFilter.GaussianBlur(0.5))
    edge = edge.filter(ImageFilter.GaussianBlur(0.8)).point(lambda v: int(v * ROAD_EDGE_ALPHA))
    img = Image.composite(Image.new("RGB", img.size, ROAD_EDGE), img, edge)
    return Image.composite(Image.new("RGB", img.size, ROAD_COLOR), img, line)


def _ground_image(world, frame: MapFrame, lookup: dict, palette: np.ndarray,
                  is_road: np.ndarray) -> np.ndarray:
    """Texture colour at full map resolution (uint8 RGB); black where a cell has no
    texture data. Also sets frame.roads from the road texture squares."""
    T = TEX_PER_CELL
    grid = np.zeros((frame.rows * T, frame.cols * T, 3), np.float32)
    has = np.zeros((frame.rows * T, frame.cols * T), np.float32)
    road = np.zeros((frame.rows * T, frame.cols * T), bool)
    lum = palette.mean(axis=1, keepdims=True) + 1e-3
    new_lum = 225.0 * (1 - np.exp(-lum / TEX_KNEE))
    pal = palette * (new_lum / lum)
    pal = new_lum + (pal - new_lum) * TEX_SATURATION
    pal = np.clip(pal, 0, 255)
    for (gx, gy), land in world.land.items():
        if land.textures is None or land.heights is None:
            continue
        r = (frame.max_y - gy) * T
        c = (gx - frame.min_x) * T
        idx = np.vectorize(lambda v: lookup.get((land.tex_plugin, int(v)), 0))(land.textures)
        grid[r:r + T, c:c + T] = pal[idx][::-1]       # row 0 of LAND is south
        has[r:r + T, c:c + T] = 1
        road[r:r + T, c:c + T] = is_road[idx][::-1]
    frame.roads = _road_paths(road)
    # smooth blend between texture squares, like the game's texture blending
    size = (frame.cols * frame.px, frame.rows * frame.px)
    img = Image.fromarray(np.clip(grid, 0, 255).astype(np.uint8), "RGB").resize(size, Image.BILINEAR)
    radius = TEX_BLUR * frame.px / T
    if radius >= 0.5:
        img = img.filter(ImageFilter.GaussianBlur(radius=radius))
    mask = Image.fromarray((has * 255).astype(np.uint8), "L").resize(size, Image.NEAREST)
    out = np.asarray(img).copy()
    out[np.asarray(mask) == 0] = 0
    return out


def render(world, px: int = 16, margin: int = 2, vfs=None, log=print):
    """The map at px pixels per cell, without roads; frame.roads holds the road
    network, drawn per zoom level with draw_roads()."""
    if SAMPLES % px:
        raise ValueError("px must divide 64 (8, 16, 32 or 64)")
    grids = [g for g, l in world.land.items() if l.heights is not None]
    xs = [g[0] for g in grids]
    ys = [g[1] for g in grids]
    frame = MapFrame(min(xs) - margin, max(ys) + margin,
                     max(xs) - min(xs) + 1 + 2 * margin, max(ys) - min(ys) + 1 + 2 * margin, px)
    Wpx, Hpx = frame.cols * px, frame.rows * px

    H = np.full((Hpx, Wpx), OCEAN_FLOOR, dtype=np.float32)
    V = np.full((Hpx, Wpx, 3), 255, dtype=np.uint8)
    for (gx, gy), land in world.land.items():
        if land.heights is None:
            continue
        r = (frame.max_y - gy) * px
        c = (gx - frame.min_x) * px
        H[r:r + px, c:c + px] = _downsample(land.heights, px)[::-1]
        if land.colors is not None:
            V[r:r + px, c:c + px] = _downsample(land.colors.astype(np.float32), px)[::-1].astype(np.uint8)

    radius = VC_BLUR * px
    if radius >= 0.5:
        V = np.asarray(Image.fromarray(V, "RGB").filter(ImageFilter.GaussianBlur(radius=radius)))

    ground = None
    if vfs is not None:
        import landtex
        lookup, palette, is_road = landtex.texture_colours(world, vfs, log=log)
        ground = _ground_image(world, frame, lookup, palette, is_road)
        log(f"Roads: {len(frame.roads)} paths")

    # water: lighter near the shore (blurred land mask), darker with depth
    land_mask = H > 0
    glow = Image.fromarray((land_mask * 255).astype(np.uint8), "L").filter(
        ImageFilter.GaussianBlur(radius=max(1.0, px * 0.35)))
    glow = np.asarray(glow, dtype=np.float32) / 255.0

    out = np.empty((Hpx, Wpx, 3), np.uint8)
    spacing = CELL_UNITS / px
    az, alt = np.radians(SUN_AZIMUTH), np.radians(SUN_ALTITUDE)
    STRIP = 512
    for y0 in range(0, Hpx, STRIP):
        y1 = min(Hpx, y0 + STRIP)
        a0, a1 = max(0, y0 - 1), min(Hpx, y1 + 1)          # one row of context for gradients
        h = H[a0:a1]
        gy_, gx_ = np.gradient(h * RELIEF, spacing)
        slope = np.arctan(np.hypot(gx_, gy_))
        aspect = np.arctan2(-gx_, gy_)
        shade = np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(az - aspect)
        sl = slice(y0 - a0, y0 - a0 + (y1 - y0))
        shade = np.clip(shade[sl], 0, 1)[..., None]
        h = h[sl]

        base = _height_ramp(h)
        if ground is not None:
            g = ground[y0:y1].astype(np.float32)
            have = g.any(axis=-1, keepdims=True)
            base = np.where(have, g, base)
        vc = 1 - VC_STRENGTH * (1 - V[y0:y1].astype(np.float32) / 255.0)
        land_rgb = base * vc * (AMBIENT + DIFFUSE * shade)

        depth = np.clip(-h / DEPTH_RANGE, 0, 1)[..., None] ** 0.7
        water = SHALLOW * (1 - depth) + DEEP * depth
        gl = glow[y0:y1, :, None] * 0.55
        water = water * (1 - gl) + SHORE_GLOW * gl

        m = land_mask[y0:y1]
        rgb = np.where(m[..., None], land_rgb, water)

        # coastline: land pixels touching water
        mm = land_mask[a0:a1]
        edge = mm.copy()
        edge[1:] &= mm[:-1]
        edge[:-1] &= mm[1:]
        edge[:, 1:] &= mm[:, :-1]
        edge[:, :-1] &= mm[:, 1:]
        coast = (mm & ~edge)[sl]
        rgb[coast] *= COAST_DARKEN

        out[y0:y1] = np.clip(rgb, 0, 255).astype(np.uint8)

    return Image.fromarray(out, "RGB"), frame


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
