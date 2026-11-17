"""Build one release profile's data pack.

    python build.py vanilla [--px 16] [--cfg path/to/openmw.cfg]

Content files are looked up in the data= directories of an openmw.cfg. The
default cfg path is read from paths.local.json ({"openmw_cfg": "..."}), which
is machine-specific and not committed.

Output goes to <repo>/output/<profile>/:
    map.png            the world map
    map_debug.png      the map with every detected location dotted on it
    locations.json     locations, NorthMarkers and supporting data
    report.txt         counts and lists for review
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path

import extract
import render

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("profile")
    ap.add_argument("--px", type=int, default=16, help="pixels per cell (8, 16, 32, 64)")
    ap.add_argument("--cfg", help="openmw.cfg whose data= dirs hold the content files")
    ap.add_argument("--install", action="store_true",
                    help="also write tiles + Lua data into mod/ (uses 32px/cell unless --px given)")
    args = ap.parse_args()
    if args.install and "--px" not in __import__("sys").argv:
        args.px = 32

    profiles = json.loads((HERE / "builds.json").read_text())
    content = profiles[args.profile]
    cfg = args.cfg or json.loads((HERE / "paths.local.json").read_text())["openmw_cfg"]

    t0 = time.time()
    paths = extract.resolve_content(content, extract.read_openmw_cfg(Path(cfg)))
    print("Loading:")
    world = extract.load_world(paths)
    print(f"Merged: {len(world.cells)} cells, {len(world.land)} land records ({time.time() - t0:.1f}s)")

    data = extract.extract(world)
    locs = data["locations"]

    out = REPO / "output" / args.profile
    out.mkdir(parents=True, exist_ok=True)

    img, frame = render.render(world, px=args.px)
    img.save(out / "map.png")
    render.draw_locations(img, frame, locs).save(out / "map_debug.png")

    payload = {
        "profile": args.profile,
        "content": [p.name for p in paths],
        "frame": frame.as_dict(),
        "locations": [asdict(l) for l in locs],
        "northMarkers": data["north_markers"],
        "quasiExteriors": data["quasi_exteriors"],
        "exitsToExterior": data["exits_to_exterior"],
    }
    (out / "locations.json").write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")

    ent = [l for l in locs if l.kind == "entrance"]
    report = [
        f"profile: {args.profile}",
        f"content: {', '.join(p.name for p in paths)}",
        f"map: {img.width}x{img.height}px, {frame.cols}x{frame.rows} cells at {args.px}px/cell",
        f"entrances: {len(ent)} ({sum(l.town_interior for l in ent)} town interiors, "
        f"{sum(not l.town_interior for l in ent)} others)",
        f"landmarks (named exterior cells): {sum(l.kind == 'landmark' for l in locs)}",
        f"interior cells grouped under entrances: {sum(len(l.cells) for l in ent)}",
        f"interiors not reachable from any exterior door: {len(data['unreachable_interiors'])}",
        f"NorthMarkers: {len(data['north_markers'])}",
        f"quasi-exteriors: {', '.join(data['quasi_exteriors'])}",
        "",
        "== unreachable interiors (script teleports, test cells, unused) ==",
        *data["unreachable_interiors"],
    ]
    (out / "report.txt").write_text("\n".join(report), encoding="utf-8")
    print("\n".join(report[:9]))
    if args.install:
        import export
        r = export.export(REPO / "mod", img, frame, locs, args.profile, [p.name for p in paths])
        print(f"Installed into mod/: {r['tiles']} of {r['of']} tiles (empty ocean skipped)")
        n = export.export_interiors(REPO / "mod", data["north_markers"], data["exits"], data["route"])
        print(f"Interior compass data: {n['exits']} cells with outdoor doors, {n['route']} with a route out")
    print(f"Done in {time.time() - t0:.1f}s -> {out}")


if __name__ == "__main__":
    main()
