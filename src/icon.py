"""Draws the ShrinkDrop icon (a photo frame with inward arrows) with Pillow."""
from PIL import Image, ImageDraw

BG_TOP = (255, 122, 69)
BG_BOTTOM = (238, 66, 102)
WHITE = (255, 255, 255, 255)


def make_icon(size=256):
    s = size * 4
    grad = Image.new("RGBA", (s, s))
    gd = ImageDraw.Draw(grad)
    for y in range(s):
        t = y / s
        gd.line([(0, y), (s, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOTTOM)) + (255,))
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle([s * .06, s * .06, s * .94, s * .94], radius=s * .22, fill=255)
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    img.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(img)
    # small picture frame in the middle (mountain + sun)
    x0, y0, x1, y1 = s * .36, s * .38, s * .64, s * .62
    w = int(s * .03)
    d.rounded_rectangle([x0, y0, x1, y1], radius=s * .03, outline=WHITE, width=w)
    d.polygon([(x0 + s * .03, y1 - s * .03), (x0 + s * .11, y0 + s * .09), (x0 + s * .17, y1 - s * .03)], fill=WHITE)
    d.ellipse([x1 - s * .09, y0 + s * .04, x1 - s * .045, y0 + s * .085], fill=WHITE)
    # four arrows pointing inwards from the corners
    for cx, cy, dx, dy in ((.2, .2, 1, 1), (.8, .2, -1, 1), (.2, .8, 1, -1), (.8, .8, -1, -1)):
        tip = (s * (cx + dx * .1), s * (cy + dy * .1))
        tail = (s * cx, s * cy)
        d.line([tail, tip], fill=WHITE, width=int(s * .045))
        a = s * .075
        d.polygon([tip, (tip[0] - dx * a, tip[1]), (tip[0], tip[1] - dy * a)], fill=WHITE)
    return img.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else "app.ico"
    make_icon(256).save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("wrote", out)
