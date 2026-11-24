"""
Renders sir's "Welcome, {name}" banner as a real PNG filled in with the
actual person being welcomed and their real team/role. Same
template-code approach as role_card_image.py: one drawing, filled in
by code per person, in well under a second, cached by its own content
under static_assets/generated/.

Sir's rebrand (red/black/yellow "TMP" mark, red timeline, red+yellow
footer bar) -- the earlier teal/round-logo version is gone; this is
now the one live design.
"""

import hashlib
import io

from PIL import Image, ImageDraw

from .card_image_common import (
    BG, BRAND_BLACK, BRAND_RED, CARD_BG, CARD_BORDER, GENERATED_DIR, MUTED, TEAL, TEAL_BG,
    draw_footer_bar, font, wrap,
)

# Bump this whenever render_welcome_card_image's drawing changes -- see
# get_welcome_card_image_url's cache-key comment below.
_TEMPLATE_VERSION = "v22"

_RED = BRAND_RED
_BLACK = BRAND_BLACK

_STEPS = [
    ("01", "Review", "Your role and responsibilities"),
    ("02", "Read", "Each task card as it arrives"),
    ("03", "Respond", "In the card — logged and timed"),
    ("04", "Complete", "Every task before the drill ends"),
]


def render_welcome_card_image(recipient_name: str, badge_label: str, team_role_text: str) -> bytes:
    width = 1200
    pad = 56
    header_h = 56
    name_h = 90
    pill_h = 56
    gap_before_timeline = 50
    timeline_h = 190
    footer_h = 10

    height = pad + header_h + name_h + pill_h + gap_before_timeline + timeline_h + pad + footer_h

    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)

    # Badge pill, top-right -- "RESPONSE TEAM" or "BACKUP". Kept the
    # same teal badge style sir's new design still uses here (unlike
    # the logo/timeline/footer, which moved to red/black/yellow).
    badge_text = badge_label.upper()
    badge_font = font(True, 16)
    badge_tw = draw.textlength(badge_text, font=badge_font)
    badge_w = badge_tw + 56
    badge_x0, badge_y0 = width - pad - badge_w, pad
    draw.rounded_rectangle([badge_x0, badge_y0, width - pad, badge_y0 + 40], radius=20, fill=TEAL_BG)
    dot_cy = badge_y0 + 20
    draw.ellipse([badge_x0 + 20, dot_cy - 4, badge_x0 + 28, dot_cy + 4], fill=TEAL)
    draw.text((badge_x0 + 36, badge_y0 + 11), badge_text, font=badge_font, fill=TEAL)

    y = pad + header_h
    name_font = font(True, 64)
    prefix = "Welcome, "
    prefix_w = draw.textlength(prefix, font=name_font)
    draw.text((pad, y), prefix, font=name_font, fill=_BLACK)
    draw.text((pad + prefix_w, y), recipient_name, font=name_font, fill=_RED)
    y += name_h

    # Team/role pill -- real data, not baked into a picture.
    pill_font = font(True, 24)
    pill_text = team_role_text
    pill_tw = draw.textlength(pill_text, font=pill_font)
    pill_w = pill_tw + 96
    draw.rounded_rectangle([pad, y, pad + pill_w, y + pill_h], radius=28, fill=CARD_BG, outline=CARD_BORDER, width=1)
    # Two-person icon in red, matching the new accent color.
    icon_cy = y + pill_h // 2
    for ox in (pad + 22, pad + 40):
        draw.ellipse([ox, icon_cy - 12, ox + 12, icon_cy], fill=_RED)
        draw.pieslice([ox - 4, icon_cy - 2, ox + 16, icon_cy + 20], 180, 360, fill=_RED)
    draw.text((pad + 66, y + 13), pill_text, font=pill_font, fill=_BLACK)
    y += pill_h + gap_before_timeline

    # Horizontal 4-step timeline -- same fixed content every time
    # (sir's design), only the header above it is per-person. Red dots
    # and numbers now, black line (was teal/gray).
    col_w = (width - pad * 2) // 4
    line_y = y + 8
    draw.line([(pad, line_y), (width - pad, line_y)], fill=_BLACK, width=2)

    num_font = font(True, 26)
    title_font = font(True, 30)
    desc_font = font(False, 20)

    for i, (num, title, desc) in enumerate(_STEPS):
        cx = pad + col_w * i
        draw.ellipse([cx - 7, line_y - 7, cx + 7, line_y + 7], fill=_RED)
        ty = line_y + 28
        draw.text((cx, ty), num, font=num_font, fill=_RED)
        ty += 42
        draw.text((cx, ty), title, font=title_font, fill=_BLACK)
        ty += 44
        for line in wrap(draw, desc, desc_font, col_w - 24):
            draw.text((cx, ty), line, font=desc_font, fill=MUTED)
            ty += 26

    draw_footer_bar(draw, width, height, footer_h)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def get_welcome_card_image_url(backend_url: str, recipient_name: str, badge_label: str, team_role_text: str) -> str:
    # _TEMPLATE_VERSION folded into the cache key so a future design
    # change regenerates every image instead of keeping someone's
    # already-cached file from before the change (same reasoning as
    # role_card_image.py's cache key).
    key_source = "|".join([_TEMPLATE_VERSION, recipient_name, badge_label, team_role_text])
    key = hashlib.sha1(key_source.encode("utf-8")).hexdigest()[:20]
    filename = f"welcome_{key}.png"
    path = GENERATED_DIR / filename
    if not path.exists():
        data = render_welcome_card_image(recipient_name, badge_label, team_role_text)
        path.write_bytes(data)
    return f"{backend_url}/assets/generated/{filename}"
