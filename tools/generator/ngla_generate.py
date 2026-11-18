"""NGLA Map and Tracking Overhaul - custom map generator.

Builds the world map, location markers and compass data for YOUR load order
(every land mod, dungeon mod and texture replacer you use), into its own folder
that overrides the map shipped with the mod. Nothing in your game or mod
folders is changed.

    NGLA Map Generator.exe                  find openmw.cfg automatically
    NGLA Map Generator.exe --cfg PATH       use this openmw.cfg
    NGLA Map Generator.exe --out FOLDER     write here (default: "NGLA Custom Data" next to the program)
    NGLA Map Generator.exe --yes            don't ask before writing

Afterwards add the output folder to OpenMW as a data directory placed AFTER
"NGLA Map and Tracking Overhaul" (in the launcher's Data Directories list, or
as a data= line below the mod's own data= line in openmw.cfg). Run it again
whenever your load order changes. Delete the folder (and its data= line) to go
back to the map that came with the mod.
"""
from __future__ import annotations

import argparse
import os
import sys
import traceback
from pathlib import Path

import build
import extract

CONTENT_EXT = {".esm", ".esp", ".omwaddon", ".omwgame"}


def documents_dir() -> Path:
    """The real Documents folder on Windows (it may be moved, e.g. into OneDrive)."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            import uuid
            guid = uuid.UUID("{FDD39AD0-238F-46AF-ADB4-6C85480369C7}")   # FOLDERID_Documents

            class GUID(ctypes.Structure):
                _fields_ = [("data", ctypes.c_byte * 16)]

            g = GUID()
            ctypes.memmove(ctypes.byref(g), guid.bytes_le, 16)
            out = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(out)) == 0:
                path = out.value
                ctypes.windll.ole32.CoTaskMemFree(out)
                return Path(path)
        except Exception:
            pass
    return Path.home() / "Documents"


def find_cfg() -> Path | None:
    candidates = []
    if sys.platform == "win32":
        candidates.append(documents_dir() / "My Games" / "OpenMW" / "openmw.cfg")
    elif sys.platform == "darwin":
        candidates.append(Path.home() / "Library" / "Preferences" / "openmw" / "openmw.cfg")
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME")
        candidates.append((Path(xdg) if xdg else Path.home() / ".config") / "openmw" / "openmw.cfg")
    for c in candidates:
        if c.is_file():
            return c
    return None


def _unquote(v: str) -> str:
    v = v.strip()
    if v.startswith('"') and v.endswith('"'):
        v = v[1:-1].replace("&&", "&").replace('&"', '"')
    return v


def read_cfg(cfg: Path) -> tuple[list[Path], list[str]]:
    """data= directories (with ?userdata? resolved) and content= files, in order."""
    dirs, content = [], []
    userdata = cfg.parent
    for line in cfg.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith("data=") or line.startswith("data-local="):
            v = _unquote(line.split("=", 1)[1])
            if v.startswith("?userdata?"):
                v = str(userdata) + "/" + v[len("?userdata?"):]
            elif v.startswith("?"):
                continue
            dirs.append(Path(v))
        elif line.startswith("content="):
            name = line.split("=", 1)[1].strip()
            if Path(name).suffix.lower() in CONTENT_EXT:
                content.append(name)
    return dirs, content


def resolve(names: list[str], dirs: list[Path]) -> tuple[list[Path], list[str]]:
    index: dict[str, Path] = {}
    for d in dirs:
        try:
            for e in d.iterdir():
                if e.is_file():
                    index[e.name.lower()] = e
        except OSError:
            continue
    found, missing = [], []
    for n in names:
        p = index.get(n.lower())
        (found.append(p) if p else missing.append(n))
    return found, missing


def main() -> int:
    ap = argparse.ArgumentParser(description="Build the NGLA map for your own load order.")
    ap.add_argument("--cfg", help="path to openmw.cfg")
    ap.add_argument("--out", help='output folder (default: "NGLA Custom Data" next to this program)')
    ap.add_argument("--yes", action="store_true", help="don't ask before writing")
    args = ap.parse_args()

    print("NGLA Map and Tracking Overhaul - custom map generator\n")
    cfg = Path(args.cfg) if args.cfg else find_cfg()
    if not cfg or not cfg.is_file():
        print("Couldn't find openmw.cfg. Run again with --cfg \"path\\to\\openmw.cfg\".")
        return 1
    here = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
    out = (Path(args.out) if args.out else here / "NGLA Custom Data").resolve()

    dirs, names = read_cfg(cfg)
    paths, missing = resolve(names, dirs)
    print(f"openmw.cfg:     {cfg}")
    print(f"data folders:   {len(dirs)}")
    print(f"content files:  {len(paths)} found" + (f", {len(missing)} not found (skipped)" if missing else ""))
    for m in missing[:10]:
        print(f"    not found: {m}")
    print(f"output folder:  {out}\n")
    if not paths:
        print("No content files found; nothing to build.")
        return 1
    if not args.yes:
        try:
            input("Press Enter to build the map (takes a few minutes for big load orders), or close this window to cancel. ")
        except EOFError:
            pass

    build.build("custom", paths, cfg, px=64, mod_dir=out)

    line = f'data="{out.as_posix()}"'
    print("\nFinished. Now add the folder to OpenMW, AFTER NGLA Map and Tracking Overhaul:")
    print("  - OpenMW Launcher > Data Directories: add the folder and move it below the NGLA mod, or")
    print("  - openmw.cfg: add this line below the NGLA mod's own data= line:")
    print(f"      {line}")
    print("Run this again whenever your load order changes.")
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except Exception:
        traceback.print_exc()
        code = 1
    if getattr(sys, "frozen", False):
        try:
            input("\nPress Enter to close.")
        except EOFError:
            pass
    sys.exit(code)
