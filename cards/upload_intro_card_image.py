"""
Renders sir's "Upload & analyze your BIA / BCP" prompt design as a
real PNG -- the first thing shown on this step, before any upload
instructions (cards/bia_upload_v2_data.py's build_bia_question_card).
Entirely static content (same for every workspace) except the step
badge style, so this is the simplest of the template cards -- no
per-person or per-org data at all.

The "Yes, I have it" / "Not yet" buttons stay real Slack buttons
underneath this image -- not baked into it, same reasoning as every
other card with a genuine click target.
"""

import hashlib
import io

from PIL import Image, ImageDraw

from .card_image_common import (
    BG, BRAND_RED, CARD_BG, CARD_BORDER, GENERATED_DIR, INK, MUTED, TEAL, TEAL_BG,
    draw_footer_bar, font, wrap,
)

# Bump this whenever render_upload_intro_card_image's drawing changes
# -- see get_upload_intro_card_image_url's cache-key comment below.
_TEMPLATE_VERSION = "v6"

_DOC_ICON_FG = TEAL
_DOC_ICON_BG = TEAL_BG
_LIST_ICON_BG = (26, 26, 26)
_LIST_ICON_FG = (255, 255, 255)
_HIGHLIGHT = (214, 97, 23)


def _draw_doc_icon(draw: ImageDraw.ImageDraw, x0: int, y0: int, size: int) -> None:
    cx, cy = x0 + size / 2, y0 + size / 2
    s = size
    w = max(2, int(s * 0.07))
    doc_w, doc_h = s * 0.42, s * 0.56
    dx0, dy0 = cx - doc_w / 2, cy - doc_h / 2
    fold = doc_w * 0.3
    draw.polygon(
        [(dx0, dy0), (dx0 + doc_w - fold, dy0), (dx0 + doc_w, dy0 + fold),
         (dx0 + doc_w, dy0 + doc_h), (dx0, dy0 + doc_h)],
        outline=_DOC_ICON_FG, width=w,
    )
    for i in range(3):
        ly = dy0 + doc_h * 0.45 + i * doc_h * 0.18
        draw.line([(dx0 + doc_w * 0.18, ly), (dx0 + doc_w * 0.82, ly)], fill=_DOC_ICON_FG, width=max(2, w - 1))


def _draw_list_icon(draw: ImageDraw.ImageDraw, x0: int, y0: int, size: int) -> None:
    cx, cy = x0 + size / 2, y0 + size / 2
    s = size
    line_w = max(2, int(s * 0.09))
    list_w = s * 0.46
    lx0 = cx - list_w / 2
    for i in range(3):
        ly = cy - s * 0.18 + i * s * 0.18
        draw.ellipse([lx0, ly - 2, lx0 + 4, ly + 2], fill=_LIST_ICON_FG)
        draw.line([(lx0 + 10, ly), (lx0 + list_w, ly)], fill=_LIST_ICON_FG, width=line_w)


def render_upload_intro_card_image() -> bytes:
    width = 1200
    pad = 56
    header_h = 56
    title_h = 64
    gap = 24
    heading_h = 40
    option_h = 150
    footer_h = 10

    subtitle = "We'll extract your RTOs, critical services, and build your threat landscape straight from your real document."

    measure_img = Image.new("RGB", (10, 10))
    measure_draw = ImageDraw.Draw(measure_img)
    subtitle_font = font(False, 24)
    subtitle_lines = wrap(measure_draw, subtitle, subtitle_font, width - pad * 2)

    height = pad + header_h + title_h + len(subtitle_lines) * 32 + gap + heading_h + option_h + pad + footer_h

    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)


    badge_text = "STEP 3 · UPLOAD"
    badge_font = font(True, 16)
    badge_tw = draw.textlength(badge_text, font=badge_font)
    badge_w = badge_tw + 56
    badge_x0, badge_y0 = width - pad - badge_w, pad
    draw.rounded_rectangle([badge_x0, badge_y0, width - pad, badge_y0 + 40], radius=20, outline=CARD_BORDER, width=2)
    dot_cy = badge_y0 + 20
    draw.ellipse([badge_x0 + 20, dot_cy - 4, badge_x0 + 28, dot_cy + 4], fill=INK)
    draw.text((badge_x0 + 36, badge_y0 + 11), badge_text, font=badge_font, fill=INK)

    y = pad + header_h
    title_font = font(True, 48)
    prefix = "Upload & analyze your "
    x = pad
    draw.text((x, y), prefix, font=title_font, fill=INK)
    x += draw.textlength(prefix, font=title_font)
    draw.text((x, y), "BIA / BCP", font=title_font, fill=BRAND_RED)
    y += title_h

    for line in subtitle_lines:
        draw.text((pad, y), line, font=subtitle_font, fill=MUTED)
        y += 32
    y += gap

    draw.text((pad, y), "Do you already have one ready?", font=font(True, 28), fill=INK)
    y += heading_h

    col_gap = 24
    col_w = (width - pad * 2 - col_gap) // 2
    options = [
        (
            pad, _DOC_ICON_BG, _draw_doc_icon, "Yes, I have it",
            "Send it to the app — we read it in 1-3 minutes", True,
        ),
        (
            pad + col_w + col_gap, _LIST_ICON_BG, _draw_list_icon, "Not yet",
            "We'll research a draft BIA for you to confirm", False,
        ),
    ]
    for bx, icon_bg, icon_fn, label, desc, highlighted in options:
        outline_color = _HIGHLIGHT if highlighted else CARD_BORDER
        outline_width = 3 if highlighted else 2
        draw.rounded_rectangle([bx, y, bx + col_w, y + option_h], radius=14, fill=CARD_BG, outline=outline_color, width=outline_width)
        icon_size = 44
        icon_x, icon_y = bx + 20, y + 20
        draw.rounded_rectangle([icon_x, icon_y, icon_x + icon_size, icon_y + icon_size], radius=10, fill=icon_bg)
        icon_fn(draw, icon_x, icon_y, icon_size)

        label_y = icon_y + icon_size + 16
        draw.text((bx + 20, label_y), label, font=font(True, 24), fill=INK)
        desc_y = label_y + 32
        for line in wrap(draw, desc, font(False, 18), col_w - 40):
            draw.text((bx + 20, desc_y), line, font=font(False, 18), fill=MUTED)
            desc_y += 24

    y += option_h

    draw_footer_bar(draw, width, height, footer_h)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def get_upload_intro_card_image_url(backend_url: str) -> str:
    # _TEMPLATE_VERSION folded into the cache key so a future design
    # change regenerates the image instead of keeping an already-cached
    # file from before the change. No other data varies this card at
    # all, so in practice this is a single cached file reused forever.
    key = hashlib.sha1(_TEMPLATE_VERSION.encode("utf-8")).hexdigest()[:20]
    filename = f"uploadintro_{key}.png"
    path = GENERATED_DIR / filename
    if not path.exists():
        path.write_bytes(render_upload_intro_card_image())
    return f"{backend_url}/assets/generated/{filename}"
