"""Build one release profile's data pack.

    python build.py vanilla [--px 16] [--cfg path/to/openmw.cfg]
    python build.py tr-pc-shotn --install [--mod-dir some/folder]

Content files are looked up in the data= directories of an openmw.cfg. The
default cfg path is read from paths.local.json ({"openmw_cfg": "..."}), which
is machine-specific and not committed.

Output goes to <repo>/output/<profile>/:
    map.png            the world map
    map_debug.png      the map with every detected location dotted on it
    locations.json     locations, NorthMarkers and supporting data
    report.txt         counts and lists for review

With --install the tiles and Lua data are also written into a mod folder
(<repo>/mod by default): textures/NGLA/map/ and scripts/NGLA/generated/.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

import extract
import render
import vfs

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent


def build(profile: str, paths: list[Path], cfg: Path, px: int = 64,
          report_dir: Path | None = None, mod_dir: Path | None = None, log=print) -> dict:
    """Read the content files, draw the map and write the outputs.

    report_dir: map.png, map_debug.png, locations.json, report.txt (optional)
    mod_dir:    tile pyramid + generated Lua data, the way the mod reads them (optional)
    """
    t0 = time.time()
    data_dirs = extract.read_openmw_cfg(cfg)
    log("Loading:")
    world = extract.load_world(paths, log=log)
    log(f"Merged: {len(world.cells)} cells, {len(world.land)} land records ({time.time() - t0:.1f}s)")

    data = extract.extract(world)
    locs = data["locations"]

    files = vfs.VFS(data_dirs, vfs.read_archives(cfg))
    img, frame = render.render(world, px=px, vfs=files, log=log)

    ent = [l for l in locs if l.kind == "entrance"]
    report = [
        f"profile: {profile}",
        f"content: {', '.join(p.name for p in paths)}",
        f"map: {img.width}x{img.height}px, {frame.cols}x{frame.rows} cells at {px}px/cell",
        f"entrances: {len(ent)} ({sum(l.town_interior for l in ent)} town interiors, "
        f"{sum(not l.town_interior for l in ent)} others)",
        f"landmarks (named exterior cells): {sum(l.kind == 'landmark' for l in locs)}",
        f"interior cells grouped under entrances: {sum(len(l.cells) for l in ent)}",
        f"teleport-only places placed: {len(data['teleport_locations'])}",
        f"dev/test cells filtered: {len(data['dev_cells'])}",
        f"interiors still unplaced: {len(data['unreachable_interiors'])}",
        f"NorthMarkers: {len(data['north_markers'])}",
        f"quasi-exteriors: {', '.join(data['quasi_exteriors'])}",
        "",
        "== teleport-only places (name @ cell grid <- cells in the group) ==",
        *(f"{l.name} @ {l.grid} <- {', '.join(l.cells[:4])}{' ...' if len(l.cells) > 4 else ''}"
          for l in data["teleport_locations"]),
        "",
        "== still unplaced (no door out, nothing found that teleports in) ==",
        *data["unreachable_interiors"],
        "",
        "== dev / test cells filtered ==",
        *data["dev_cells"],
    ]
    log("\n".join(report[2:11]))

    if report_dir is not None:
        report_dir.mkdir(parents=True, exist_ok=True)
        with_roads = render.draw_roads(img, frame)   # img itself stays road-free for the tile pyramid
        with_roads.save(report_dir / "map.png")
        render.draw_locations(with_roads, frame, locs).save(report_dir / "map_debug.png")
        payload = {
            "profile": profile,
            "content": [p.name for p in paths],
            "frame": frame.as_dict(),
            "locations": [asdict(l) for l in locs],
            "northMarkers": data["north_markers"],
            "quasiExteriors": data["quasi_exteriors"],
            "exitsToExterior": data["exits_to_exterior"],
        }
        (report_dir / "locations.json").write_text(json.dumps(payload, indent=1, ensure_ascii=False),
                                                   encoding="utf-8")
        (report_dir / "report.txt").write_text("\n".join(report), encoding="utf-8")

    result = {"locations": len(locs), "roads": len(frame.roads or [])}
    if mod_dir is not None:
        import export
        r = export.export(mod_dir, img, frame, locs, profile, [p.name for p in paths])
        log(f"Wrote {r['tiles']} map tiles (empty ocean skipped); per level: "
            + ", ".join(f"{lp}px/cell {n}" for lp, n in r["levels"]))
        n = export.export_interiors(mod_dir, data["north_markers"], data["exits"], data["route"])
        log(f"Interior compass data: {n['exits']} cells with outdoor doors, {n['route']} with a route out")
        result["tiles"] = r["tiles"]
    log(f"Done in {time.time() - t0:.1f}s")
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("profile")
    ap.add_argument("--px", type=int, default=16, help="pixels per cell (8, 16, 32, 64)")
    ap.add_argument("--cfg", help="openmw.cfg whose data= dirs hold the content files")
    ap.add_argument("--install", action="store_true",
                    help="also write tiles + Lua data into a mod folder (uses 64px/cell unless --px given)")
    ap.add_argument("--mod-dir", help="mod folder for --install (default: <repo>/mod)")
    args = ap.parse_args()
    if args.install and "--px" not in sys.argv:
        args.px = 64

    profiles = json.loads((HERE / "builds.json").read_text())
    cfg = Path(args.cfg or json.loads((HERE / "paths.local.json").read_text())["openmw_cfg"])
    paths = extract.resolve_content(profiles[args.profile], extract.read_openmw_cfg(cfg))
    mod_dir = (Path(args.mod_dir) if args.mod_dir else REPO / "mod") if args.install else None
    build(args.profile, paths, cfg, px=args.px, report_dir=REPO / "output" / args.profile, mod_dir=mod_dir)


if __name__ == "__main__":
    main()
