"""
Renders sir's "You're all set" final-confirmation design as a real PNG
-- same template-image approach as the other role_welcome_v2.py cards.
This one is almost entirely static (same checkmark, same heading, same
subtitle every time) -- only the logged timestamp actually differs per
person, so it's the cheapest of the four to cache: in practice most
people share the same rendered minute and reuse the same file.
"""

import hashlib
import io

from PIL import Image, ImageDraw

from .card_image_common import (
    BG, BRAND_RED, GENERATED_DIR, INK, MUTED, TEAL, TEAL_BG,
    draw_footer_bar, font,
)

# Bump this whenever render_ack_done_card_image's drawing changes --
# see get_ack_done_card_image_url's cache-key comment below.
_TEMPLATE_VERSION = "v9"


def render_ack_done_card_image(logged_at_text: str) -> bytes:
    width = 1200
    pad = 56
    header_h = 56
    icon_size = 150
    content_h = 260
    footer_h = 10

    height = pad + header_h + content_h + pad + footer_h

    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)


    badge_text = "LOGGED"
    badge_font = font(True, 16)
    badge_tw = draw.textlength(badge_text, font=badge_font)
    badge_w = badge_tw + 56
    badge_x0, badge_y0 = width - pad - badge_w, pad
    draw.rounded_rectangle([badge_x0, badge_y0, width - pad, badge_y0 + 40], radius=20, fill=TEAL_BG)
    dot_cy = badge_y0 + 20
    draw.ellipse([badge_x0 + 20, dot_cy - 4, badge_x0 + 28, dot_cy + 4], fill=TEAL)
    draw.text((badge_x0 + 36, badge_y0 + 11), badge_text, font=badge_font, fill=TEAL)

    y = pad + header_h
    icon_x = pad
    icon_y = y + 10
    draw.rounded_rectangle([icon_x, icon_y, icon_x + icon_size, icon_y + icon_size], radius=32, fill=TEAL)
    # Checkmark, drawn as a simple two-segment thick line.
    cx0, cy0 = icon_x + icon_size * 0.28, icon_y + icon_size * 0.52
    cx1, cy1 = icon_x + icon_size * 0.44, icon_y + icon_size * 0.68
    cx2, cy2 = icon_x + icon_size * 0.74, icon_y + icon_size * 0.34
    draw.line([(cx0, cy0), (cx1, cy1)], fill=(255, 255, 255), width=14, joint="curve")
    draw.line([(cx1, cy1), (cx2, cy2)], fill=(255, 255, 255), width=14, joint="curve")

    text_x = icon_x + icon_size + 48
    heading_font = font(True, 54)
    prefix = "You're "
    prefix_w = draw.textlength(prefix, font=heading_font)
    draw.text((text_x, y), prefix, font=heading_font, fill=INK)
    draw.text((text_x + prefix_w, y), "all set", font=heading_font, fill=BRAND_RED)
    draw.text((text_x, y + 78), "Your first task card will arrive here when the test fires.", font=font(False, 26), fill=MUTED)

    # Confirmed live: the clock emoji glyph isn't in Arial, so it
    # rendered as a blank tofu box instead of an icon. A small drawn
    # clock face (circle + two hands) avoids depending on the font
    # having that glyph at all.
    pill_text = f"Logged {logged_at_text}"
    pill_font = font(True, 22)
    pill_tw = draw.textlength(pill_text, font=pill_font)
    clock_d = 20
    pill_w = clock_d + 12 + pill_tw + 48
    pill_y = y + 150
    draw.rounded_rectangle([text_x, pill_y, text_x + pill_w, pill_y + 48], radius=24, fill=TEAL_BG)
    clock_cx, clock_cy = text_x + 24 + clock_d // 2, pill_y + 24
    draw.ellipse([clock_cx - clock_d // 2, clock_cy - clock_d // 2, clock_cx + clock_d // 2, clock_cy + clock_d // 2], outline=TEAL, width=2)
    draw.line([(clock_cx, clock_cy), (clock_cx, clock_cy - 6)], fill=TEAL, width=2)
    draw.line([(clock_cx, clock_cy), (clock_cx + 5, clock_cy + 2)], fill=TEAL, width=2)
    draw.text((text_x + 24 + clock_d + 10, pill_y + 11), pill_text, font=pill_font, fill=TEAL)

    draw_footer_bar(draw, width, height, footer_h)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def get_ack_done_card_image_url(backend_url: str, logged_at_text: str) -> str:
    # _TEMPLATE_VERSION folded into the cache key so a future design
    # change regenerates every image instead of keeping someone's
    # already-cached file from before the change.
    key_source = "|".join([_TEMPLATE_VERSION, logged_at_text])
    key = hashlib.sha1(key_source.encode("utf-8")).hexdigest()[:20]
    filename = f"ackdone_{key}.png"
    path = GENERATED_DIR / filename
    if not path.exists():
        data = render_ack_done_card_image(logged_at_text)
        path.write_bytes(data)
    return f"{backend_url}/assets/generated/{filename}"
