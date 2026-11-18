"""Merge a load order into one world and pull out what the mod needs.

Merging follows the engine's rules closely enough for map purposes:
- a cell is identified by its grid (exterior) or lowercase name (interior);
  later files override cell fields and add / replace / delete references
- a reference is identified by (owning content file, ref index); the FRMR
  high byte names the owning master (0 = the file itself)
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import esm

CELL_UNITS = 8192.0


# ---------------------------------------------------------------- content resolution

def read_openmw_cfg(cfg: Path) -> list[Path]:
    """Return the data= directories from an openmw.cfg, in order."""
    dirs = []
    for line in Path(cfg).read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith("data="):
            value = line[5:].strip()
            if value.startswith('"') and value.endswith('"'):
                value = value[1:-1].replace("&&", "&").replace('&"', '"')
            dirs.append(Path(value))
    return dirs


def resolve_content(names: list[str], data_dirs: list[Path]) -> list[Path]:
    """Find each content file; like the engine, later data dirs win."""
    index: dict[str, Path] = {}
    for d in data_dirs:
        try:
            for entry in d.iterdir():
                if entry.is_file():
                    index[entry.name.lower()] = entry
        except OSError:
            continue
    out = []
    for n in names:
        p = index.get(n.lower())
        if p is None:
            raise FileNotFoundError(f"content file not found in any data dir: {n}")
        out.append(p)
    return out


# ---------------------------------------------------------------- world model

@dataclass
class World:
    files: list[str]
    cells: dict[tuple, esm.Cell] = field(default_factory=dict)          # key -> merged cell
    refs: dict[tuple, dict[tuple, esm.CellRef]] = field(default_factory=dict)  # cell key -> refkey -> ref
    land: dict[tuple[int, int], esm.Land] = field(default_factory=dict)
    regions: dict[str, str] = field(default_factory=dict)              # region id -> display name
    # teleports not done by doors, merged by record id (later files win)
    travel: dict[str, list[str]] = field(default_factory=dict)        # NPC id -> travel destination cells ('' = exterior)
    object_script: dict[str, str] = field(default_factory=dict)       # object id -> script id
    script_targets: dict[str, set[str]] = field(default_factory=dict)  # script id -> PositionCell target cells
    # info id -> (speaker id, PositionCell targets, scripts started)
    info_targets: dict[str, tuple[str, set[str], set[str]]] = field(default_factory=dict)
    ltex: dict[int, dict[int, str]] = field(default_factory=dict)      # plugin index -> LTEX index -> texture


# Developer, test and holding cells: never markers, door targets or sub-maps.
# "Test of ..." is a real naming pattern (Nchuleftingth, Test of Pattern).
DEV_CELL = re.compile(
    r"^[A-Za-z0-9]+_"                      # T_Test_TR, TR_HOLD_..., PC_HOLD_..., Sky_ScriptHolder
    r"|\btest(ing)?\b(?! of)|toddtest"     # ToddTest, Draugr Test, Mark's Script Testing Cell
    r"|holdingcell|wonderland|^clutter warehouse|^redoran interior\d*$|^sotha sil,$",
    re.I)


def is_dev_cell(name: str) -> bool:
    return bool(DEV_CELL.search(name or ""))


# Player->PositionCell x y z rot "cell" (commas optional). Only the player
# form counts: "SomeNPC"->PositionCell just moves that NPC around.
_POSITION_CELL = re.compile(
    r'player\s*->\s*positioncell\s*,?\s*-?[\d.]+\s*,?\s*-?[\d.]+\s*,?\s*-?[\d.]+\s*,?\s*-?[\d.]+\s*,?\s*"([^"]+)"', re.I)
_SCRIPTED_OBJECTS = {"ACTI", "DOOR", "NPC_", "CREA", "CONT", "MISC", "BOOK", "ALCH",
                     "WEAP", "ARMO", "CLOT", "LIGH", "INGR", "APPA", "LOCK", "PROB", "REPA"}


_START_SCRIPT = re.compile(r'startscript\s*,?\s*"?([\w ]+?)"?\s*$', re.I | re.M)


def _targets(text: bytes) -> set[str]:
    return {m.strip().lower() for m in _POSITION_CELL.findall(text.decode(esm.ENCODING, "replace"))}


def _started(text: bytes) -> set[str]:
    return {m.strip().lower() for m in _START_SCRIPT.findall(text.decode(esm.ENCODING, "replace"))}


def cell_key(cell: esm.Cell) -> tuple:
    if cell.interior:
        return ("int", cell.name.lower())
    return ("ext", cell.grid[0], cell.grid[1])


def load_world(paths: list[Path], with_land: bool = True, log=print) -> World:
    world = World([p.name for p in paths])
    lower_names = [p.name.lower() for p in paths]
    wanted = {"CELL", "REGN", "SCPT", "INFO"} | _SCRIPTED_OBJECTS | ({"LAND", "LTEX"} if with_land else set())
    for file_idx, path in enumerate(paths):
        masters = [m.lower() for m in esm.read_masters(path)]
        master_idx = [lower_names.index(m) if m in lower_names else -1 for m in masters]
        n_cells = n_land = 0
        for rec in esm.iter_records(path, wanted):
            if rec.type == "CELL":
                n_cells += 1
                _merge_cell(world, esm.parse_cell(rec), file_idx, master_idx)
            elif rec.type == "LAND":
                land = esm.parse_land(rec)
                if land is not None:
                    n_land += 1
                    if land.textures is not None:
                        land.tex_plugin = file_idx
                    old = world.land.get(land.grid)
                    if old is not None:  # a plugin may override only some LAND subrecords
                        land.heights = land.heights if land.heights is not None else old.heights
                        land.colors = land.colors if land.colors is not None else old.colors
                        if land.textures is None:
                            land.textures, land.tex_plugin = old.textures, old.tex_plugin
                    world.land[land.grid] = land
            elif rec.type == "LTEX":
                lt = esm.parse_ltex(rec)
                if lt is not None:
                    world.ltex.setdefault(file_idx, {})[lt[0]] = lt[1]
            elif rec.type == "REGN":
                rid = esm.cstr(rec.first("NAME") or b"").lower()
                fnam = rec.first("FNAM")
                if rid:
                    world.regions[rid] = esm.cstr(fnam) if fnam else rid
            elif rec.type == "SCPT":
                hd, tx = rec.first("SCHD"), rec.first("SCTX")
                if hd:
                    world.script_targets[esm.cstr(hd[:32]).lower()] = _targets(tx) if tx else set()
            elif rec.type == "INFO":
                iid = rec.first("INAM")
                if iid:
                    b, o = rec.first("BNAM"), rec.first("ONAM")
                    t = _targets(b) if b else set()
                    s = _started(b) if b else set()
                    if t or s:
                        world.info_targets[esm.cstr(iid)] = (esm.cstr(o).lower() if o else "", t, s)
                    else:
                        world.info_targets.pop(esm.cstr(iid), None)
            else:  # an object type that may carry a script or travel destinations
                n = rec.first("NAME")
                if not n:
                    continue
                oid = esm.cstr(n).lower()
                s = rec.first("SCRI")
                if s:
                    world.object_script[oid] = esm.cstr(s).lower()
                else:
                    world.object_script.pop(oid, None)
                if rec.type == "NPC_" or rec.type == "CREA":
                    dests, pending = [], False
                    for sn, sd in rec.subs:
                        if sn == "DODT":
                            if pending:
                                dests.append("")       # exterior destination
                            pending = True
                        elif sn == "DNAM" and pending:
                            dests.append(esm.cstr(sd).lower())
                            pending = False
                    if pending:
                        dests.append("")
                    if dests:
                        world.travel[oid] = dests
                    else:
                        world.travel.pop(oid, None)
        log(f"  {path.name}: {n_cells} cells, {n_land} land")
    return world


def _merge_cell(world: World, cell: esm.Cell, file_idx: int, master_idx: list[int]):
    if cell.interior:
        cell.grid = (0, 0)  # DATA grid fields are meaningless for interiors
    key = cell_key(cell)
    if cell.deleted:
        world.cells.pop(key, None)
        world.refs.pop(key, None)
        return
    base = world.cells.get(key)
    if base is None:
        world.cells[key] = cell
    else:
        # later file overrides the cell's own fields
        base.flags = cell.flags
        if cell.name:
            base.name = cell.name
        if cell.region:
            base.region = cell.region
        if cell.water_height is not None:
            base.water_height = cell.water_height
    refs = world.refs.setdefault(key, {})
    for ref in cell.refs:
        hi, lo = ref.frmr >> 24, ref.frmr & 0xFFFFFF
        owner = file_idx if hi == 0 else (master_idx[hi - 1] if hi - 1 < len(master_idx) else -1)
        rk = (owner, lo)
        if ref.deleted:
            refs.pop(rk, None)
        else:
            refs[rk] = ref
    cell.refs = []  # merged refs live in world.refs


# ---------------------------------------------------------------- locations

def grid_of(pos) -> tuple[int, int]:
    return (math.floor(pos[0] / CELL_UNITS), math.floor(pos[1] / CELL_UNITS))


def prefix(name: str) -> str:
    return name.split(",")[0].strip()


@dataclass
class Location:
    id: str
    name: str
    kind: str                     # "entrance" | "landmark" | "quasi-exterior"
    pos: tuple[float, float, float]
    grid: tuple[int, int]
    region: str | None
    cells: list[str] = field(default_factory=list)   # interior cells belonging to it
    doors: int = 0
    town_interior: bool = False   # a house/shop inside a named town cell
    space: str | None = None      # None = main exterior map; else the quasi-exterior cell it's in


def extract(world: World) -> dict:
    """Build the location list, door graph and NorthMarker table."""
    interiors = {k[1]: c for k, c in world.cells.items() if k[0] == "int" and not is_dev_cell(c.name)}
    dev_cells = sorted(c.name for k, c in world.cells.items() if k[0] == "int" and is_dev_cell(c.name))
    quasi_keys = {k for k, c in interiors.items() if c.flags & esm.CELL_BEHAVE_EXTERIOR}

    # exterior doors -> interiors, and interior -> interior links.
    # Quasi-exterior cells (Mournhold) act as small exterior maps of their own.
    ext_doors: list[tuple[esm.CellRef, esm.Cell]] = []
    links: dict[str, set[str]] = defaultdict(set)
    exits_to_ext: dict[str, list] = defaultdict(list)   # interior -> exterior door targets
    interior_doors: dict[str, list] = defaultdict(list)  # interior -> [(door pos, target interior or None, dest pos)]
    north: dict[str, float] = {}

    for key, cell in world.cells.items():
        if key[0] == "int" and key[1] not in interiors:
            continue  # dev / test cell
        for ref in world.refs.get(key, {}).values():
            if key[0] == "int" and ref.id == "northmarker":
                north[cell.name] = ref.rot[2]
            if ref.dest_pos is None:
                continue
            is_quasi = key[0] == "int" and key[1] in quasi_keys
            target_quasi = bool(ref.dest_cell) and ref.dest_cell.lower() in quasi_keys
            if (key[0] == "ext" or is_quasi) and not target_quasi:
                if ref.dest_cell and ref.dest_cell.lower() in interiors:
                    ext_doors.append((ref, cell))
            else:
                tgt = ref.dest_cell.lower() if ref.dest_cell else None
                if tgt is None or tgt in interiors:
                    interior_doors[key[1]].append((ref.pos, tgt, ref.dest_pos))
                if ref.dest_cell:
                    t = ref.dest_cell.lower()
                    # quasi-exteriors are map roots, not part of any dungeon
                    if t in interiors and t != key[1] and not is_quasi and not target_quasi:
                        links[key[1]].add(t)
                        links[t].add(key[1])
                else:
                    exits_to_ext[key[1]].append([round(v) for v in ref.dest_pos[:3]])

    named_ext = {(c.grid): c.name for k, c in world.cells.items()
                 if k[0] == "ext" and c.name and not is_dev_cell(c.name)}

    # group exterior doors by target cell; split groups whose doors are far apart
    by_target: dict[str, list] = defaultdict(list)
    for ref, cell in ext_doors:
        by_target[ref.dest_cell.lower()].append((ref, cell))

    # A named exterior area is a town if many separate entrances share its name
    # prefix (Balmora, Vivec). A lone ruin whose exterior cell carries its own
    # name (Ald Daedroth) is not.
    entrances_per_prefix: dict[str, int] = defaultdict(int)
    for target, doors in by_target.items():
        town_name = named_ext.get(doors[0][1].grid)
        if town_name and prefix(interiors[target].name).lower() == prefix(town_name).lower():
            entrances_per_prefix[prefix(town_name).lower()] += 1
    towns = {p for p, n in entrances_per_prefix.items() if n >= 5}

    locations: list[Location] = []
    entrance_of: dict[str, str] = {}
    for target, doors in sorted(by_target.items()):
        clusters: list[list] = []
        for ref, cell in doors:
            for cl in clusters:
                r0 = cl[0][0]
                if math.dist(ref.pos[:2], r0.pos[:2]) < 2 * CELL_UNITS:
                    cl.append((ref, cell))
                    break
            else:
                clusters.append([(ref, cell)])
        for i, cl in enumerate(clusters):
            r0, c0 = cl[0]
            name = interiors[target].name
            pos = tuple(sum(r.pos[j] for r, _ in cl) / len(cl) for j in range(3))
            space = c0.name if c0.interior else None
            g = grid_of(pos) if space is None else (0, 0)
            if space is None:
                town = named_ext.get(g) or named_ext.get(c0.grid)
                town_p = prefix(town).lower() if town else None
                in_town = bool(town_p in towns and "," in name and prefix(name).lower() == town_p)
            else:
                in_town = prefix(name).lower() == prefix(space).lower() and "," in name
            loc = Location(
                id=target + (f"#{i}" if i else ""),
                name=name,
                kind="entrance",
                pos=tuple(round(v) for v in pos),
                grid=g,
                region=world.regions.get(c0.region or "", c0.region),
                cells=[name],
                doors=len(cl),
                town_interior=in_town,
                space=space,
            )
            locations.append(loc)
            entrance_of.setdefault(target, loc.id)

    # interiors reached only from other interiors: attach to the nearest entrance (BFS)
    loc_by_id = {l.id: l for l in locations}
    owner: dict[str, str] = dict(entrance_of)
    frontier = list(entrance_of)
    while frontier:
        nxt = []
        for cell in frontier:
            for other in links.get(cell, ()):
                if other not in owner:
                    owner[other] = owner[cell]
                    loc_by_id[owner[cell]].cells.append(interiors[other].name)
                    nxt.append(other)
        frontier = nxt

    # named exterior cells -> landmarks (adjacent cells with the same name merge)
    by_name: dict[str, list] = defaultdict(list)
    for k, c in world.cells.items():
        if k[0] == "ext" and c.name and not is_dev_cell(c.name):
            by_name[c.name].append(c)
    for name, cells in sorted(by_name.items()):
        groups: list[list] = []
        for c in cells:
            for g in groups:
                if any(abs(c.grid[0] - o.grid[0]) <= 1 and abs(c.grid[1] - o.grid[1]) <= 1 for o in g):
                    g.append(c)
                    break
            else:
                groups.append([c])
        for i, g in enumerate(groups):
            cx = sum(c.grid[0] for c in g) / len(g)
            cy = sum(c.grid[1] for c in g) / len(g)
            pos = ((cx + 0.5) * CELL_UNITS, (cy + 0.5) * CELL_UNITS, 0.0)
            locations.append(Location(
                id="ext:" + name.lower() + (f"#{i}" if i else ""),
                name=name, kind="landmark",
                pos=tuple(round(v) for v in pos), grid=grid_of(pos),
                region=world.regions.get(g[0].region or "", g[0].region),
            ))

    # quasi-exterior interiors (Mournhold etc.)
    quasi = sorted(c.name for c in interiors.values() if c.flags & esm.CELL_BEHAVE_EXTERIOR)

    teleport_locs, unowned = _teleport_locations(world, interiors, quasi_keys, links, exits_to_ext,
                                                 owner, loc_by_id)
    locations += teleport_locs

    # Way out of every interior, for the compass:
    #   exits[cell] = doors in that cell leading outdoors: (door x, y, exterior x, y)
    #   route[cell] = for cells with no outdoor door, the door one step closer to one
    exits: dict[str, list] = {}
    for c, doors in interior_doors.items():
        if c in quasi_keys:
            continue
        outs = [(round(p[0]), round(p[1]), round(d[0]), round(d[1])) for p, t, d in doors if t is None]
        if outs:
            exits[c] = outs
    route: dict[str, tuple] = {}
    dist = {c: 0 for c in exits}
    frontier = list(exits)
    # reverse index: which cells have a door into a given cell
    into: dict[str, list] = defaultdict(list)
    for c, doors in interior_doors.items():
        if c in quasi_keys:
            continue
        for p, t, d in doors:
            if t is not None and t != c and t not in quasi_keys:
                into[t].append((c, p))
    while frontier:
        nxt = []
        for b in frontier:
            for a, p in into.get(b, ()):
                if a not in dist:
                    dist[a] = dist[b] + 1
                    route[a] = (round(p[0]), round(p[1]))
                    nxt.append(a)
        frontier = nxt

    return {
        "exits": exits,
        "route": route,
        "locations": locations,
        "north_markers": north,
        "quasi_exteriors": quasi,
        "exits_to_exterior": {interiors[k].name: v for k, v in exits_to_ext.items()},
        "unreachable_interiors": unowned,
        "dev_cells": dev_cells,
        "teleport_locations": teleport_locs,
    }


def _cluster(points: list, radius: float = 2 * CELL_UNITS) -> list[list]:
    groups: list[list] = []
    for p in points:
        for g in groups:
            if math.dist(p[:2], g[0][:2]) < radius:
                g.append(p)
                break
        else:
            groups.append([p])
    return groups


def _teleport_locations(world, interiors, quasi_keys, links, exits_to_ext, owner, loc_by_id):
    """Markers for places no exterior door leads to.

    Each group of linked unreachable interiors (or a whole quasi-exterior town
    like Mournhold) is placed, in order of preference:
      1. where its doors let you out into the world, if any do
      2. where the NPC or object that teleports you in stands: travel-service
         destinations, PositionCell in an object's script, PositionCell in a
         dialogue result (an NPC indoors counts as its building's entrance)
    Groups with neither stay unplaced and are listed in the report.
    Returns (locations, names of interiors still unplaced).
    """
    # target cell -> ids of the NPCs / objects that send the player there
    sources: dict[str, set[str]] = defaultdict(set)
    for npc, dests in world.travel.items():
        for d in dests:
            if d:
                sources[d].add(npc)
    for oid, sid in world.object_script.items():
        for t in world.script_targets.get(sid, ()):
            sources[t].add(oid)
    for speaker, targets, started in world.info_targets.values():
        if speaker:
            for t in targets.union(*(world.script_targets.get(s, set()) for s in started)):
                sources[t].add(speaker)

    # where each source stands, as a main-map position
    wanted = set().union(*sources.values()) if sources else set()
    stands: dict[str, list] = defaultdict(list)
    for key, refs in world.refs.items():
        for ref in refs.values():
            if ref.id not in wanted:
                continue
            if key[0] == "ext":
                stands[ref.id].append(ref.pos)
            elif key[1] in owner and key[1] in interiors:
                ent = loc_by_id[owner[key[1]]]
                if ent.space is None:
                    # nudged north so it doesn't sit exactly on the building's own dot
                    stands[ref.id].append((ent.pos[0], ent.pos[1] + 512, ent.pos[2]))

    # groups of unreachable cells: linked interiors, or quasi-exteriors by town name
    unowned = [c for c in interiors if c not in owner]
    group_of: dict[str, str] = {}
    groups: dict[str, list[str]] = {}
    for c in unowned:
        if c in group_of:
            continue
        if c in quasi_keys:
            gid = "quasi:" + prefix(interiors[c].name).lower()
            groups.setdefault(gid, []).append(c)
            group_of[c] = gid
            continue
        members, frontier = [c], [c]
        group_of[c] = c
        while frontier:
            nxt = []
            for a in frontier:
                for b in links.get(a, ()):
                    if b not in group_of and b not in owner and b not in quasi_keys:
                        group_of[b] = c
                        members.append(b)
                        nxt.append(b)
            frontier = nxt
        groups[c] = members

    # an unused interior named like a town (the old "Anvil" cell) would only duplicate its marker
    ext_names = {n for k, c in world.cells.items() if k[0] == "ext" and c.name
                 for n in (c.name.lower(), prefix(c.name).lower())}

    # a teleport into any building of a quasi-exterior town (Mournhold's palace)
    # counts as getting into that town
    town_cells: dict[str, list[str]] = defaultdict(list)
    for c, lid in owner.items():
        sp = loc_by_id[lid].space
        if sp:
            town_cells["quasi:" + prefix(sp).lower()].append(c)

    locs: list[Location] = []
    unplaced: list[str] = []
    for gid, members in sorted(groups.items()):
        exit_pts = [tuple(p) for m in members for p in exits_to_ext.get(m, ())]
        tp_cells = [m for m in members + town_cells.get(gid, [])
                    if any(stands.get(s) for s in sources.get(m, ()))]
        tp_pts = [tuple(p) for m in tp_cells for s in sources[m] for p in stands.get(s, ())]
        pts = exit_pts or tp_pts
        if not pts:
            unplaced += [interiors[m].name for m in members]
            continue
        if gid.startswith("quasi:"):
            name, kind = prefix(interiors[members[0]].name), "landmark"
        else:
            front = [m for m in members if exits_to_ext.get(m)] if exit_pts else tp_cells
            name, kind = min((interiors[m].name for m in front), key=lambda n: (len(n), n)), "entrance"
        if name.lower() in ext_names or name.split(":")[0].strip().lower() in ext_names:
            unplaced += [interiors[m].name for m in members]
            continue
        for i, cl in enumerate(_cluster(pts)):
            pos = tuple(round(sum(p[j] for p in cl) / len(cl)) for j in range(2)) + (0,)
            g = grid_of(pos)
            c0 = world.cells.get(("ext", g[0], g[1]))
            locs.append(Location(
                id="tp:" + gid + (f"#{i}" if i else ""),
                name=name, kind=kind, pos=pos, grid=g,
                region=world.regions.get((c0.region if c0 else "") or "", c0.region if c0 else None),
                cells=[interiors[m].name for m in members],
            ))
    return locs, sorted(unplaced)
