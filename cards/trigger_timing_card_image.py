"""
Renders the "When should it fire?" timing-picker screen as a real PNG
-- dark theme (sir's reference), logo+badge, breadcrumb, the
pre-notification status pill, the title, and the three timing option
tiles (Trigger now / Schedule / Surprise window). Same template-code
approach as the other cards, just the one dark-theme card in this set.

The "Trigger now" / "Schedule" / "Surprise window" buttons stay real
Slack buttons underneath this image -- not baked into it, same
reasoning as every other card with a genuine click target.
"""

import hashlib
import io

from PIL import Image, ImageDraw

from .card_image_common import GENERATED_DIR, draw_footer_bar, font, wrap

# Bump this whenever render_trigger_timing_card_image's drawing
# changes -- see get_trigger_timing_card_image_url's cache-key
# comment below.
_TEMPLATE_VERSION = "v3"

_DARK_BG = (20, 20, 20)
_DARK_CARD = (38, 38, 38)
_DARK_BORDER = (58, 58, 58)
_DARK_TEXT = (240, 240, 240)
_DARK_MUTED = (158, 158, 158)
_RED = (211, 30, 40)
_TEAL_BG = (24, 56, 52)
_TEAL_FG = (74, 199, 183)


def _draw_icon(draw: ImageDraw.ImageDraw, x0: int, y0: int, size: int, icon_key: str, color: tuple) -> None:
    cx, cy = x0 + size / 2, y0 + size / 2
    s = size
    w = max(2, int(s * 0.1))
    if icon_key == "now":
        draw.polygon(
            [(cx + s * 0.1, cy - s * 0.3), (cx - s * 0.15, cy + s * 0.05), (cx, cy + s * 0.05),
             (cx - s * 0.1, cy + s * 0.3), (cx + s * 0.18, cy - s * 0.05), (cx + s * 0.02, cy - s * 0.05)],
            fill=color,
        )
    elif icon_key == "sched":
        bw, bh = s * 0.5, s * 0.42
        bx0, by0 = cx - bw / 2, cy - bh / 2 + s * 0.04
        draw.rounded_rectangle([bx0, by0, bx0 + bw, by0 + bh], radius=4, outline=color, width=w)
        draw.line([(bx0, by0 + bh * 0.3), (bx0 + bw, by0 + bh * 0.3)], fill=color, width=max(1, w - 1))
        draw.line([(bx0 + bw * 0.25, by0 - s * 0.06), (bx0 + bw * 0.25, by0 + s * 0.08)], fill=color, width=w)
        draw.line([(bx0 + bw * 0.75, by0 - s * 0.06), (bx0 + bw * 0.75, by0 + s * 0.08)], fill=color, width=w)
    else:  # "surprise" -- a die
        bw = s * 0.46
        bx0, by0 = cx - bw / 2, cy - bw / 2
        draw.rounded_rectangle([bx0, by0, bx0 + bw, by0 + bw], radius=6, outline=color, width=w)
        for dx, dy in ((-0.2, -0.2), (0.2, 0.2), (0, 0)):
            r = bw * 0.08
            draw.ellipse([cx + bw * dx - r, cy + bw * dy - r, cx + bw * dx + r, cy + bw * dy + r], fill=color)


def render_trigger_timing_card_image(breadcrumb_text: str, training_mode: bool) -> bytes:
    width = 1200
    pad = 56
    header_h = 56
    gap = 20
    tile_h = 150
    footer_h = 10

    measure_img = Image.new("RGB", (10, 10))
    measure_draw = ImageDraw.Draw(measure_img)
    crumb_font = font(False, 20)
    crumb_lines = wrap(measure_draw, breadcrumb_text, crumb_font, width - pad * 2 - 260)

    title_h = 56

    height = pad + header_h + len(crumb_lines) * 28 + gap + title_h + gap + tile_h + pad + footer_h

    img = Image.new("RGB", (width, height), _DARK_BG)
    draw = ImageDraw.Draw(img)


    badge_text = "STEP 7 · LAUNCH"
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

    if training_mode:
        pill_text = "Pre-notification sent"
        pill_font = font(True, 15)
        pill_tw = draw.textlength(pill_text, font=pill_font)
        pill_w = pill_tw + 48
        pill_x0, pill_y0 = width - pad - pill_w, pad + header_h
        draw.rounded_rectangle([pill_x0, pill_y0, pill_x0 + pill_w, pill_y0 + 26], radius=13, fill=_TEAL_BG)
        draw.line([(pill_x0 + 14, pill_y0 + 13), (pill_x0 + 18, pill_y0 + 17), (pill_x0 + 25, pill_y0 + 9)], fill=_TEAL_FG, width=2)
        draw.text((pill_x0 + 32, pill_y0 + 3), pill_text, font=pill_font, fill=_TEAL_FG)

    y += gap
    title_font = font(True, 48)
    prefix = "When should it "
    x = pad
    draw.text((x, y), prefix, font=title_font, fill=_DARK_TEXT)
    x += draw.textlength(prefix, font=title_font)
    draw.text((x, y), "fire?", font=title_font, fill=_RED)
    y += title_h + gap

    tiles = [
        ("now", "Trigger now", "Launches immediately — teams are notified in their channel", True),
        ("sched", "Schedule", "Pick a window; participants get a calendar hold", False),
        ("surprise", "Surprise window", "Fires at random within the next 7 days", False),
    ]
    col_gap = 20
    col_w = (width - pad * 2 - col_gap * 2) // 3
    for i, (icon_key, label, desc, highlighted) in enumerate(tiles):
        bx = pad + i * (col_w + col_gap)
        outline_color = _RED if highlighted else _DARK_BORDER
        draw.rounded_rectangle([bx, y, bx + col_w, y + tile_h], radius=14, fill=_DARK_CARD, outline=outline_color, width=2)
        icon_size = 44
        icon_bg = _RED if highlighted else (54, 54, 54)
        icon_fg = "white" if highlighted else _DARK_TEXT
        draw.rounded_rectangle([bx + 18, y + 18, bx + 18 + icon_size, y + 18 + icon_size], radius=10, fill=icon_bg)
        _draw_icon(draw, bx + 18, y + 18, icon_size, icon_key, icon_fg)

        label_y = y + 18 + icon_size + 14
        draw.text((bx + 18, label_y), label, font=font(True, 22), fill=_DARK_TEXT)
        desc_y = label_y + 30
        for line in wrap(draw, desc, font(False, 16), col_w - 36):
            draw.text((bx + 18, desc_y), line, font=font(False, 16), fill=_DARK_MUTED)
            desc_y += 21

    y += tile_h

    draw_footer_bar(draw, width, height, footer_h)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def get_trigger_timing_card_image_url(backend_url: str, breadcrumb_text: str, training_mode: bool) -> str:
    # _TEMPLATE_VERSION + the real data folded into the cache key so a
    # changed drawing or a different scenario both bust the cache
    # instead of silently reusing a stale image.
    key = hashlib.sha1(f"{_TEMPLATE_VERSION}|{breadcrumb_text}|{int(training_mode)}".encode("utf-8")).hexdigest()[:20]
    filename = f"triggertiming_{key}.png"
    path = GENERATED_DIR / filename
    if not path.exists():
        path.write_bytes(render_trigger_timing_card_image(breadcrumb_text, training_mode))
    return f"{backend_url}/assets/generated/{filename}"
