"""
Renders the "The test is running" live-status screen as a real PNG --
dark theme (sir's reference), logo+badge, breadcrumb, the title, the
subtitle, and the three stat tiles (Participants notified / Injects
remaining / Scoring). Same template-code approach as the other cards.

The "Preparedness report" / "Inject a scenario" / "Run another test"
buttons stay real Slack buttons underneath this image -- not baked
into it, same reasoning as every other card with a genuine click
target.
"""

import hashlib
import io

from PIL import Image, ImageDraw

from .card_image_common import GENERATED_DIR, draw_footer_bar, font, wrap

# Bump this whenever render_live_status_card_image's drawing changes --
# see get_live_status_card_image_url's cache-key comment below.
_TEMPLATE_VERSION = "v3"

_DARK_BG = (20, 20, 20)
_DARK_CARD = (38, 38, 38)
_DARK_BORDER = (58, 58, 58)
_DARK_TEXT = (240, 240, 240)
_DARK_MUTED = (158, 158, 158)
_RED = (211, 30, 40)


def render_live_status_card_image(
    breadcrumb_text: str, badge_text: str, title_suffix: str, subtitle: str, participants_text: str, injects_text: str, scoring_text: str
) -> bytes:
    width = 1200
    pad = 56
    header_h = 56
    gap = 20
    title_h = 56
    tile_h = 110
    footer_h = 10

    measure_img = Image.new("RGB", (10, 10))
    measure_draw = ImageDraw.Draw(measure_img)
    crumb_font = font(False, 20)
    crumb_lines = wrap(measure_draw, breadcrumb_text, crumb_font, width - pad * 2)

    subtitle_font = font(False, 22)
    subtitle_lines = wrap(measure_draw, subtitle, subtitle_font, width - pad * 2)

    height = (
        pad + header_h + len(crumb_lines) * 28 + gap + title_h + len(subtitle_lines) * 30
        + gap + tile_h + pad + footer_h
    )

    img = Image.new("RGB", (width, height), _DARK_BG)
    draw = ImageDraw.Draw(img)


    badge_font = font(True, 16)
    badge_tw = draw.textlength(badge_text, font=badge_font)
    badge_w = badge_tw + 56
    badge_x0, badge_y0 = width - pad - badge_w, pad
    draw.rounded_rectangle([badge_x0, badge_y0, width - pad, badge_y0 + 40], radius=20, fill=_RED)
    dot_cy = badge_y0 + 20
    draw.ellipse([badge_x0 + 20, dot_cy - 4, badge_x0 + 28, dot_cy + 4], fill="white")
    draw.text((badge_x0 + 36, badge_y0 + 11), badge_text, font=badge_font, fill="white")

    y = pad + header_h
    for line in crumb_lines:
        draw.text((pad, y), line, font=crumb_font, fill=_DARK_MUTED)
        y += 28
    y += gap

    title_font = font(True, 48)
    prefix = "The test is "
    x = pad
    draw.text((x, y), prefix, font=title_font, fill=_DARK_TEXT)
    x += draw.textlength(prefix, font=title_font)
    draw.text((x, y), title_suffix, font=title_font, fill=_RED)
    y += title_h

    for line in subtitle_lines:
        draw.text((pad, y), line, font=subtitle_font, fill=_DARK_MUTED)
        y += 30
    y += gap

    tiles = [
        ("PARTICIPANTS NOTIFIED", participants_text.split("\n", 1)),
        ("INJECTS REMAINING", injects_text.split("\n", 1)),
        ("SCORING", scoring_text.split("\n", 1)),
    ]
    col_gap = 20
    col_w = (width - pad * 2 - col_gap * 2) // 3
    label_font = font(False, 13)
    value_font = font(True, 32)
    caption_font = font(False, 15)
    for i, (label, parts) in enumerate(tiles):
        value = parts[0]
        caption = parts[1] if len(parts) > 1 else ""
        bx = pad + i * (col_w + col_gap)
        draw.rounded_rectangle([bx, y, bx + col_w, y + tile_h], radius=14, fill=_DARK_CARD, outline=_DARK_BORDER, width=2)
        draw.text((bx + 18, y + 16), label, font=label_font, fill=_DARK_MUTED)
        draw.text((bx + 18, y + 38), value, font=value_font, fill=_DARK_TEXT)
        if caption:
            cy = y + 76
            for line in wrap(draw, caption, caption_font, col_w - 36):
                draw.text((bx + 18, cy), line, font=caption_font, fill=_DARK_MUTED)
                cy += 18

    y += tile_h

    draw_footer_bar(draw, width, height, footer_h)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def get_live_status_card_image_url(
    backend_url: str, breadcrumb_text: str, badge_text: str, title_suffix: str, subtitle: str,
    participants_text: str, injects_text: str, scoring_text: str,
) -> str:
    # _TEMPLATE_VERSION + every piece of real data folded into the
    # cache key so a changed drawing or a changed run both bust the
    # cache instead of silently reusing a stale image.
    key = hashlib.sha1(
        f"{_TEMPLATE_VERSION}|{breadcrumb_text}|{badge_text}|{title_suffix}|{subtitle}|{participants_text}|{injects_text}|{scoring_text}".encode("utf-8")
    ).hexdigest()[:20]
    filename = f"livestatus_{key}.png"
    path = GENERATED_DIR / filename
    if not path.exists():
        path.write_bytes(render_live_status_card_image(breadcrumb_text, badge_text, title_suffix, subtitle, participants_text, injects_text, scoring_text))
    return f"{backend_url}/assets/generated/{filename}"
