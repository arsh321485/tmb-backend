"""
Renders the "Draft request received" design as a real PNG -- shown
right after someone asks for a generated draft (confirms the real
org_name/website_url on file and that the request is recorded). Same
template-code approach as the other cards.

The "Check again" button stays a real Slack button underneath this
image -- not baked into it, same reasoning as every other card with a
genuine click target.
"""

import hashlib
import io

from PIL import Image, ImageDraw

from .card_image_common import (
    BG, BRAND_RED, CARD_BG, CARD_BORDER, GENERATED_DIR, INK, MUTED, TEAL,
    draw_footer_bar, font, wrap,
)

# Bump this whenever render_draft_requested_card_image's drawing
# changes -- see get_draft_requested_card_image_url's cache-key
# comment below.
_TEMPLATE_VERSION = "v5"

_ICON_BG = (223, 236, 252)
_ICON_FG = (40, 80, 150)


def render_draft_requested_card_image(org_name: str, website_url: str) -> bytes:
    width = 1200
    pad = 56
    header_h = 56
    title_h = 64
    gap = 20
    meta_h = 32
    footer_h = 10

    measure_img = Image.new("RGB", (10, 10))
    measure_draw = ImageDraw.Draw(measure_img)
    title_font = font(True, 40)
    prefix = "Draft request received for "
    title_lines_full = wrap(measure_draw, prefix + org_name + ".", title_font, width - pad * 2)

    status_text = "Researching now — usually takes 2-4 minutes. This screen updates itself automatically when it's ready."
    status_font = font(False, 22)
    status_lines = wrap(measure_draw, status_text, status_font, width - pad * 2 - 20 - 56)

    height = pad + header_h + len(title_lines_full) * 48 + gap + meta_h + gap + max(56, len(status_lines) * 28 + 20) + pad + footer_h

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
    # "Draft request received for {org_name}." -- org name in red, same
    # two-tone heading style as the other cards.
    prefix_text = "Draft request received for "
    x, line_y = pad, y
    words = prefix_text.split(" ")
    draw.text((x, line_y), prefix_text, font=title_font, fill=INK)
    x += draw.textlength(prefix_text, font=title_font)
    org_lines = wrap(draw, org_name + ".", title_font, width - pad - x)
    if org_lines:
        draw.text((x, line_y), org_lines[0], font=title_font, fill=BRAND_RED)
        line_y += 48
        for extra in org_lines[1:]:
            draw.text((pad, line_y), extra, font=title_font, fill=BRAND_RED)
            line_y += 48
    y = line_y + gap

    globe_r = 11
    draw.ellipse([pad, y - globe_r + 10, pad + globe_r * 2, y + globe_r + 10], outline=TEAL, width=2)
    draw.line([(pad, y + 10), (pad + globe_r * 2, y + 10)], fill=TEAL, width=2)
    draw.ellipse([pad + globe_r * 0.5, y - globe_r + 10, pad + globe_r * 1.5, y + globe_r + 10], outline=TEAL, width=2)
    meta_font = font(False, 22)
    draw.text((pad + 32, y), f"Website on file: {website_url}", font=meta_font, fill=MUTED)
    y += meta_h + gap

    icon_size = 56
    draw.rounded_rectangle([pad, y, pad + icon_size, y + icon_size], radius=12, fill=_ICON_BG)
    draw.ellipse([pad + 14, y + 14, pad + icon_size - 14, y + icon_size - 14], outline=_ICON_FG, width=3)
    draw.line([(pad + icon_size / 2, y + 16), (pad + icon_size / 2, y + icon_size / 2)], fill=_ICON_FG, width=3)
    draw.line([(pad + icon_size / 2, y + icon_size / 2), (pad + icon_size / 2 + 10, y + icon_size / 2 + 6)], fill=_ICON_FG, width=3)
    ty = y + (max(56, len(status_lines) * 28 + 20) - len(status_lines) * 28) // 2
    for line in status_lines:
        draw.text((pad + icon_size + 20, ty), line, font=status_font, fill=MUTED)
        ty += 28

    draw_footer_bar(draw, width, height, footer_h)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def get_draft_requested_card_image_url(backend_url: str, org_name: str, website_url: str) -> str:
    # _TEMPLATE_VERSION folded into the cache key so a future design
    # change regenerates every image instead of keeping an
    # already-cached file from before the change.
    key = hashlib.sha1(f"{_TEMPLATE_VERSION}|{org_name}|{website_url}".encode("utf-8")).hexdigest()[:20]
    filename = f"draftreq_{key}.png"
    path = GENERATED_DIR / filename
    if not path.exists():
        path.write_bytes(render_draft_requested_card_image(org_name, website_url))
    return f"{backend_url}/assets/generated/{filename}"
