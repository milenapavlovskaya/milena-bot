"""Генерация персональной карточки с результатом теста."""
import io
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONTS = Path(__file__).with_name("assets") / "fonts"
S = 2  # суперсэмплинг для гладких линий

PALETTES = {
    "green":  {"bg": ((214, 244, 226), (190, 226, 240)), "accent": (52, 168, 120), "dark": (30, 82, 70)},
    "yellow": {"bg": ((255, 240, 205), (255, 214, 214)), "accent": (232, 164, 40), "dark": (110, 72, 30)},
    "orange": {"bg": ((255, 222, 205), (240, 200, 235)), "accent": (232, 110, 80), "dark": (112, 52, 60)},
}


def _font(size: int, idx: int) -> ImageFont.FreeTypeFont:
    """idx 5 — жирный шрифт, остальное — обычный (PT Sans лежит рядом с ботом)."""
    name = "PTSans-Bold.ttf" if idx == 5 else "PTSans-Regular.ttf"
    return ImageFont.truetype(str(FONTS / name), size * S)


def make_result_card(name: str, score: int, max_score: int, title: str, color: str) -> bytes:
    pal = PALETTES.get(color, PALETTES["yellow"])
    W, H = 1080 * S // S, 1080
    W, H = W * S, H * S
    c1, c2 = pal["bg"]
    img = Image.new("RGB", (W, H))
    px = img.load()
    for y in range(H):
        for x in range(W):
            t = x / W * 0.5 + y / H * 0.5
            px[x, y] = tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    od.ellipse((-200 * S, -200 * S, 450 * S, 450 * S), fill=(255, 255, 255, 120))
    od.ellipse((700 * S, 700 * S, 1300 * S, 1300 * S), fill=(255, 255, 255, 100))
    ov = ov.filter(ImageFilter.GaussianBlur(50 * S))
    img = Image.alpha_composite(img.convert("RGBA"), ov)
    d = ImageDraw.Draw(img)

    def center(text, y, font, fill):
        w = d.textlength(text, font=font)
        d.text(((W - w) / 2, y * S), text, font=font, fill=fill)

    dark, accent = pal["dark"], pal["accent"]
    center(f"{name}, твой результат".strip(", "), 70, _font(46, 0), dark)

    # круговая шкала
    cx, cy, r, wd = W // 2, 470 * S, 280 * S, 52 * S
    box = (cx - r, cy - r, cx + r, cy + r)
    d.arc(box, 0, 360, fill=(255, 255, 255, 170), width=wd)
    frac = max(0.02, min(1.0, score / max_score))
    d.arc(box, -90, -90 + 360 * frac, fill=accent, width=wd)
    # скруглённый конец дуги
    ang = math.radians(-90 + 360 * frac)
    mid = r - wd / 2
    ex, ey = cx + mid * math.cos(ang), cy + mid * math.sin(ang)
    d.ellipse((ex - wd / 2, ey - wd / 2, ex + wd / 2, ey + wd / 2), fill=accent)
    sx, sy = cx, cy - mid
    d.ellipse((sx - wd / 2, sy - wd / 2, sx + wd / 2, sy + wd / 2), fill=accent)

    center(str(score), 340, _font(210, 5), dark)
    center(f"из {max_score} баллов", 580, _font(44, 0), dark)

    # плашка с уровнем
    f = _font(52, 5)
    tw = d.textlength(title, font=f)
    pad = 50 * S
    x0, x1 = (W - tw) / 2 - pad, (W + tw) / 2 + pad
    d.rounded_rectangle((x0, 850 * S, x1, 960 * S), radius=55 * S, fill=accent)
    d.text(((W - tw) / 2, 865 * S), title, font=f, fill=(255, 255, 255))
    center("Тренер Милена", 1000, _font(32, 0), dark)

    img = img.convert("RGB").resize((1080, 1080), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=92)
    return buf.getvalue()
