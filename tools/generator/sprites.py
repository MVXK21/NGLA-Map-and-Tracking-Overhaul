"""Draw the mod's small UI sprites (placeholder art).

    python sprites.py

Writes to mod/textures/NGLA/icons/:
    white.png         plain white, tinted in Lua for backgrounds
    dot.png           white marker dot with a dark rim, tinted per marker type
    arrow_00..15.png  player arrow in 16 headings, 22.5 degrees apart,
                      clockwise from north (Lua UI images can't rotate)
"""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[2] / "mod" / "textures" / "NGLA" / "icons"


def main():
    OUT.mkdir(parents=True, exist_ok=True)

    Image.new("RGBA", (4, 4), (255, 255, 255, 255)).save(OUT / "white.png")

    s = 64
    dot = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(dot)
    d.ellipse([2, 2, s - 3, s - 3], fill=(20, 15, 10, 255))
    d.ellipse([10, 10, s - 11, s - 11], fill=(255, 255, 255, 255))
    dot.save(OUT / "dot.png")

    s = 128
    base = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(base)
    c = s / 2
    shape = [(c, 8), (c + 40, s - 18), (c, s - 40), (c - 40, s - 18)]
    d.polygon(shape, fill=(20, 15, 10, 255))
    inner = [(c, 22), (c + 30, s - 28), (c, s - 50), (c - 30, s - 28)]
    d.polygon(inner, fill=(255, 235, 170, 255))
    for i in range(16):
        # PIL rotates counter-clockwise for positive angles; headings go clockwise
        img = base.rotate(-i * 22.5, resample=Image.BICUBIC)
        img.save(OUT / f"arrow_{i:02d}.png")
    # ring drawn around a tracked marker / search result
    s = 64
    ring = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(ring)
    d.ellipse([2, 2, s - 3, s - 3], outline=(20, 15, 10, 255), width=12)
    d.ellipse([6, 6, s - 7, s - 7], outline=(255, 255, 255, 255), width=5)
    ring.save(OUT / "ring.png")

    # map pin: round head, tip at the bottom centre
    w, h = 64, 96
    pin = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(pin)
    d.polygon([(w / 2, h - 2), (8, 34), (w - 8, 34)], fill=(20, 15, 10, 255))
    d.ellipse([2, 2, w - 3, w - 3], fill=(20, 15, 10, 255))
    d.polygon([(w / 2, h - 12), (14, 36), (w - 14, 36)], fill=(255, 255, 255, 255))
    d.ellipse([9, 9, w - 10, w - 10], fill=(255, 255, 255, 255))
    d.ellipse([w / 2 - 8, w / 2 - 8, w / 2 + 8, w / 2 + 8], fill=(20, 15, 10, 255))
    pin.save(OUT / "pin.png")

    print(f"sprites -> {OUT}")


if __name__ == "__main__":
    main()
