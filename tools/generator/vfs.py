"""Find game files the way OpenMW does: loose files in the data= directories
(later directories win), then the fallback-archive= BSAs (later archives win).

Only what the generator needs: look up a file by its path under the data
root (e.g. "textures/tx_ai_grass_01.dds") and read its bytes.
"""
from __future__ import annotations

import os
import struct
from pathlib import Path


class BSA:
    """TES3 (Morrowind) BSA archive, version 0x100."""

    def __init__(self, path: Path):
        self.path = path
        self.files: dict[str, tuple[int, int]] = {}   # lowercase name with / -> (offset, size)
        with open(path, "rb") as f:
            version, hash_offset, count = struct.unpack("<III", f.read(12))
            if version != 0x100:
                raise ValueError(f"{path}: not a Morrowind BSA")
            sizes = struct.unpack(f"<{count * 2}I", f.read(8 * count))
            name_offsets = struct.unpack(f"<{count}I", f.read(4 * count))
            names_start = 12 + 12 * count
            f.seek(names_start)
            names = f.read(hash_offset - 12 * count)
            data_start = 12 + hash_offset + 8 * count
            for i in range(count):
                start = name_offsets[i]
                end = names.index(b"\0", start)
                name = names[start:end].decode("cp1252").replace("\\", "/").lower()
                self.files[name] = (data_start + sizes[2 * i + 1], sizes[2 * i])

    def read(self, name: str) -> bytes:
        off, size = self.files[name]
        with open(self.path, "rb") as f:
            f.seek(off)
            return f.read(size)


class VFS:
    def __init__(self, data_dirs: list[Path], archives: list[str]):
        self.data_dirs = data_dirs
        self._listing: dict[str, dict[str, Path]] = {}    # subdir -> lowercase name -> path
        self.archives: list[BSA] = []
        for a in archives:
            for d in reversed(data_dirs):
                p = d / a
                if p.is_file():
                    self.archives.append(BSA(p))
                    break

    def _index(self, subdir: str) -> dict[str, Path]:
        """Every loose file directly in <data dir>/<subdir>, later dirs winning."""
        if subdir not in self._listing:
            idx: dict[str, Path] = {}
            for d in self.data_dirs:
                try:
                    with os.scandir(d / subdir) as it:
                        for e in it:
                            if e.is_file():
                                idx[e.name.lower()] = Path(e.path)
                except OSError:
                    continue
            self._listing[subdir] = idx
        return self._listing[subdir]

    def read(self, path: str) -> bytes | None:
        path = path.replace("\\", "/").lower()
        sub, _, name = path.rpartition("/")
        loose = self._index(sub).get(name)
        if loose is not None:
            return loose.read_bytes()
        for a in reversed(self.archives):
            if path in a.files:
                return a.read(path)
        return None

    def read_texture(self, name: str) -> bytes | None:
        """Like the engine: try the .dds version first, then the name as given."""
        name = name.replace("\\", "/").lower()
        if not name.startswith("textures/"):
            name = "textures/" + name
        stem = name.rsplit(".", 1)[0]
        for candidate in (stem + ".dds", name, stem + ".tga", stem + ".bmp"):
            data = self.read(candidate)
            if data is not None:
                return data
        return None


def read_archives(cfg: Path) -> list[str]:
    out = []
    for line in Path(cfg).read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith("fallback-archive="):
            out.append(line.split("=", 1)[1].strip())
    return out
