import math
import os
from PIL import Image, ImageDraw, ImageFilter

S = 1024
here = os.path.dirname(os.path.abspath(__file__))


def build():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((24, 24, S - 24, S - 24), radius=230, fill=(6, 6, 6, 255), outline=(38, 38, 38, 255), width=6)
    cx = cy = S // 2
    # soft glow
    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    g = ImageDraw.Draw(glow)
    g.ellipse((cx - 190, cy - 190, cx + 190, cy + 190), fill=(255, 255, 255, 120))
    glow = glow.filter(ImageFilter.GaussianBlur(60))
    img = Image.alpha_composite(img, glow)
    d = ImageDraw.Draw(img)
    # radial bars (voice ring)
    n = 48
    for i in range(n):
        a = 2 * math.pi * i / n - math.pi / 2
        w = 0.5 + 0.5 * math.sin(i * 0.65) * math.sin(i * 0.23 + 1.0)
        r0 = 232
        r1 = r0 + 28 + 150 * w
        shade = int(120 + 135 * w)
        x0, y0 = cx + math.cos(a) * r0, cy + math.sin(a) * r0
        x1, y1 = cx + math.cos(a) * r1, cy + math.sin(a) * r1
        d.line((x0, y0, x1, y1), fill=(shade, shade, shade, 255), width=26)
        for x, y in ((x0, y0), (x1, y1)):
            d.ellipse((x - 13, y - 13, x + 13, y + 13), fill=(shade, shade, shade, 255))
    # core
    d.ellipse((cx - 150, cy - 150, cx + 150, cy + 150), fill=(250, 250, 250, 255))
    d.ellipse((cx - 205, cy - 205, cx + 205, cy + 205), outline=(90, 90, 90, 255), width=7)
    return img


if __name__ == "__main__":
    im = build()
    im.resize((256, 256), Image.LANCZOS).save(os.path.join(here, "icon.png"))
    sizes = [16, 24, 32, 48, 64, 128, 256]
    im.save(os.path.join(here, "icon.ico"), format="ICO", sizes=[(s, s) for s in sizes])
    print("ok")
