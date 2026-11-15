"""Builds the 1920x1080 Store screenshots, a 300x300 logo and a 600x600 thumbnail.

Raw window capture: packaging/store-assets/src/window.png (made with SD_SHOT, see main.py).
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "src"))
from icon import make_icon  # noqa: E402

SRC = os.path.join(HERE, "store-assets", "src")
OUT = os.path.join(HERE, "store-assets")
W, H = 1920, 1080
FONTS = r"C:\Windows\Fonts"


def font(bold, size):
    return ImageFont.truetype(os.path.join(FONTS, "segoeuib.ttf" if bold else "segoeui.ttf"), size)


def background(top=(232, 84, 72), bottom=(160, 46, 120)):
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)], fill=tuple(int(top[i] * (1 - t) + bottom[i] * t) for i in range(3)))
    glow = Image.new("L", (W, H), 0)
    ImageDraw.Draw(glow).ellipse([1000, -300, 2300, 900], fill=80)
    glow = glow.filter(ImageFilter.GaussianBlur(160))
    img.paste(Image.new("RGB", (W, H), (255, 190, 120)), (0, 0), glow)
    return img.convert("RGBA")


def rounded(im, r):
    mask = Image.new("L", im.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, im.size[0] - 1, im.size[1] - 1], radius=r, fill=255)
    out = Image.new("RGBA", im.size, (0, 0, 0, 0))
    out.paste(im.convert("RGBA"), (0, 0), mask)
    return out


def shadow_paste(canvas, im, xy, blur=40, offset=(0, 24), opacity=110):
    sh = Image.new("RGBA", (im.size[0] + blur * 4, im.size[1] + blur * 4), (0, 0, 0, 0))
    alpha = im.split()[-1].point(lambda a: opacity if a else 0)
    sh.paste((0, 0, 0, 255), (blur * 2, blur * 2), alpha)
    sh = sh.filter(ImageFilter.GaussianBlur(blur))
    canvas.alpha_composite(sh, (xy[0] - blur * 2 + offset[0], xy[1] - blur * 2 + offset[1]))
    canvas.alpha_composite(im, xy)


def window(width, crop=None):
    win = Image.open(os.path.join(SRC, "window.png")).convert("RGB")
    if crop:
        win = win.crop(crop)
    h = int(win.size[1] * width / win.size[0])
    return rounded(win.resize((width, h), Image.LANCZOS), 14)


def text_block(canvas, title, sub, bullets=(), x=110, y=270):
    d = ImageDraw.Draw(canvas)
    d.text((x, y - 70), "ShrinkDrop", font=font(True, 34), fill=(255, 225, 205))
    ty = y
    for line in title.split("\n"):
        d.text((x, ty), line, font=font(True, 72), fill="white")
        ty += 88
    ty += 18
    for line in sub.split("\n"):
        d.text((x, ty), line, font=font(False, 34), fill=(255, 238, 230))
        ty += 48
    ty += 30
    for b in bullets:
        d.ellipse([x, ty + 15, x + 14, ty + 29], fill=(255, 214, 120))
        d.text((x + 32, ty), b, font=font(False, 31), fill="white")
        ty += 52


def save(img, name):
    img.convert("RGB").save(os.path.join(OUT, name), optimize=True)
    print("wrote", name)


def main():
    raw = Image.open(os.path.join(SRC, "window.png"))
    rw, rh = raw.size

    c = background()
    text_block(c, "iPhone photos that\nopen everywhere", "Turn HEIC photos into JPG in one click.\nCamera details and dates are kept.",
               ["Drop a whole folder at once", "Right-click → Share → ShrinkDrop", "Choose size and quality"])
    shadow_paste(c, window(960), (880, 150))
    save(c, "1-heic-to-jpg.png")

    c = background((210, 70, 110), (90, 50, 160))
    text_block(c, "Videos small enough\nto email and share", "Pick a size, like 25 MB for email,\nand ShrinkDrop makes it fit.",
               ["Big phone videos shrink by 90%", "Portrait videos stay the right way up", "Sound and quality kept"])
    shadow_paste(c, window(960, (0, 0, rw, int(rh * .58))), (880, 230))
    save(c, "2-shrink-videos.png")

    c = background((40, 120, 140), (60, 60, 150))
    text_block(c, "Private and offline", "Everything happens on your PC.\nNothing is uploaded, ever.",
               ["No account, no ads, no watermark", "Originals are never changed", "Windows 10 and 11"], y=300)
    shadow_paste(c, window(960, (0, int(rh * .68), rw, rh)), (880, 380))
    save(c, "3-private.png")

    make_icon(300).save(os.path.join(OUT, "logo-300.png"))
    thumb = Image.new("RGBA", (600, 600), (0, 0, 0, 0))
    bg = background().resize((1067, 600)).crop((233, 0, 833, 600))
    thumb.paste(bg, (0, 0))
    ic = make_icon(300)
    thumb.alpha_composite(ic, (150, 90))
    d = ImageDraw.Draw(thumb)
    f = font(True, 64)
    tw = d.textlength("ShrinkDrop", font=f)
    d.text(((600 - tw) / 2, 420), "ShrinkDrop", font=f, fill="white")
    save(thumb, "thumb-600.png")
    print("wrote logo-300.png")


if __name__ == "__main__":
    main()
