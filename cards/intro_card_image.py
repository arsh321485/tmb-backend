"""
Renders sir's "Welcome to TestMyPlan" general orientation design as a
real PNG -- sent on Slack's own "team_join" event, the moment someone
accepts the workspace invite, before any admin has assigned them a
role (cards/intro_card_v2.py). Same template-code approach as the
other cards: mostly-static layout (same 3 feature boxes every time),
only the recipient's name and org actually differ per person.
"""

import hashlib
import io

from PIL import Image, ImageDraw

from .card_image_common import (
    BG, BRAND_RED, CARD_BG, CARD_BORDER, GENERATED_DIR, INK, MUTED, TEAL, TEAL_BG,
    draw_footer_bar, font, wrap,
)

# Bump this whenever render_intro_card_image's drawing changes -- see
# get_intro_card_image_url's cache-key comment below.
_TEMPLATE_VERSION = "v5"

_ICON_BG = (252, 234, 234)
_ICON_FG = (60, 58, 58)

_FEATURES = [
    ("bell", "Drill alerts", "Know the moment a drill starts"),
    ("list", "One card at a time", "Updates and decisions in this chat"),
    ("target", "Answer in chat", "Tap a button — it's logged and timed"),
]


def _draw_feature_icon(draw: ImageDraw.ImageDraw, x0: int, y0: int, size: int, icon_key: str) -> None:
    cx, cy = x0 + size / 2, y0 + size / 2
    s = size
    color = _ICON_FG
    w = max(2, int(s * 0.08))

    if icon_key == "bell":
        draw.pieslice([cx - s * 0.22, cy - s * 0.26, cx + s * 0.22, cy + s * 0.18], 180, 360, fill=color)
        draw.rectangle([cx - s * 0.22, cy - s * 0.04, cx + s * 0.22, cy + s * 0.14], fill=color)
        draw.polygon([(cx - s * 0.26, cy + s * 0.14), (cx + s * 0.26, cy + s * 0.14), (cx + s * 0.16, cy + s * 0.22), (cx - s * 0.16, cy + s * 0.22)], fill=color)
        draw.ellipse([cx - s * 0.05, cy + s * 0.22, cx + s * 0.05, cy + s * 0.32], fill=color)
    elif icon_key == "list":
        for i in range(3):
            ly = cy - s * 0.18 + i * s * 0.18
            draw.ellipse([cx - s * 0.28, ly - w / 2, cx - s * 0.28 + w, ly + w / 2], fill=color)
            draw.line([(cx - s * 0.16, ly), (cx + s * 0.28, ly)], fill=color, width=w)
    else:  # target
        draw.ellipse([cx - s * 0.3, cy - s * 0.3, cx + s * 0.3, cy + s * 0.3], outline=color, width=w)
        draw.ellipse([cx - s * 0.14, cy - s * 0.14, cx + s * 0.14, cy + s * 0.14], outline=color, width=w)
        draw.ellipse([cx - s * 0.04, cy - s * 0.04, cx + s * 0.04, cy + s * 0.04], fill=color)


def render_intro_card_image(recipient_name: str, org_name: str) -> bytes:
    width = 1200
    pad = 56
    header_h = 56
    title_h = 64
    subtitle_h = 64
    gap = 24
    footer_line_h = 50
    footer_h = 10

    subtitle = "Realistic, scenario-based drills that prove your incident plan works — run right here in chat."

    measure_img = Image.new("RGB", (10, 10))
    measure_draw = ImageDraw.Draw(measure_img)
    name_font = font(True, 24)
    desc_font = font(False, 20)
    subtitle_font = font(False, 24)

    cols = 3
    gap_box = 24
    col_w = (width - pad * 2 - gap_box * (cols - 1)) // cols

    subtitle_lines = wrap(measure_draw, subtitle, subtitle_font, width - pad * 2)

    box_h = 0
    for _, name, desc in _FEATURES:
        name_lines = wrap(measure_draw, name, name_font, col_w - 48)
        desc_lines = wrap(measure_draw, desc, desc_font, col_w - 48)
        h = 20 + 56 + 16 + len(name_lines) * 30 + 10 + len(desc_lines) * 27 + 24
        box_h = max(box_h, h)

    height = pad + header_h + title_h + len(subtitle_lines) * 32 + gap + box_h + gap + footer_line_h + pad + footer_h

    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)


    badge_text = "WELCOME"
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
    prefix = "Welcome to "
    x = pad
    draw.text((x, y), prefix, font=title_font, fill=INK)
    x += draw.textlength(prefix, font=title_font)
    draw.text((x, y), "TestMyPlan", font=title_font, fill=BRAND_RED)
    y += title_h

    for line in subtitle_lines:
        draw.text((pad, y), line, font=subtitle_font, fill=MUTED)
        y += 32
    y += gap

    for i, (icon_key, name, desc) in enumerate(_FEATURES):
        bx = pad + i * (col_w + gap_box)
        draw.rounded_rectangle([bx, y, bx + col_w, y + box_h], radius=14, fill=CARD_BG, outline=CARD_BORDER, width=1)
        icon_size = 56
        draw.rounded_rectangle([bx + 20, y + 20, bx + 20 + icon_size, y + 20 + icon_size], radius=14, fill=_ICON_BG)
        _draw_feature_icon(draw, bx + 20, y + 20, icon_size, icon_key)
        ty = y + 20 + icon_size + 16
        name_font_local = font(True, 24)
        for line in wrap(draw, name, name_font_local, col_w - 48):
            draw.text((bx + 20, ty), line, font=name_font_local, fill=INK)
            ty += 30
        ty += 10
        for line in wrap(draw, desc, desc_font, col_w - 48):
            draw.text((bx + 20, ty), line, font=desc_font, fill=MUTED)
            ty += 27
    y += box_h + gap

    draw.line([(pad, y), (width - pad, y)], fill=CARD_BORDER, width=1)
    y += 20
    check_size = 32
    draw.rounded_rectangle([pad, y, pad + check_size, y + check_size], radius=8, fill=TEAL)
    draw.line([(pad + check_size * 0.24, y + check_size * 0.52), (pad + check_size * 0.42, y + check_size * 0.72)], fill=(255, 255, 255), width=3)
    draw.line([(pad + check_size * 0.42, y + check_size * 0.72), (pad + check_size * 0.78, y + check_size * 0.3)], fill=(255, 255, 255), width=3)
    draw.text((pad + check_size + 16, y + 3), "You're all set — no action needed right now", font=font(True, 22), fill=INK)

    draw_footer_bar(draw, width, height, footer_h)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def get_intro_card_image_url(backend_url: str, recipient_name: str, org_name: str) -> str:
    # _TEMPLATE_VERSION folded into the cache key so a future design
    # change regenerates every image instead of keeping someone's
    # already-cached file from before the change.
    key_source = "|".join([_TEMPLATE_VERSION, recipient_name, org_name])
    key = hashlib.sha1(key_source.encode("utf-8")).hexdigest()[:20]
    filename = f"intro_{key}.png"
    path = GENERATED_DIR / filename
    if not path.exists():
        data = render_intro_card_image(recipient_name, org_name)
        path.write_bytes(data)
    return f"{backend_url}/assets/generated/{filename}"
