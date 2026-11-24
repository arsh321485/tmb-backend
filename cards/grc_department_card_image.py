"""
Renders sir's "No document yet? Pick whichever path fits you best"
design as a real PNG -- the two options (GRC Department / Generate for
me), each with its icon, title, turnaround time and description.
Same template-code approach as the other cards -- entirely static
content (same for every workspace), so this is one cached image reused
for everyone.

The "I have it now" / "Generate a draft for us instead" buttons stay
real Slack buttons underneath this image -- not baked into it, same
reasoning as every other card with a genuine click target.
"""

import hashlib
import io

from PIL import Image, ImageDraw

from .card_image_common import (
    BG, BRAND_RED, CARD_BG, CARD_BORDER, GENERATED_DIR, INK, MUTED, TEAL,
    draw_footer_bar, font, wrap,
)

# Bump this whenever render_grc_department_card_image's drawing
# changes -- see get_grc_department_card_image_url's cache-key
# comment below.
_TEMPLATE_VERSION = "v7"

_ICON_BG = (223, 236, 252)
_ICON_FG = (40, 80, 150)
_BOLT_BG = (255, 243, 205)
_BOLT_FG = (166, 120, 0)


def _draw_building_icon(draw: ImageDraw.ImageDraw, x0: int, y0: int, size: int) -> None:
    cx, cy = x0 + size / 2, y0 + size / 2
    s = size
    w = max(2, int(s * 0.07))
    bw, bh = s * 0.44, s * 0.52
    bx0, by0 = cx - bw / 2, cy - bh / 2 + s * 0.04
    draw.rectangle([bx0, by0, bx0 + bw, by0 + bh], outline=_ICON_FG, width=w)
    for row in range(3):
        for col in range(2):
            wx0 = bx0 + bw * (0.18 + col * 0.46)
            wy0 = by0 + bh * (0.15 + row * 0.28)
            draw.rectangle([wx0, wy0, wx0 + bw * 0.18, wy0 + bh * 0.16], fill=_ICON_FG)


def _draw_bolt_icon(draw: ImageDraw.ImageDraw, x0: int, y0: int, size: int) -> None:
    cx, cy = x0 + size / 2, y0 + size / 2
    s = size
    draw.polygon(
        [(cx + s * 0.08, cy - s * 0.32), (cx - s * 0.2, cy + s * 0.05), (cx - s * 0.02, cy + s * 0.05),
         (cx - s * 0.08, cy + s * 0.32), (cx + s * 0.2, cy - s * 0.08), (cx + s * 0.02, cy - s * 0.08)],
        fill=_BOLT_FG,
    )


def render_grc_department_card_image() -> bytes:
    width = 1200
    pad = 56
    header_h = 56
    title_h = 64
    gap = 24
    footer_h = 10

    options = [
        ("building", "Option A · GRC Department", "Thorough, done by your own team", "~4 weeks turnaround",
         "Visit grcdepartment.com and take their guided BIA/BCP course (about 4 weeks) to get a real document, then come back and upload it here."),
        ("bolt", "Option B · Generate for me", "Fast, researched automatically", "Ready in minutes",
         "We research your organization and draft a starting BIA/BCP for you to confirm."),
    ]

    measure_img = Image.new("RGB", (10, 10))
    measure_draw = ImageDraw.Draw(measure_img)
    title_font_box = font(True, 24)
    sub_font = font(False, 20)
    meta_font = font(False, 20)
    desc_font = font(False, 21)

    cols = 2
    gap_box = 24
    col_w = (width - pad * 2 - gap_box * (cols - 1)) // cols
    inner_w = col_w - 40

    box_h = 0
    for _, title, subtitle, meta, desc in options:
        title_lines = wrap(measure_draw, title, title_font_box, inner_w - 72)
        desc_lines = wrap(measure_draw, desc, desc_font, inner_w)
        h = 20 + 56 + 16 + len(title_lines) * 30 + 6 + 26 + 16 + 26 + 14 + len(desc_lines) * 28 + 20
        box_h = max(box_h, h)

    subtitle_text = "No document yet? No problem — pick whichever path fits you best:"
    subtitle_font = font(False, 24)
    subtitle_lines = wrap(measure_draw, subtitle_text, subtitle_font, width - pad * 2)

    height = pad + header_h + title_h + len(subtitle_lines) * 32 + gap + box_h + pad + footer_h

    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)


    # Filled pink badge, matching every other Step 3 screen's style.
    badge_text = "STEP 3 · UPLOAD"
    badge_font = font(True, 16)
    badge_tw = draw.textlength(badge_text, font=badge_font)
    badge_w = badge_tw + 56
    badge_x0, badge_y0 = width - pad - badge_w, pad
    draw.rounded_rectangle([badge_x0, badge_y0, width - pad, badge_y0 + 40], radius=20, fill=(252, 225, 225))
    dot_cy = badge_y0 + 20
    draw.ellipse([badge_x0 + 20, dot_cy - 4, badge_x0 + 28, dot_cy + 4], fill=(150, 30, 40))
    draw.text((badge_x0 + 36, badge_y0 + 11), badge_text, font=badge_font, fill=(150, 30, 40))

    y = pad + header_h
    title_font = font(True, 48)
    prefix = "Choose your "
    x = pad
    draw.text((x, y), prefix, font=title_font, fill=INK)
    x += draw.textlength(prefix, font=title_font)
    draw.text((x, y), "path", font=title_font, fill=BRAND_RED)
    y += title_h

    for line in subtitle_lines:
        draw.text((pad, y), line, font=subtitle_font, fill=MUTED)
        y += 32
    y += gap

    for i, (icon_key, title, subtitle, meta, desc) in enumerate(options):
        bx = pad + i * (col_w + gap_box)
        draw.rounded_rectangle([bx, y, bx + col_w, y + box_h], radius=14, fill=CARD_BG, outline=CARD_BORDER, width=2)
        icon_size = 56
        icon_bg = _BOLT_BG if icon_key == "bolt" else _ICON_BG
        draw.rounded_rectangle([bx + 20, y + 20, bx + 20 + icon_size, y + 20 + icon_size], radius=12, fill=icon_bg)
        if icon_key == "bolt":
            _draw_bolt_icon(draw, bx + 20, y + 20, icon_size)
        else:
            _draw_building_icon(draw, bx + 20, y + 20, icon_size)

        ty = y + 20
        for line in wrap(draw, title, title_font_box, inner_w - 72):
            draw.text((bx + 20 + icon_size + 16, ty), line, font=title_font_box, fill=INK)
            ty += 30
        ty = y + 20 + icon_size + 16
        draw.text((bx + 20, ty), subtitle, font=sub_font, fill=MUTED)
        ty += 34

        draw.text((bx + 20, ty), meta, font=meta_font, fill=TEAL)
        ty += 36

        for line in wrap(draw, desc, desc_font, inner_w):
            draw.text((bx + 20, ty), line, font=desc_font, fill=INK)
            ty += 28

    y += box_h

    draw_footer_bar(draw, width, height, footer_h)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def get_grc_department_card_image_url(backend_url: str) -> str:
    # _TEMPLATE_VERSION folded into the cache key so a future design
    # change regenerates the image instead of keeping an already-cached
    # file from before the change. No other data varies this card, so
    # in practice this is a single cached file reused forever.
    key = hashlib.sha1(_TEMPLATE_VERSION.encode("utf-8")).hexdigest()[:20]
    filename = f"grcdept_{key}.png"
    path = GENERATED_DIR / filename
    if not path.exists():
        path.write_bytes(render_grc_department_card_image())
    return f"{backend_url}/assets/generated/{filename}"
