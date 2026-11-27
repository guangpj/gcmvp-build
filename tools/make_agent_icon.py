#!/usr/bin/env python3
"""Generate a simple blue icon for the gcmvp agent build.

No third-party dependencies: writes a 256x256 PNG wrapped in an ICO container
(supported by all modern Windows versions). The file is checked into the repo
so the cloud build can copy it over the RustDesk app icon without downloading
anything.
"""
import os
import struct
import zlib

W = H = 256

# A blocky "G" so the icon is recognizable at small sizes.
GLYPH = [
    ".####.",
    "##..##",
    "##....",
    "##.###",
    "##..##",
    "##..##",
    ".####.",
]
SCALE = 17
GW = len(GLYPH[0]) * SCALE
GH = len(GLYPH) * SCALE
OX = (W - GW) // 2
OY = (H - GH) // 2


def _chunk(kind: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + kind + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))


def make_png() -> bytes:
    rows = []
    for y in range(H):
        row = bytearray()
        t = y / max(1, H - 1)
        # subtle blue gradient
        bg = (int(26 + 14 * t), int(105 - 34 * t), int(218 - 46 * t), 255)
        for x in range(W):
            gx = (x - OX) // SCALE
            gy = (y - OY) // SCALE
            inside = (0 <= gx < len(GLYPH[0]) and 0 <= gy < len(GLYPH)
                      and GLYPH[gy][gx] == "#")
            row += bytes((255, 255, 255, 255) if inside else bg)
        rows.append(b"\x00" + bytes(row))  # PNG filter type 0

    ihdr = struct.pack(">IIBBBBB", W, H, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", ihdr)
            + _chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
            + _chunk(b"IEND", b""))


def make_ico() -> bytes:
    png = make_png()
    header = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, len(png), 22)
    return header + entry + png


if __name__ == "__main__":
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "gcmvp_agent.ico")
    with open(out, "wb") as f:
        f.write(make_ico())
    print(f"wrote {out} ({os.path.getsize(out)} bytes)")
