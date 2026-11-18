NGLA Map Generator (optional file for NGLA Map and Tracking Overhaul)
=====================================================================

Builds the NGLA world map, location markers and compass data for YOUR load
order: every land mod, dungeon mod and texture replacer you use. You need the
main mod installed too; this only replaces its map data.

1. Run "NGLA Map Generator.exe". It finds your openmw.cfg (Documents\My Games\
   OpenMW), reads your load order, shows what it found and asks before
   writing anything.
2. It builds a folder named "NGLA Custom Data" next to the program. Big load
   orders take a few minutes and a few GB of memory.
3. Add that folder to OpenMW as a data directory BELOW "NGLA Map and Tracking
   Overhaul":
     - OpenMW Launcher > Data Directories: add it and move it below the mod, or
     - openmw.cfg: add the data= line the program prints, below the mod's own
       data= line.

Run it again whenever your load order changes. To go back to the map that came
with the mod, delete the folder and its data directory entry.

It never changes your game, your mods or your openmw.cfg.

Options (from a command prompt):
  --cfg "path\to\openmw.cfg"    use a specific openmw.cfg
  --out "folder"                write somewhere else
  --yes                         don't ask before writing

About antivirus warnings
------------------------
The exe is the Python script tools/generator/ngla_generate.py packed with
PyInstaller, so it runs without Python installed. Some antivirus tools flag
PyInstaller programs in general, whatever they contain. The full source code
is on the same GitHub page as this download. If you'd rather not run the exe,
run the generator from source instead:

1. Install Python 3.10 or newer (python.org), ticking "Add python.exe to PATH".
2. Download the source code (GitHub: Code > Download ZIP) and extract it.
3. In a command prompt, in the extracted folder's tools\generator folder:
     pip install -r requirements.txt
     python ngla_generate.py
   It works exactly like the exe, with the same options.
