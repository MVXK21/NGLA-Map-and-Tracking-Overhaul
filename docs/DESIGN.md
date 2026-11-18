# NGLA Map and Tracking Overhaul — Design

"NGLA" = **Never Get Lost Again**. Internal ID `NGLA` (script and texture folders, the `I.NGLA` interface, settings
keys); the launcher entry is `NGLA Map and Tracking Overhaul.omwscripts`. The GitHub repo is still named
OpenMW-Map-Markers.

Working name. A Skyrim-style map, marker and compass system for OpenMW 0.51+, without automatic quest markers:
the player finds a place on the map, clicks it, and it shows up as a mark on the map and on the compass.

## Goals

1. **A custom world map** covering the whole exterior grid. Vvardenfell, Tamriel Rebuilt, Project Cyrodiil and
   Skyrim: Home of the Nords all share one grid, so one map covers them all. "Behave like exterior" cells
   (Mournhold, Sotha Sil) get their own small sub-maps.
2. **A marker for every location that can be detected**, as close as possible to Skyrim's `tmm 1`:
   - every exterior door leading to an interior (tombs, caves, ruins, shipwrecks, strongholds…), with
     several doors to the same place merged into one marker
   - every named exterior cell (the source of vanilla's own map markers)
   - named places with no door (open-air shrines, camps): found by recognising their objects, plus a
     hand-made list
   - interiors reached only from other interiors are grouped under their entrance, not given markers
   - town houses and shops show only at close zoom (or are filtered out)
3. **Everything revealed from the start.** All markers are visible and clickable from the beginning.
   There is no discovery mode. (Decided 2026-11-17: an "Informed" mode that revealed places once heard
   about or visited was dropped, because many other mods already do that and full reveal is what sets
   this mod apart.)
4. **The player's position** shown as an icon on the map (heading shown with 8–16 pre-drawn sprites; in
   interiors the icon sits at the last exterior door).
5. **Search:** type a name, the map centres on it.
6. **Tracking:** click to track (several destinations at once, each with its own colour). Right-click
   empty map to drop a free pin with an optional note. A tracked location clears automatically on entering
   it (a setting).
7. **Compass:** a Skyrim-style horizontal compass HUD, based on Valcule's *Horizontal Compass* (used with
   credit, as its permissions allow). Additions: tracked-destination markers, camera yaw instead of player yaw,
   NorthMarker data generated per load order, an interior mark pointing at the exit towards the
   destination, and a public interface:
   `I.NGLA.addCompassMarker{ id, position, cell, icon }` / `removeCompassMarker(id)`.

## Architecture

```
tools/generator/   offline Python tool (run by us; also shipped as an optional file)
    esm.py           TES3 ESM/ESP/omwaddon record reader
    extract.py       merges the load order: cells, doors, land, NorthMarkers
    render.py        draws the map image from LAND records
    build.py         command line: build one release profile -> output/<profile>/
    builds.json      the three release profiles (content file lists)
mod/               the OpenMW mod itself (Lua), identical code for every profile
    scripts/NGLA/...
    textures/NGLA/map/, scripts/NGLA/generated/   generated tiles + location data
```

Lua can't create images and `vfs` is read-only, so the map image **must** be made offline. Every in-game
feature reads the generated data.

### Verified API facts (OpenMW 0.51.0)
- `I.UI.registerWindow('Map', show, hide)` replaces the built-in map window (only existing windows can be
  replaced).
- `types.Player.journal(player)`: `.journalTextEntries[i].text/.questId`,
  `.topics[name].entries[i].text/.actor/.id`.
- `core.dialogue.*` record infos expose `resultScript`.
- `world.cells`, `cell:getAll(types.Door)` (global scripts only), `Door.isTeleport/destCell/destPosition`.
- Cells: `displayName` (localised), `region`, `gridX/gridY`, `hasTag("QuasiExterior")`.
- No image rotation is documented for UI widgets, so headings use pre-drawn sprites.

## Releases

Three versions share the same code and differ only in their data pack:

| Profile | Content files |
|---|---|
| `vanilla` | Morrowind, Tribunal, Bloodmoon |
| `tr` | + Tamriel_Data, TR_Mainland |
| `tr-pc-shotn` | + Sky_Main, Cyr_Main |

Each data pack records which mod versions it was built from, so the mod can warn about a mismatch. It needs
re-building when TR, PC or SHotN release new land. Stretch goal: an optional in-game door scan adds markers
for dungeon mods without land (OAAB, quest mods) that aren't in the data pack.

### Optional generator file (decided 2026-11-17)

The main file lists exactly what it covers, and we update it for major TR / PC / SHotN releases. The
generator also ships as a separate **optional file** for players who want the map and markers synced to
their own load order (new landmasses included). Plan:
- Package it as a standalone Windows exe (e.g. PyInstaller) so players don't need Python.
- It finds openmw.cfg on its own, reads the active load order, and asks before writing anything.
- It writes to its own data folder (e.g. `NGLA Custom Data/`) that the player adds after the main
  mod. OpenMW's later data dirs win, so this overrides the shipped pack without touching it, and deleting
  the folder reverts to stock.
- The mod compares the data pack's recorded content list with the live load order and offers a "your map
  is out of date, re-run the generator" notice when they differ.

## Marker style

Plain coloured dots, no per-type icons (decided 2026-11-17: keep the mod simple; the core loop is open
map, search, zoom, click). The colour comes straight from generator data, so no UESP lookup is needed:

| Colour | Meaning | Generator source |
|---|---|---|
| Yellow | settlements and named places | named exterior cells (`k='l'`) |
| Blue | in-town locations (houses, shops, guilds) | entrances with `t=true`, shown at close zoom |
| Red | wilderness locations (caves, tombs, ruins…) | all other entrances |

## Credits

- Valcule — *Horizontal Compass* (compass method and textures)
