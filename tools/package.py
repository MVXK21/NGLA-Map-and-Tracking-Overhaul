"""Build the release archives.

    python tools/package.py            all three main files and the generator
    python tools/package.py tr         just one profile ("generator" for just the generator)

Each archive holds one folder, "NGLA Map and Tracking Overhaul", ready to add
as an OpenMW data directory: the mod's code and art from mod/ (never its
generated files) plus that profile's map tiles and data, built fresh, and the
README. Output: dist/NGLA-Map-and-Tracking-Overhaul-<version>-<label>.zip
"""
from __future__ import annotations

import json
import shutil
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools" / "generator"))

import build      # noqa: E402
import extract    # noqa: E402

VERSION = "1.0.0"
MOD_NAME = "NGLA Map and Tracking Overhaul"
PROFILES = [("vanilla", "Vanilla"), ("tr", "TR"), ("tr-pc-shotn", "TR-PC-SHotN")]

# copied from mod/ as they are; generated content is rebuilt per profile
STATIC = [
    f"{MOD_NAME}.omwscripts",
    "l10n",
    "scripts/NGLA/compass.lua",
    "scripts/NGLA/map.lua",
    "scripts/NGLA/settings.lua",
    "textures/NGLA/compass",
    "textures/NGLA/icons",
]


def stage_profile(profile: str, label: str, cfg: Path) -> Path:
    stage = REPO / "dist" / "stage" / profile
    if stage.exists():
        shutil.rmtree(stage)
    mod = stage / MOD_NAME
    for rel in STATIC:
        src, dst = REPO / "mod" / rel, mod / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        (shutil.copytree if src.is_dir() else shutil.copy2)(src, dst)
    shutil.copy2(REPO / "README.md", mod / "README.md")

    profiles = json.loads((REPO / "tools" / "generator" / "builds.json").read_text())
    paths = extract.resolve_content(profiles[profile], extract.read_openmw_cfg(cfg))
    print(f"\n=== {label} ===")
    build.build(profile, paths, cfg, px=64, mod_dir=mod)

    out = REPO / "dist" / f"NGLA-Map-and-Tracking-Overhaul-{VERSION}-{label}.zip"
    if out.exists():
        out.unlink()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(mod.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(stage).as_posix())
    print(f"-> {out.name}  ({out.stat().st_size / 1e6:.1f} MB)")
    return out


def package_generator() -> Path:
    """Standalone NGLA Map Generator.exe (PyInstaller, one file) + its readme.
    Published as a GitHub release only (linked from Nexus), next to its source,
    because antivirus tools often flag PyInstaller programs."""
    import subprocess
    import tempfile
    gen = REPO / "tools" / "generator"
    dist = REPO / "dist" / "generator"
    with tempfile.TemporaryDirectory() as work:
        subprocess.run([sys.executable, "-m", "PyInstaller", "--onefile", "--console", "--noconfirm",
                        "--clean", "--name", "NGLA Map Generator", "--distpath", str(dist),
                        "--workpath", work, "--specpath", work,
                        "--exclude-module", "tkinter", "--exclude-module", "luaparser",
                        str(gen / "ngla_generate.py")], cwd=gen, check=True)
    out = REPO / "dist" / f"NGLA-Map-Generator-{VERSION}.zip"
    if out.exists():
        out.unlink()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(dist / "NGLA Map Generator.exe", "NGLA Map Generator/NGLA Map Generator.exe")
        z.write(gen / "README-Generator.txt", "NGLA Map Generator/README.txt")
    print(f"-> {out.name}  ({out.stat().st_size / 1e6:.1f} MB)")
    return out


def main():
    cfg = Path(json.loads((REPO / "tools" / "generator" / "paths.local.json").read_text())["openmw_cfg"])
    wanted = sys.argv[1:] or [p for p, _ in PROFILES] + ["generator"]
    for profile, label in PROFILES:
        if profile in wanted:
            stage_profile(profile, label, cfg)
    if "generator" in wanted:
        package_generator()


if __name__ == "__main__":
    main()
