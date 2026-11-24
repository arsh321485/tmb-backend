"""
Renders sir's "Before it's tested" awareness design as a real PNG --
sent to every staffed team member right before an incident-wide
scenario is generated (cards/incident_test_v2.py's send_awareness_dms).
Same template-code approach as the other cards: one drawing, filled in
with the real incident name and real causes, in well under a second.

Icons are drawn with simple shapes (lock, eye, email, key, warning,
people, phone, folder), not emoji glyphs -- confirmed in an earlier
card (the clock emoji) that Arial doesn't have every emoji glyph, so
it rendered as a blank box instead of an icon.
"""

import hashlib
import io

from PIL import Image, ImageDraw

from .card_image_common import (
    BG, BRAND_RED, CARD_BG, CARD_BORDER, GENERATED_DIR, INK, MUTED,
    draw_footer_bar, font, wrap,
)

# Bump this whenever render_awareness_card_image's drawing changes --
# see get_awareness_card_image_url's cache-key comment below.
_TEMPLATE_VERSION = "v7"

_BADGE_BG = (247, 231, 210)
_BADGE_BORDER = (224, 189, 135)
_BADGE_FG = (166, 100, 30)
_ICON_BG = (247, 231, 210)
_ICON_FG = (166, 100, 30)

# Same keyword-matching spirit as cause_awareness_modal_v2._icon_for,
# but mapped to one of THIS file's own drawn icon shapes instead of a
# Slack emoji name -- checked in order, first match wins.
_ICON_KEYWORDS = (
    (("privileg", "permission", "over-permission", "excess access"), "lock"),
    (("audit", "visibility", "monitor", "detect", "oversight"), "eye"),
    (("phish", "email", "link"), "email"),
    (("api", "key", "token", "credential", "password", "secret"), "key"),
    (("rdp", "vpn", "remote", "access", "login"), "lock"),
    (("mfa", "authentication", "2fa"), "key"),
    (("vendor", "third-party", "third party", "supplier", "partner"), "people"),
    (("device", "laptop", "phone", "mobile"), "phone"),
    (("misconfig", "config", "scope", "bucket"), "warning"),
    (("insider", "employee", "staff", "leaver"), "people"),
    (("data", "exfilt", "leak", "share"), "folder"),
)

_EMOJI_TO_ICON = {
    ":email:": "email", ":iphone:": "phone", ":warning:": "warning",
    ":handshake:": "people", ":busts_in_silhouette:": "people",
    ":key:": "key", ":closed_lock_with_key:": "lock", ":bell:": "key",
    ":bust_in_silhouette:": "people", ":open_file_folder:": "folder",
}


def icon_key_for(cause_name: str, fixed_emoji: str = "") -> str:
    """Picks which of this file's drawn icon shapes fits a cause, from
    its fixed CAUSE_AWARENESS emoji if it has one, else by keyword."""
    if fixed_emoji and fixed_emoji in _EMOJI_TO_ICON:
        return _EMOJI_TO_ICON[fixed_emoji]
    haystack = cause_name.lower()
    for keywords, icon_key in _ICON_KEYWORDS:
        if any(kw in haystack for kw in keywords):
            return icon_key
    return "warning"


def _draw_icon(draw: ImageDraw.ImageDraw, x0: int, y0: int, size: int, icon_key: str) -> None:
    cx, cy = x0 + size / 2, y0 + size / 2
    s = size
    color = _ICON_FG
    w = max(2, int(s * 0.09))

    if icon_key == "lock":
        body_w, body_h = s * 0.46, s * 0.34
        bx0, by0 = cx - body_w / 2, cy - body_h / 2 + s * 0.1
        shackle_w = max(3, int(s * 0.065))
        shackle_r = body_w * 0.34
        shackle_cy = by0
        # Shackle: a thick top-half ring (outer pieslice, minus an
        # inner pieslice of the icon-background color), plus two short
        # legs running down into the body -- pieslice fills solidly at
        # any size, unlike Pillow's `arc`, which stayed hairline-thin
        # here regardless of the `width` argument.
        draw.pieslice([cx - shackle_r, shackle_cy - shackle_r, cx + shackle_r, shackle_cy + shackle_r], 180, 360, fill=color)
        inner_r = shackle_r - shackle_w
        draw.pieslice([cx - inner_r, shackle_cy - inner_r, cx + inner_r, shackle_cy + inner_r], 180, 360, fill=_ICON_BG)
        draw.rectangle([cx - shackle_r, shackle_cy, cx - shackle_r + shackle_w, by0], fill=color)
        draw.rectangle([cx + shackle_r - shackle_w, shackle_cy, cx + shackle_r, by0], fill=color)
        draw.rounded_rectangle([bx0, by0, bx0 + body_w, by0 + body_h], radius=int(s * 0.06), fill=color)
    elif icon_key == "eye":
        draw.ellipse([cx - s * 0.32, cy - s * 0.18, cx + s * 0.32, cy + s * 0.18], outline=color, width=w)
        draw.ellipse([cx - s * 0.08, cy - s * 0.08, cx + s * 0.08, cy + s * 0.08], fill=color)
    elif icon_key == "email":
        bx0, by0, bx1, by1 = cx - s * 0.34, cy - s * 0.22, cx + s * 0.34, cy + s * 0.22
        draw.rounded_rectangle([bx0, by0, bx1, by1], radius=int(s * 0.05), outline=color, width=w)
        draw.line([(bx0, by0), (cx, cy + s * 0.06), (bx1, by0)], fill=color, width=w, joint="curve")
    elif icon_key == "key":
        draw.ellipse([cx - s * 0.3, cy - s * 0.28, cx, cy + s * 0.02], outline=color, width=w)
        draw.line([(cx - s * 0.02, cy - s * 0.1), (cx + s * 0.32, cy + s * 0.22)], fill=color, width=w)
        draw.line([(cx + s * 0.18, cy + s * 0.08), (cx + s * 0.18, cy + s * 0.2)], fill=color, width=w)
    elif icon_key == "warning":
        draw.polygon([(cx, cy - s * 0.32), (cx + s * 0.32, cy + s * 0.24), (cx - s * 0.32, cy + s * 0.24)], outline=color, width=w)
        draw.line([(cx, cy - s * 0.08), (cx, cy + s * 0.06)], fill=color, width=w)
        draw.ellipse([cx - w / 2, cy + s * 0.14, cx + w / 2, cy + s * 0.14 + w], fill=color)
    elif icon_key == "people":
        for ox in (cx - s * 0.16, cx + s * 0.1):
            draw.ellipse([ox, cy - s * 0.26, ox + s * 0.18, cy - s * 0.08], fill=color)
            draw.pieslice([ox - s * 0.05, cy - s * 0.1, ox + s * 0.23, cy + s * 0.26], 180, 360, fill=color)
    elif icon_key == "phone":
        draw.rounded_rectangle([cx - s * 0.18, cy - s * 0.32, cx + s * 0.18, cy + s * 0.32], radius=int(s * 0.06), outline=color, width=w)
        draw.ellipse([cx - w, cy + s * 0.22, cx + w, cy + s * 0.22 + 2 * w], fill=color)
    elif icon_key == "folder":
        draw.polygon([(cx - s * 0.32, cy - s * 0.12), (cx - s * 0.12, cy - s * 0.12), (cx - s * 0.04, cy - s * 0.2), (cx + s * 0.32, cy - s * 0.2), (cx + s * 0.32, cy - s * 0.12)], fill=color)
        draw.rectangle([cx - s * 0.32, cy - s * 0.12, cx + s * 0.32, cy + s * 0.22], fill=color)
    else:  # shield
        draw.polygon(
            [(cx, cy - s * 0.32), (cx + s * 0.28, cy - s * 0.2), (cx + s * 0.28, cy + s * 0.06),
             (cx, cy + s * 0.32), (cx - s * 0.28, cy + s * 0.06), (cx - s * 0.28, cy - s * 0.2)],
            outline=color, width=w,
        )


def render_awareness_card_image(incident_name: str, causes: list[tuple[str, str, str]]) -> bytes:
    """
    causes: [(cause_name, description, icon_key), ...]
    """
    width = 1200
    pad = 56
    header_h = 56
    kicker_h = 30
    title_h = 64
    subtitle_h = 48
    gap = 24
    footer_line_h = 50
    footer_h = 10

    cols = 2
    col_w = (width - pad * 2 - gap) // cols
    rows = (len(causes) + cols - 1) // cols

    measure_img = Image.new("RGB", (10, 10))
    measure_draw = ImageDraw.Draw(measure_img)
    name_font = font(True, 24)
    desc_font = font(False, 20)

    row_heights: list[int] = []
    for r in range(rows):
        chunk = causes[r * cols:(r + 1) * cols]
        max_h = 0
        for name, desc, _ in chunk:
            name_lines = wrap(measure_draw, name, name_font, col_w - 48)
            desc_lines = wrap(measure_draw, desc, desc_font, col_w - 48)
            # Confirmed live: this left out the icon's own space (20px
            # top padding + 56px icon + 16px gap before the name even
            # starts), so the box came out too short and the
            # description text ran past the box's own bottom edge.
            h = 20 + 56 + 16 + len(name_lines) * 30 + 10 + len(desc_lines) * 27 + 24
            max_h = max(max_h, h)
        row_heights.append(max_h)

    boxes_h = sum(row_heights) + gap * max(0, rows - 1)
    height = pad + header_h + kicker_h + title_h + subtitle_h + gap + boxes_h + gap + footer_line_h + pad + footer_h

    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)


    badge_text = "AWARENESS"
    badge_font = font(True, 16)
    badge_tw = draw.textlength(badge_text, font=badge_font)
    badge_w = badge_tw + 56
    badge_x0, badge_y0 = width - pad - badge_w, pad
    draw.rounded_rectangle([badge_x0, badge_y0, width - pad, badge_y0 + 40], radius=20, fill=_BADGE_BG, outline=_BADGE_BORDER, width=1)
    dot_cy = badge_y0 + 20
    draw.ellipse([badge_x0 + 20, dot_cy - 4, badge_x0 + 28, dot_cy + 4], fill=_BADGE_FG)
    draw.text((badge_x0 + 36, badge_y0 + 11), badge_text, font=badge_font, fill=_BADGE_FG)

    y = pad + header_h
    draw.text((pad, y), "BEFORE IT'S TESTED", font=font(True, 16), fill=BRAND_RED)
    y += kicker_h
    draw.text((pad, y), incident_name, font=font(True, 48), fill=INK)
    y += title_h
    draw.text((pad, y), "Here's how it can happen.", font=font(False, 24), fill=MUTED)
    y += subtitle_h + gap

    for r in range(rows):
        chunk = causes[r * cols:(r + 1) * cols]
        rh = row_heights[r]
        for i, (name, desc, icon_key) in enumerate(chunk):
            bx = pad + i * (col_w + gap)
            draw.rounded_rectangle([bx, y, bx + col_w, y + rh], radius=14, fill=CARD_BG, outline=CARD_BORDER, width=1)
            icon_size = 56
            draw.rounded_rectangle([bx + 20, y + 20, bx + 20 + icon_size, y + 20 + icon_size], radius=14, fill=_ICON_BG)
            _draw_icon(draw, bx + 20, y + 20, icon_size, icon_key)
            ty = y + 20 + icon_size + 16
            for line in wrap(draw, name, name_font, col_w - 48):
                draw.text((bx + 20, ty), line, font=name_font, fill=INK)
                ty += 30
            ty += 10
            for line in wrap(draw, desc, desc_font, col_w - 48):
                draw.text((bx + 20, ty), line, font=desc_font, fill=MUTED)
                ty += 27
        y += rh + gap

    y += 0
    draw.line([(pad, y), (width - pad, y)], fill=CARD_BORDER, width=1)
    y += 20
    shield_size = 28
    draw.rounded_rectangle([pad, y, pad + shield_size, y + shield_size], radius=8, fill=_ICON_BG)
    _draw_icon(draw, pad, y, shield_size, "shield")
    draw.text((pad + shield_size + 14, y + 3), "Readiness drill — not a real incident", font=font(True, 22), fill=INK)

    draw_footer_bar(draw, width, height, footer_h)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def get_awareness_card_image_url(backend_url: str, incident_name: str, causes: list[tuple[str, str, str]]) -> str:
    # _TEMPLATE_VERSION folded into the cache key so a future design
    # change regenerates every image instead of keeping someone's
    # already-cached file from before the change.
    key_source = "|".join([
        _TEMPLATE_VERSION, incident_name,
        ";".join(f"{n}:{d}:{i}" for n, d, i in causes),
    ])
    key = hashlib.sha1(key_source.encode("utf-8")).hexdigest()[:20]
    filename = f"awareness_{key}.png"
    path = GENERATED_DIR / filename
    if not path.exists():
        data = render_awareness_card_image(incident_name, causes)
        path.write_bytes(data)
    return f"{backend_url}/assets/generated/{filename}"
