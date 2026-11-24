"""
Renders sir's admin-side "Welcome to TestMyPlan" design as a real PNG
-- the first screen of the command-center wizard, posted when the app
is installed (cards/onboarding_v2.py) and shown again on the Welcome
nav tab. Same template-code approach as the other cards: the real
installer's name is the only thing that actually varies per
workspace -- the 4-step overview is identical for everyone.
"""

import hashlib
import io

from PIL import Image, ImageDraw

from .card_image_common import (
    BG, BRAND_RED, GENERATED_DIR, INK, MUTED, TEAL, TEAL_BG,
    draw_footer_bar, font, wrap,
)

# Bump this whenever render_admin_welcome_card_image's drawing changes
# -- see get_admin_welcome_card_image_url's cache-key comment below.
_TEMPLATE_VERSION = "v7"

_STEPS = [
    ("01", "Select modules", "Cybersecurity, Privacy and more"),
    ("02", "Upload your BCP", "We extract RTOs and critical services"),
    ("03", "Staff teams", "A primary and backup for every role"),
    ("04", "Trigger a drill", "Now, scheduled, or as a surprise"),
]


def render_admin_welcome_card_image(user_name: str) -> bytes:
    width = 1200
    pad = 56
    header_h = 56
    title_h = 64
    subtitle_h = 64
    pill_h = 48
    gap_before_timeline = 50
    timeline_h = 190
    footer_h = 10

    subtitle = "Build and run realistic incident response drills — right inside your workspace."

    measure_img = Image.new("RGB", (10, 10))
    measure_draw = ImageDraw.Draw(measure_img)
    subtitle_font = font(False, 24)
    subtitle_lines = wrap(measure_draw, subtitle, subtitle_font, width - pad * 2)

    height = pad + header_h + title_h + len(subtitle_lines) * 32 + 16 + pill_h + gap_before_timeline + timeline_h + pad + footer_h

    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)

    badge_text = "ADMIN SETUP"
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
    prefix = "Welcome to TestMyPlan, "
    x = pad
    draw.text((x, y), prefix, font=title_font, fill=INK)
    x += draw.textlength(prefix, font=title_font)
    draw.text((x, y), user_name, font=title_font, fill=BRAND_RED)
    y += title_h

    for line in subtitle_lines:
        draw.text((pad, y), line, font=subtitle_font, fill=MUTED)
        y += 32
    y += 16

    pill_text = "Connected · Workspace ready"
    pill_font = font(True, 22)
    pill_tw = draw.textlength(pill_text, font=pill_font)
    pill_w = pill_tw + 72
    draw.rounded_rectangle([pad, y, pad + pill_w, y + pill_h], radius=24, fill=TEAL_BG)
    check_size = 18
    ccx, ccy = pad + 24, y + pill_h // 2
    draw.line([(ccx - 5, ccy), (ccx - 1, ccy + 5)], fill=TEAL, width=3)
    draw.line([(ccx - 1, ccy + 5), (ccx + 7, ccy - 6)], fill=TEAL, width=3)
    draw.text((pad + 40, y + 12), pill_text, font=pill_font, fill=TEAL)
    y += pill_h + gap_before_timeline

    col_w = (width - pad * 2) // 4
    line_y = y + 8
    draw.line([(pad, line_y), (width - pad, line_y)], fill=INK, width=2)

    num_font = font(True, 26)
    title_font2 = font(True, 30)
    desc_font = font(False, 20)

    for i, (num, step_title, desc) in enumerate(_STEPS):
        cx = pad + col_w * i
        draw.ellipse([cx - 7, line_y - 7, cx + 7, line_y + 7], fill=BRAND_RED)
        ty = line_y + 28
        draw.text((cx, ty), num, font=num_font, fill=BRAND_RED)
        ty += 42
        for line in wrap(draw, step_title, title_font2, col_w - 24):
            draw.text((cx, ty), line, font=title_font2, fill=INK)
            ty += 36
        ty += 6
        for line in wrap(draw, desc, desc_font, col_w - 24):
            draw.text((cx, ty), line, font=desc_font, fill=MUTED)
            ty += 26

    draw_footer_bar(draw, width, height, footer_h)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def get_admin_welcome_card_image_url(backend_url: str, user_name: str) -> str:
    # _TEMPLATE_VERSION folded into the cache key so a future design
    # change regenerates every image instead of keeping an
    # already-cached file from before the change.
    key_source = "|".join([_TEMPLATE_VERSION, user_name])
    key = hashlib.sha1(key_source.encode("utf-8")).hexdigest()[:20]
    filename = f"adminwelcome_{key}.png"
    path = GENERATED_DIR / filename
    if not path.exists():
        data = render_admin_welcome_card_image(user_name)
        path.write_bytes(data)
    return f"{backend_url}/assets/generated/{filename}"
