"""Minimal reader for TES3 plugin files (.esm / .esp / .omwaddon).

File layout: a sequence of records. Each record has a 16-byte header
(type[4], size u32, unused u32, flags u32) followed by `size` bytes of
subrecords. Each subrecord is (name[4], size u32, data).

Only the record types the generator needs are decoded; everything else is
skipped without being parsed.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

ENCODING = "cp1252"

_REC_HDR = struct.Struct("<4sIII")
_SUB_HDR = struct.Struct("<4sI")


def cstr(data: bytes) -> str:
    """Decode a (possibly zero-terminated) string subrecord."""
    end = data.find(b"\0")
    if end >= 0:
        data = data[:end]
    return data.decode(ENCODING, errors="replace")


@dataclass
class Record:
    type: str
    flags: int
    subs: list[tuple[str, bytes]]

    def first(self, name: str) -> bytes | None:
        for n, d in self.subs:
            if n == name:
                return d
        return None


def iter_records(path: Path, wanted: set[str] | None = None) -> Iterator[Record]:
    """Yield records from a plugin file. Only types in `wanted` get their
    subrecords split; with wanted=None every record is decoded."""
    data = Path(path).read_bytes()
    pos, end = 0, len(data)
    while pos + 16 <= end:
        rtype, size, _unused, flags = _REC_HDR.unpack_from(data, pos)
        body_start = pos + 16
        body_end = body_start + size
        if body_end > end:
            raise ValueError(f"{path}: truncated record at offset {pos}")
        t = rtype.decode("ascii", errors="replace")
        if wanted is None or t in wanted:
            subs = []
            p = body_start
            while p + 8 <= body_end:
                name, ssize = _SUB_HDR.unpack_from(data, p)
                p += 8
                subs.append((name.decode("ascii", errors="replace"), data[p:p + ssize]))
                p += ssize
            yield Record(t, flags, subs)
        pos = body_end


def read_masters(path: Path) -> list[str]:
    """Return the MAST list from the file's TES3 header record."""
    for rec in iter_records(path, {"TES3"}):
        return [cstr(d) for n, d in rec.subs if n == "MAST"]
    return []


# ---------------------------------------------------------------- CELL

CELL_INTERIOR = 0x01
CELL_HAS_WATER = 0x02
CELL_BEHAVE_EXTERIOR = 0x80  # "QuasiExterior": Mournhold, Sotha Sil


@dataclass
class CellRef:
    frmr: int                      # raw FRMR (high byte = master index, low 24 bits = ref index)
    id: str = ""                   # base object id, lowercase
    pos: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rot: tuple[float, float, float] = (0.0, 0.0, 0.0)
    dest_pos: tuple[float, float, float] | None = None   # DODT: teleport door target
    dest_rot: tuple[float, float, float] | None = None
    dest_cell: str | None = None   # DNAM: target interior name (None => exterior)
    deleted: bool = False


@dataclass
class Cell:
    name: str = ""
    flags: int = 0
    grid: tuple[int, int] = (0, 0)
    region: str | None = None
    water_height: float | None = None
    refs: list[CellRef] = field(default_factory=list)
    deleted: bool = False

    @property
    def interior(self) -> bool:
        return bool(self.flags & CELL_INTERIOR)


_F3x2 = struct.Struct("<6f")


def parse_cell(rec: Record) -> Cell:
    cell = Cell()
    ref: CellRef | None = None
    for name, d in rec.subs:
        if name == "FRMR":
            ref = CellRef(frmr=struct.unpack_from("<I", d)[0])
            cell.refs.append(ref)
            continue
        if ref is None:
            # cell-level subrecords (appear before the first reference)
            if name == "NAME":
                cell.name = cstr(d)
            elif name == "DATA" and len(d) >= 12:
                cell.flags, gx, gy = struct.unpack_from("<Iii", d)
                cell.grid = (gx, gy)
            elif name == "RGNN":
                cell.region = cstr(d).lower()
            elif name == "WHGT" and len(d) >= 4:
                cell.water_height = struct.unpack_from("<f", d)[0]
            elif name == "DELE":
                cell.deleted = True
        else:
            if name == "NAME":
                ref.id = cstr(d).lower()
            elif name == "DATA" and len(d) >= 24:
                v = _F3x2.unpack_from(d)
                ref.pos, ref.rot = v[:3], v[3:]
            elif name == "DODT" and len(d) >= 24:
                v = _F3x2.unpack_from(d)
                ref.dest_pos, ref.dest_rot = v[:3], v[3:]
            elif name == "DNAM":
                ref.dest_cell = cstr(d)
            elif name == "DELE":
                ref.deleted = True
    return cell


# ---------------------------------------------------------------- LAND

LAND_SIZE = 65  # vertices per side; neighbouring cells share their edge row/column


@dataclass
class Land:
    grid: tuple[int, int]
    heights: "object | None" = None   # numpy float32 (65, 65), game units; row 0 = south edge
    colors: "object | None" = None    # numpy uint8 (65, 65, 3)


def parse_land(rec: Record):
    import numpy as np

    intv = rec.first("INTV")
    if intv is None:
        return None
    gx, gy = struct.unpack_from("<ii", intv)
    land = Land((gx, gy))
    vhgt = rec.first("VHGT")
    if vhgt is not None and len(vhgt) >= 4 + LAND_SIZE * LAND_SIZE:
        offset = struct.unpack_from("<f", vhgt)[0]
        deltas = np.frombuffer(vhgt, dtype=np.int8, count=LAND_SIZE * LAND_SIZE, offset=4)
        d = deltas.reshape(LAND_SIZE, LAND_SIZE).astype(np.float32)
        # The first value of each row is relative to the first value of the row
        # before; the rest of the row is relative to its left neighbour.
        d[:, 0] = offset + np.cumsum(d[:, 0])
        land.heights = np.cumsum(d, axis=1) * 8.0
    vclr = rec.first("VCLR")
    if vclr is not None and len(vclr) >= LAND_SIZE * LAND_SIZE * 3:
        land.colors = np.frombuffer(vclr, dtype=np.uint8, count=LAND_SIZE * LAND_SIZE * 3).reshape(
            LAND_SIZE, LAND_SIZE, 3)
    return land
