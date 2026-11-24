"""
Renders the "Training mode?" trigger screen as a real PNG -- logo+
badge, the breadcrumb, the title, and the two option boxes (Yes ·
Pre-notify / No · Go live). Same template-code approach as the other
cards.

The "Yes -- send pre-notification" / "No -- send test directly"
buttons stay real Slack buttons underneath this image -- not baked
into it, same reasoning as every other card with a genuine click
target.
"""

import hashlib
import io

from PIL import Image, ImageDraw

from .card_image_common import (
    BG, BRAND_RED, CARD_BG, CARD_BORDER, GENERATED_DIR, INK, MUTED,
    draw_footer_bar, font, wrap,
)

# Bump this whenever render_trigger_training_card_image's drawing
# changes -- see get_trigger_training_card_image_url's cache-key
# comment below.
_TEMPLATE_VERSION = "v3"

_RECOMMENDED_BG = (250, 233, 210)
_RECOMMENDED_FG = (184, 120, 40)
_HIGHLIGHT = (214, 97, 23)

_SPEAKER_ICON_BG = (250, 233, 210)
_SPEAKER_ICON_FG = (184, 120, 40)
_SEND_ICON_BG = (26, 26, 26)
_SEND_ICON_FG = (255, 255, 255)


def _draw_speaker_icon(draw: ImageDraw.ImageDraw, x0: int, y0: int, size: int) -> None:
    cx, cy = x0 + size / 2, y0 + size / 2
    s = size
    color = _SPEAKER_ICON_FG
    body_w, body_h = s * 0.22, s * 0.28
    draw.rectangle([cx - s * 0.3, cy - body_h / 2, cx - s * 0.3 + body_w * 0.5, cy + body_h / 2], fill=color)
    draw.polygon(
        [(cx - s * 0.3 + body_w * 0.5, cy - body_h / 2), (cx - s * 0.02, cy - s * 0.26),
         (cx - s * 0.02, cy + s * 0.26), (cx - s * 0.3 + body_w * 0.5, cy + body_h / 2)],
        fill=color,
    )
    w = max(2, int(s * 0.07))
    draw.arc([cx + s * 0.02, cy - s * 0.22, cx + s * 0.34, cy + s * 0.22], start=-55, end=55, fill=color, width=w)
    draw.arc([cx + s * 0.1, cy - s * 0.32, cx + s * 0.44, cy + s * 0.32], start=-50, end=50, fill=color, width=w)


def _draw_send_icon(draw: ImageDraw.ImageDraw, x0: int, y0: int, size: int) -> None:
    cx, cy = x0 + size / 2, y0 + size / 2
    s = size
    draw.polygon(
        [(cx - s * 0.3, cy - s * 0.26), (cx + s * 0.32, cy - s * 0.02), (cx - s * 0.3, cy + s * 0.26),
         (cx - s * 0.12, cy)],
        fill=_SEND_ICON_FG,
    )


def render_trigger_training_card_image(breadcrumb_text: str) -> bytes:
    width = 1200
    pad = 56
    header_h = 56
    crumb_h = 28
    title_h = 56
    gap = 20
    option_h = 160
    footer_h = 10

    measure_img = Image.new("RGB", (10, 10))
    measure_draw = ImageDraw.Draw(measure_img)
    crumb_font = font(False, 20)
    crumb_lines = wrap(measure_draw, breadcrumb_text, crumb_font, width - pad * 2)

    options = [
        (
            "speaker", "RECOMMENDED", "Yes · Pre-notify", "A heads-up message goes out first", True,
        ),
        (
            "send", "", "No · Go live", "No warning — starts immediately", False,
        ),
    ]

    height = pad + header_h + len(crumb_lines) * crumb_h + gap + title_h + 32 + gap + option_h + pad + footer_h

    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)


    badge_text = "STEP 7 · TRIGGER"
    badge_font = font(True, 16)
    badge_tw = draw.textlength(badge_text, font=badge_font)
    badge_w = badge_tw + 56
    badge_x0, badge_y0 = width - pad - badge_w, pad
    draw.rounded_rectangle([badge_x0, badge_y0, width - pad, badge_y0 + 40], radius=20, fill=(252, 225, 225))
    dot_cy = badge_y0 + 20
    draw.ellipse([badge_x0 + 20, dot_cy - 4, badge_x0 + 28, dot_cy + 4], fill=(150, 30, 40))
    draw.text((badge_x0 + 36, badge_y0 + 11), badge_text, font=badge_font, fill=(150, 30, 40))

    y = pad + header_h
    for line in crumb_lines:
        draw.text((pad, y), line, font=crumb_font, fill=MUTED)
        y += crumb_h
    y += gap

    title_font = font(True, 48)
    prefix = "Training "
    suffix = "mode?"
    x = pad
    draw.text((x, y), prefix, font=title_font, fill=INK)
    x += draw.textlength(prefix, font=title_font)
    draw.text((x, y), suffix, font=title_font, fill=BRAND_RED)
    y += title_h
    draw.text((pad, y), "Choose how the team finds out this is starting.", font=font(False, 22), fill=MUTED)
    y += 32 + gap

    col_gap = 24
    col_w = (width - pad * 2 - col_gap) // 2
    for i, (icon_key, tag, label, desc, highlighted) in enumerate(options):
        bx = pad + i * (col_w + col_gap)
        outline_color = _HIGHLIGHT if highlighted else CARD_BORDER
        outline_width = 3 if highlighted else 2
        draw.rounded_rectangle([bx, y, bx + col_w, y + option_h], radius=14, fill=CARD_BG, outline=outline_color, width=outline_width)

        icon_size = 44
        icon_bg = _SPEAKER_ICON_BG if icon_key == "speaker" else _SEND_ICON_BG
        draw.rounded_rectangle([bx + 20, y + 20, bx + 20 + icon_size, y + 20 + icon_size], radius=10, fill=icon_bg)
        if icon_key == "speaker":
            _draw_speaker_icon(draw, bx + 20, y + 20, icon_size)
        else:
            _draw_send_icon(draw, bx + 20, y + 20, icon_size)

        if tag:
            tag_font = font(True, 13)
            tag_tw = draw.textlength(tag, font=tag_font)
            tag_w = tag_tw + 24
            tag_x0 = bx + col_w - 20 - tag_w
            draw.rounded_rectangle([tag_x0, y + 20, tag_x0 + tag_w, y + 20 + 24], radius=12, outline=_RECOMMENDED_FG, width=1, fill=_RECOMMENDED_BG)
            draw.text((tag_x0 + 12, y + 25), tag, font=tag_font, fill=_RECOMMENDED_FG)

        label_y = y + 20 + icon_size + 16
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


def get_trigger_training_card_image_url(backend_url: str, breadcrumb_text: str) -> str:
    # _TEMPLATE_VERSION + the breadcrumb folded into the cache key so a
    # changed drawing or a different scenario both bust the cache
    # instead of silently reusing a stale image.
    key = hashlib.sha1(f"{_TEMPLATE_VERSION}|{breadcrumb_text}".encode("utf-8")).hexdigest()[:20]
    filename = f"triggertraining_{key}.png"
    path = GENERATED_DIR / filename
    if not path.exists():
        path.write_bytes(render_trigger_training_card_image(breadcrumb_text))
    return f"{backend_url}/assets/generated/{filename}"
