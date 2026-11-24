"""
Renders sir's "No file uploaded yet" upload-instructions design as a
real PNG -- header, status pill, the "Send it to the app, not a
person" headline, a 3-step timeline (Open the DM / Attach your file /
We'll take it from here), and the accepted file-type chips. Same
template-code approach as the other cards.

The refresh/auto-update tip line moved OUT of this image and into a
real Slack context block underneath it (cards/bia_upload_v2_data.py) --
sir's reference design shows it below the real buttons, outside this
card's own border.

The "Open DM with TestMyPlan" (a real deep LINK, not just an action)
and "Check again" buttons stay real Slack buttons underneath this
image -- not baked into it, same reasoning as every other card with a
genuine click target.
"""

import hashlib
import io

from PIL import Image, ImageDraw

from .card_image_common import (
    BG, BRAND_RED, CARD_BORDER, GENERATED_DIR, INK, MUTED,
    draw_footer_bar, font, wrap,
)

# Bump this whenever render_upload_status_card_image's drawing changes
# -- see get_upload_status_card_image_url's cache-key comment below.
_TEMPLATE_VERSION = "v6"

_FILETYPE_BG = (223, 236, 252)
_FILETYPE_FG = (40, 80, 150)

_STEPS = [
    ("01", "Open the DM", "Tap \"Open DM with TestMyPlan\" below"),
    ("02", "Attach your file", "Drop your BIA or BCP into that chat"),
    ("03", "We'll take it from here", "This card updates itself in 1-3 minutes"),
]


def _draw_file_chip(draw: ImageDraw.ImageDraw, x: int, y: int, label: str) -> int:
    """Draws a small rounded file-type chip at (x, y); returns its
    right edge x so the caller can place the next one after it."""
    chip_font = font(True, 18)
    tw = draw.textlength(label, font=chip_font)
    chip_w = tw + 44
    chip_h = 34
    draw.rounded_rectangle([x, y, x + chip_w, y + chip_h], radius=8, fill=_FILETYPE_BG)
    draw.rectangle([x + 12, y + 8, x + 22, y + 26], outline=_FILETYPE_FG, width=2)
    draw.text((x + 32, y + 7), label, font=chip_font, fill=_FILETYPE_FG)
    return x + chip_w


def render_upload_status_card_image() -> bytes:
    width = 1200
    pad = 56
    header_h = 56
    status_h = 36
    gap = 24
    timeline_h = 140
    chips_h = 34
    footer_h = 10

    title_font = font(True, 48)

    height = pad + header_h + status_h + gap + 56 + gap + timeline_h + gap + chips_h + pad + footer_h

    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)


    # Filled pink badge, matching the other Step 3 screens' style.
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
    # Status pill (filled pink, matching the badge's color language) --
    # replaces the old plain gray-outlined circle + text.
    status_text = "No file uploaded yet"
    status_font = font(True, 20)
    status_tw = draw.textlength(status_text, font=status_font)
    status_pill_w = status_tw + 56
    draw.rounded_rectangle([pad, y, pad + status_pill_w, y + status_h], radius=18, fill=(252, 225, 225))
    dot_cy2 = y + status_h / 2
    draw.ellipse([pad + 18, dot_cy2 - 5, pad + 28, dot_cy2 + 5], outline=(150, 30, 40), width=2)
    draw.text((pad + 38, y + 8), status_text, font=status_font, fill=(150, 30, 40))
    y += status_h + gap

    # "Send it to the app, not a person" -- "app" in red.
    prefix, redword, suffix = "Send it to the ", "app", ", not a person"
    x = pad
    draw.text((x, y), prefix, font=title_font, fill=INK)
    x += draw.textlength(prefix, font=title_font)
    draw.text((x, y), redword, font=title_font, fill=BRAND_RED)
    x += draw.textlength(redword, font=title_font)
    draw.text((x, y), suffix, font=title_font, fill=INK)
    y += 56 + gap

    col_w = (width - pad * 2) // 3
    line_y = y + 8
    draw.line([(pad, line_y), (width - pad, line_y)], fill=INK, width=2)

    num_font = font(True, 26)
    step_title_font = font(True, 24)
    step_desc_font = font(False, 18)
    for i, (num, step_title, desc) in enumerate(_STEPS):
        cx = pad + col_w * i
        draw.ellipse([cx - 7, line_y - 7, cx + 7, line_y + 7], fill=BRAND_RED)
        ty = line_y + 28
        draw.text((cx, ty), num, font=num_font, fill=BRAND_RED)
        ty += 38
        for line in wrap(draw, step_title, step_title_font, col_w - 24):
            draw.text((cx, ty), line, font=step_title_font, fill=INK)
            ty += 30
        ty += 4
        for line in wrap(draw, desc, step_desc_font, col_w - 24):
            draw.text((cx, ty), line, font=step_desc_font, fill=MUTED)
            ty += 24
    y += timeline_h + gap

    draw.line([(pad, y - 8), (width - pad, y - 8)], fill=CARD_BORDER, width=1)

    cx = pad
    for label in ("DOCX", "PDF", "XLSX"):
        cx = _draw_file_chip(draw, cx, y, label) + 16
    draw.text((cx + 8, y + 7), "Accepted formats", font=font(False, 18), fill=MUTED)

    draw_footer_bar(draw, width, height, footer_h)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def get_upload_status_card_image_url(backend_url: str) -> str:
    # _TEMPLATE_VERSION folded into the cache key so a future design
    # change regenerates the image instead of keeping an already-cached
    # file from before the change. No other data varies this card, so
    # in practice this is a single cached file reused forever.
    key = hashlib.sha1(_TEMPLATE_VERSION.encode("utf-8")).hexdigest()[:20]
    filename = f"uploadstatus_{key}.png"
    path = GENERATED_DIR / filename
    if not path.exists():
        path.write_bytes(render_upload_status_card_image())
    return f"{backend_url}/assets/generated/{filename}"
