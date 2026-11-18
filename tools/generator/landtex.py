"""Average colour of every land texture the world uses.

The map paints each 16x16 texture square of a LAND record with the mean
colour of its ground texture (grass, ash, rock, snow...), so the map looks
like the ground you walk on. Only colour statistics end up in the map; no
texture is redistributed.
"""
from __future__ import annotations

import io

import numpy as np
from PIL import Image

DEFAULT_TEXTURE = "_land_default.dds"
FALLBACK_RGB = (120, 110, 90)


def _mean_rgb(data: bytes) -> tuple[float, float, float] | None:
    try:
        im = Image.open(io.BytesIO(data))
        im.draft("RGB", (64, 64))          # cheap for formats that support it
        im = im.convert("RGB")
        if max(im.size) > 128:
            im = im.resize((64, 64), Image.BOX)
        a = np.asarray(im, dtype=np.float32).reshape(-1, 3)
        return tuple(a.mean(axis=0))
    except Exception:
        return None


import re

# Ground textures that are roads, paths or paved streets (by file name), across
# vanilla, TR, PC and SHotN: tx_wg_dirtroad_01, tr_rr_road_01, pc_tx_gc_roadd,
# tx_skyrim_beatenpath_01, tx_mh_cobblestone_01, pc_ex_anv_cobbles...
ROAD_TEXTURE = re.compile(r"road|beatenpath|cobble", re.I)


def texture_colours(world, vfs, log=print) -> tuple[dict, np.ndarray, np.ndarray]:
    """Return ({(plugin, vtex value): palette index}, palette (N, 3) float32,
    is_road (N,) bool).

    vtex value 0 is the default texture; n > 0 is LTEX index n-1 of `plugin`.
    """
    used: set[tuple[int, int]] = set()
    for land in world.land.values():
        if land.textures is not None:
            for v in np.unique(land.textures):
                used.add((land.tex_plugin, int(v)))

    cache: dict[str, tuple] = {}
    failed: set[str] = set()

    def colour_of(name: str):
        key = name.lower()
        if key not in cache:
            data = vfs.read_texture(name)
            rgb = _mean_rgb(data) if data is not None else None
            if rgb is None:
                failed.add(name)
                rgb = FALLBACK_RGB
            cache[key] = rgb
        return cache[key]

    lookup: dict[tuple[int, int], int] = {}
    palette: list = [colour_of(DEFAULT_TEXTURE)]
    road: list[bool] = [False]
    for plugin, v in sorted(used):
        if v == 0:
            lookup[(plugin, v)] = 0
            continue
        name = world.ltex.get(plugin, {}).get(v - 1)
        if name is None:
            lookup[(plugin, v)] = 0
            continue
        lookup[(plugin, v)] = len(palette)
        palette.append(colour_of(name))
        road.append(bool(ROAD_TEXTURE.search(name)))
    log(f"Land textures: {len(cache)} decoded, {len(failed)} missing or unreadable, "
        f"{sum(road)} road texture slots")
    if failed:
        log("  e.g. " + ", ".join(sorted(failed)[:8]))
    return lookup, np.array(palette, dtype=np.float32), np.array(road, dtype=bool)
