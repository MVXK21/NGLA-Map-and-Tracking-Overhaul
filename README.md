# NGLA Map and Tracking Overhaul

**Never Get Lost Again.** A new world map, location search, destination tracking and a Skyrim-style
compass for OpenMW. There are no quest markers: you find a place on the map, click it, and the
compass points you there.

## Features

- **A painted world map** made from the game's own land data: real ground colours from the terrain
  textures, relief shading, water shaded by depth, and the road network drawn as clean lines. It covers
  Vvardenfell, Solstheim, Tamriel Rebuilt, Project Cyrodiil and Skyrim: Home of the Nords in one map,
  with zoom from the whole continent down to single streets.
- **Every location marked from the start.** Each cave, tomb, ruin, shipwreck, stronghold and house with
  a door gets a marker, plus every named place and places you can only reach by teleport (Mournhold).
  - Yellow: settlements and named places
  - Red: wilderness locations
  - Blue: buildings inside towns (shown when zoomed in)
- **Search** by name: type part of a name and the map jumps to the result.
- **Tracking:** click a location to track it (up to 5 at once, each with its own colour). Right-click
  empty map to drop a pin. Tracking stops by itself when you arrive.
- **Compass** at the top of the screen with N/E/S/W and your tracked destinations, showing the name and
  distance of the one ahead. Indoors it points to the exit that leads towards your destination and
  turns with each interior's own north.
- **Your position** on the map, with the direction you're facing.
- **Settings:** compass size and position, label, how many destinations to track, stop tracking on
  arrival.

## Requirements

- **OpenMW 0.51 or newer.** This is an OpenMW Lua mod; it doesn't work with the original Morrowind engine
  or MWSE.
- Morrowind with Tribunal and Bloodmoon.
- For the bigger versions: Tamriel Rebuilt (with Tamriel_Data), Project Cyrodiil and Skyrim: Home of
  the Nords, matching the version you download.

## Which version?

Download **one** main file, matching the lands in your game:

| File | Map covers |
|---|---|
| Vanilla | Morrowind, Tribunal, Bloodmoon |
| TR | + Tamriel Rebuilt (Tamriel_Data, TR_Mainland) |
| TR-PC-SHotN | + Project Cyrodiil (Cyr_Main) and Skyrim: Home of the Nords (Sky_Main) |

The code is the same in all three. Only the map and location data differ.

## Installation

1. Extract the archive anywhere, for example into your mods folder. You get a folder named
   `NGLA Map and Tracking Overhaul`.
2. In the **OpenMW Launcher**, open **Data Directories**, add that folder, then on the **Content Files**
   page tick `NGLA Map and Tracking Overhaul.omwscripts`.

   Or in `openmw.cfg`, add:
   ```
   data="C:/path/to/NGLA Map and Tracking Overhaul"
   content=NGLA Map and Tracking Overhaul.omwscripts
   ```
3. Start the game. Settings are under **Options > Scripts > NGLA Map and Tracking Overhaul**.

Safe to add to an existing save. To uninstall, untick or remove the two lines; tracked destinations
are simply forgotten.

## Controls

| | |
|---|---|
| **M** | open the full-size map; M again closes it |
| **Tab** (inventory menu) | the map appears in the usual map window |
| drag | move the map |
| mouse wheel | zoom (towards the cursor) |
| left-click a marker | track it / stop tracking it |
| right-click empty map | drop a pin; right-click a pin to remove it |
| search box | type a name; Enter or click a result to jump to it |

## Your own load order: the optional generator

The main file's map matches the lands listed above, as of their versions at release. If you use other
land or dungeon mods, or want the map to use your texture replacers' colours, get the optional
**NGLA Map Generator**. It's published on the mod's GitHub page (linked from the Nexus page), next to
its full source code, so you can check what it does or run it from source instead of the exe.

1. Extract it anywhere and run `NGLA Map Generator.exe`. It finds your `openmw.cfg`, reads your load
   order, shows what it found and asks before writing anything.
2. It builds a folder named `NGLA Custom Data` next to the program (a few minutes for big load orders).
3. Add that folder as a data directory **below** `NGLA Map and Tracking Overhaul` (launcher Data
   Directories, or a `data=` line after the mod's own line in `openmw.cfg`).

Run it again whenever your load order changes. Delete the folder (and its data line) to go back to the
map that came with the mod. It never changes your game, your mods or your `openmw.cfg`.

## Compatibility

- **Replaces the built-in map window.** Other mods that replace the map window will conflict.
- **Other compass mods:** you'll see two compasses. Turn ours off in the settings, or disable the other.
- **Quest marker mods** that add their own map or window (for example QuestMapMarkers) work, but you'll
  have two maps; most people will want just one.
- Works with texture and mesh replacers, and with any mod that doesn't add new land. New dungeons from
  other mods appear on the map only with the optional generator.

## Permissions

You're free to use this mod in your own work: modify it, build on it, make patches, add-ons and
translations, and use its code and generator in your own mods. Just give credit to MVXK21 and link back
to this mod.

The compass textures come from Valcule's *Horizontal Compass* and remain under Valcule's own
permissions; credit Valcule if you use them.

## Credits

- **Valcule** for *Horizontal Compass*: the compass strip method and its textures are used and modified
  with credit, as its permissions allow.
- **Bethesda Softworks** for Morrowind.
- **The Tamriel Rebuilt, Project Cyrodiil and Skyrim: Home of the Nords teams**, whose lands are mapped.
- **The OpenMW team** for the engine and its Lua API.

Made by MVXK21.
