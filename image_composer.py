"""Pillow-alapú header kép kompozitálás: 600x400, fotó + headline overlay."""

import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

CANVAS_W, CANVAS_H = 600, 400
SAFE_WIDTH = 480
MARGIN = 28

FONT_CANDIDATES = [
    os.path.join("static", "fonts", "DINPro-Bold.otf"),
    os.path.join("static", "fonts", "DIN2014-Bold.ttf"),
    # fallback, amíg a DIN fontfájlok nincsenek feltöltve
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]

POSITIONS = ("bottom-left", "bottom-center", "bottom-right", "top-left", "top-center")


def _load_font(size):
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


def _fill_crop(photo):
    """A fotó méretezése/vágása úgy, hogy kitöltse a 600x400-as vásznat."""
    photo = photo.convert("RGB")
    scale = max(CANVAS_W / photo.width, CANVAS_H / photo.height)
    new_size = (round(photo.width * scale), round(photo.height * scale))
    photo = photo.resize(new_size, Image.LANCZOS)
    left = (photo.width - CANVAS_W) // 2
    top = (photo.height - CANVAS_H) // 2
    return photo.crop((left, top, left + CANVAS_W, top + CANVAS_H))


def _auto_font_size(text, requested=None):
    """A legnagyobb betűméret, amivel a szöveg belefér a biztonsági zónába."""
    size = requested or 64
    while size > 16:
        font = _load_font(size)
        if font.getbbox(text)[2] <= SAFE_WIDTH:
            return size
        size -= 2
    return 16

def compose_header(photo_path, headline, out_path, position="bottom-left",
                   font_size=None, color="#FFFFFF"):
    """Header kép összeállítása. Visszaadja a ténylegesen használt betűméretet."""
    canvas = _fill_crop(Image.open(photo_path))
    headline = (headline or "").strip().upper()
    used_size = None
    if headline:
        used_size = _auto_font_size(headline, font_size)
        font = _load_font(used_size)
        draw = ImageDraw.Draw(canvas, "RGBA")
        bbox = draw.textbbox((0, 0), headline, font=font)
        text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]

        if position not in POSITIONS:
            position = "bottom-left"
        vert, _, horiz = position.partition("-")
        if horiz == "left":
            x = MARGIN
        elif horiz == "right":
            x = CANVAS_W - MARGIN - text_w
        else:
            x = (CANVAS_W - text_w) // 2
        y = MARGIN if vert == "top" else CANVAS_H - MARGIN - text_h

        # lágy árnyék a olvashatóságért
        shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        sdraw = ImageDraw.Draw(shadow)
        sdraw.text((x - bbox[0] + 2, y - bbox[1] + 2), headline,
                   font=font, fill=(0, 0, 0, 190))
        shadow = shadow.filter(ImageFilter.GaussianBlur(3))
        canvas = Image.alpha_composite(canvas.convert("RGBA"), shadow).convert("RGB")

        draw = ImageDraw.Draw(canvas)
        draw.text((x - bbox[0], y - bbox[1]), headline, font=font, fill=color)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    canvas.save(out_path, "JPEG", quality=90, dpi=(72, 72))
    return used_size


def din_font_available():
    return any(
        os.path.exists(p) for p in FONT_CANDIDATES
        if p.startswith(os.path.join("static", "fonts"))
    )
