#!/usr/bin/env python3
"""Erzeugt die PWA-Icons (reines stdlib, kein PIL noetig).

Design: Akzent-blauer Vollton (#0A84FF, voll deckend -> apple-touch-icon-kompatibel)
mit weisser Dokument-Karte und drei blauen Textzeilen.

Aufruf:  python3 tools/make_icons.py   (schreibt nach dashboard/icons/)
"""
import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "icons"
BG = (10, 132, 255, 255)
CARD = (255, 255, 255, 255)
LINE = (10, 132, 255, 255)


def rounded_rect_inside(x, y, x0, y0, x1, y1, r):
    if x < x0 or x > x1 or y < y0 or y > y1:
        return False
    for cx, cy in ((x0 + r, y0 + r), (x1 - r, y0 + r), (x0 + r, y1 - r), (x1 - r, y1 - r)):
        in_x = x0 + r <= x <= x1 - r
        in_y = y0 + r <= y <= y1 - r
        if (not in_x and not in_y) and (x - cx) ** 2 + (y - cy) ** 2 > r * r:
            return False
    return True


def render(size):
    px = []
    for y in range(size):
        row = []
        for x in range(size):
            fx, fy = x / size, y / size
            c = BG
            if rounded_rect_inside(fx, fy, 0.18, 0.20, 0.82, 0.80, 0.09):
                c = CARD
                # drei Textzeilen
                for ly, lx0, lx1 in ((0.36, 0.30, 0.70), (0.48, 0.30, 0.70), (0.60, 0.30, 0.58)):
                    if ly - 0.035 <= fy <= ly + 0.035 and lx0 <= fx <= lx1:
                        c = LINE
                        break
            row.append(c)
        px.append(row)
    return px


def write_png(path, size, pixels):
    raw = b"".join(b"\x00" + bytes(v for px in row for v in px) for row in pixels)

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def main():
    OUT.mkdir(exist_ok=True)
    for size, name in ((512, "icon-512.png"), (512, "icon-512-maskable.png"), (192, "icon-192.png"), (180, "icon-180.png")):
        p = OUT / name
        write_png(p, size, render(size))
        print("geschrieben: %s (%d px, %d B)" % (p, size, p.stat().st_size))


if __name__ == "__main__":
    main()
