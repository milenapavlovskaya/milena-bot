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
    """Рисуется быстро (без попиксельных циклов): бесплатный сервер очень слабый."""
    pal = PALETTES.get(color, PALETTES["yellow"])
    SIZE = 1080
    c1, c2 = pal["bg"]
    dark, accent = pal["dark"], pal["accent"]

    # фон: плавный градиент + размытые светлые пятна (всё в уменьшенном размере)
    mask = Image.linear_gradient("L").resize((SIZE, SIZE), Image.BILINEAR)
    bg = Image.composite(Image.new("RGB", (SIZE, SIZE), c2), Image.new("RGB", (SIZE, SIZE), c1), mask)
    small = Image.new("RGBA", (270, 270), (0, 0, 0, 0))
    sd = ImageDraw.Draw(small)
    sd.ellipse((-50, -50, 110, 110), fill=(255, 255, 255, 120))
    sd.ellipse((175, 175, 325, 325), fill=(255, 255, 255, 100))
    small = small.filter(ImageFilter.GaussianBlur(12)).resize((SIZE, SIZE), Image.BILINEAR)
    base = Image.alpha_composite(bg.convert("RGBA"), small)

    # передний план рисуем в 2 раза крупнее для гладких линий, затем уменьшаем
    W = SIZE * S
    fg = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    d = ImageDraw.Draw(fg)

    def center(text, y, font, fill):
        w = d.textlength(text, font=font)
        d.text(((W - w) / 2, y * S), text, font=font, fill=fill)

    center(f"{name}, твой результат".strip(", "), 70, _font(46, 0), dark)

    cx, cy, r, wd = W // 2, 470 * S, 280 * S, 52 * S
    box = (cx - r, cy - r, cx + r, cy + r)
    d.arc(box, 0, 360, fill=(255, 255, 255, 170), width=wd)
    frac = max(0.02, min(1.0, score / max_score))
    d.arc(box, -90, -90 + 360 * frac, fill=accent, width=wd)
    ang = math.radians(-90 + 360 * frac)
    mid = r - wd / 2
    ex, ey = cx + mid * math.cos(ang), cy + mid * math.sin(ang)
    d.ellipse((ex - wd / 2, ey - wd / 2, ex + wd / 2, ey + wd / 2), fill=accent)
    sx, sy = cx, cy - mid
    d.ellipse((sx - wd / 2, sy - wd / 2, sx + wd / 2, sy + wd / 2), fill=accent)

    center(str(score), 340, _font(210, 5), dark)
    center(f"из {max_score} баллов", 580, _font(44, 0), dark)

    f = _font(52, 5)
    tw = d.textlength(title, font=f)
    pad = 50 * S
    d.rounded_rectangle(((W - tw) / 2 - pad, 850 * S, (W + tw) / 2 + pad, 960 * S),
                        radius=55 * S, fill=accent)
    d.text(((W - tw) / 2, 865 * S), title, font=f, fill=(255, 255, 255))
    center("Тренер Милена", 1000, _font(32, 0), dark)

    fg = fg.resize((SIZE, SIZE), Image.LANCZOS)
    img = Image.alpha_composite(base, fg).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    return buf.getvalue()
