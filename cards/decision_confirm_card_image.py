"""
Renders sir's "Your answer is in" confirmation design as a real PNG --
shown in place of the decision card the instant a responder picks an
option (cards/ai_drill_v2.py's handle_decision). Same template-code
approach as the other cards: the chosen option's own letter/text, the
responder's role, and how long they took are all real data, not fixed
mockup content.
"""

import hashlib
import io

from PIL import Image, ImageDraw

from .card_image_common import (
    BG, BRAND_RED, CARD_BG, CARD_BORDER, GENERATED_DIR, INK, MUTED, TEAL, TEAL_BG,
    draw_footer_bar, font, wrap,
)

# Bump this whenever render_decision_confirm_card_image's drawing
# changes -- see get_decision_confirm_card_image_url's cache-key
# comment below.
_TEMPLATE_VERSION = "v5"


def render_decision_confirm_card_image(letter: str, option_text: str, role: str, time_to_decide: str, next_text: str) -> bytes:
    width = 1200
    pad = 56
    header_h = 56
    title_h = 64
    gap = 24
    option_h_min = 72
    meta_h = 70
    footer_h = 10

    measure_img = Image.new("RGB", (10, 10))
    measure_draw = ImageDraw.Draw(measure_img)
    option_font = font(True, 24)

    badge_size = 40
    option_lines = wrap(measure_draw, option_text, option_font, width - pad * 2 - badge_size - 60)
    option_h = max(option_h_min, 24 + len(option_lines) * 30)

    height = pad + header_h + title_h + gap + option_h + gap + meta_h + pad + footer_h

    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)


    badge_text = "DECISION LOGGED"
    badge_font = font(True, 16)
    badge_tw = draw.textlength(badge_text, font=badge_font)
    badge_w = badge_tw + 56
    badge_x0, badge_y0 = width - pad - badge_w, pad
    draw.rounded_rectangle([badge_x0, badge_y0, width - pad, badge_y0 + 40], radius=20, fill=TEAL_BG)
    dot_cy = badge_y0 + 20
    draw.ellipse([badge_x0 + 20, dot_cy - 4, badge_x0 + 28, dot_cy + 4], fill=TEAL)
    draw.text((badge_x0 + 36, badge_y0 + 11), badge_text, font=badge_font, fill=TEAL)

    y = pad + header_h
    title_font = font(True, 48)
    prefix = "Your answer "
    mid = "is in"
    x = pad
    draw.text((x, y), prefix, font=title_font, fill=INK)
    x += draw.textlength(prefix, font=title_font)
    draw.text((x, y), mid, font=title_font, fill=BRAND_RED)
    y += title_h + gap

    draw.rounded_rectangle([pad, y, width - pad, y + option_h], radius=14, fill=CARD_BG, outline=CARD_BORDER, width=1)
    badge_y = y + (option_h - badge_size) // 2
    draw.rounded_rectangle([pad + 20, badge_y, pad + 20 + badge_size, badge_y + badge_size], radius=8, fill=TEAL)
    lw = draw.textlength(letter, font=font(True, 22))
    draw.text((pad + 20 + (badge_size - lw) / 2, badge_y + 9), letter, font=font(True, 22), fill=(255, 255, 255))
    tx = pad + 20 + badge_size + 20
    ty = y + (option_h - len(option_lines) * 30) // 2
    for line in option_lines:
        draw.text((tx, ty), line, font=option_font, fill=INK)
        ty += 30
    y += option_h + gap

    draw.line([(pad, y), (width - pad, y)], fill=CARD_BORDER, width=1)
    y += 20

    col_w = (width - pad * 2) // 3
    meta_label_font = font(True, 14)
    meta_value_font = font(True, 22)
    for i, (label, value) in enumerate([("ANSWERED AS", role), ("TIME TO DECIDE", time_to_decide), ("NEXT", next_text)]):
        cx = pad + i * col_w
        draw.text((cx, y), label, font=meta_label_font, fill=MUTED)
        vy = y + 24
        for line in wrap(draw, value, meta_value_font, col_w - 24):
            draw.text((cx, vy), line, font=meta_value_font, fill=INK)
            vy += 28

    draw_footer_bar(draw, width, height, footer_h)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def get_decision_confirm_card_image_url(backend_url: str, letter: str, option_text: str, role: str, time_to_decide: str, next_text: str) -> str:
    # _TEMPLATE_VERSION folded into the cache key so a future design
    # change regenerates every image instead of keeping an
    # already-cached file from before the change.
    key_source = "|".join([_TEMPLATE_VERSION, letter, option_text, role, time_to_decide, next_text])
    key = hashlib.sha1(key_source.encode("utf-8")).hexdigest()[:20]
    filename = f"decisionconfirm_{key}.png"
    path = GENERATED_DIR / filename
    if not path.exists():
        data = render_decision_confirm_card_image(letter, option_text, role, time_to_decide, next_text)
        path.write_bytes(data)
    return f"{backend_url}/assets/generated/{filename}"
