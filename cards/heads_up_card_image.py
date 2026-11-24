"""
Renders sir's "A drill with your role runs soon" pre-notification
design as a real PNG -- sent to every real person holding a role
targeted anywhere in an incident-wide scenario when training mode
(the "Yes -- send pre-notification" choice on the Trigger screen) is
on. Same template-code approach as the Welcome/Role/Acknowledge cards.

The Causes box is the one genuinely variable-length part of this
design (an incident-wide scenario can combine several causes under one
Incident, not just one) -- it grows its own height to fit however many
causes there are, one per line, same technique role_card_image.py
already uses for its per-phase activity boxes. The Threat/Incident
boxes stay their own natural height; the row's height is whichever of
the three ends up tallest, so a long cause list never gets cut off or
squeezed.
"""

import hashlib
import io

from PIL import Image, ImageDraw

from .card_image_common import (
    BG, BRAND_RED, CARD_BG, CARD_BORDER, GENERATED_DIR, INK, MUTED,
    draw_footer_bar, font, wrap,
)

# Bump this whenever render_heads_up_card_image's drawing changes --
# see get_heads_up_card_image_url's cache-key comment below.
_TEMPLATE_VERSION = "v7"

_BADGE_BG = (247, 231, 210)
_BADGE_BORDER = (224, 189, 135)
_BADGE_FG = (166, 100, 30)
_CAUSES_BG = (253, 243, 229)
_CAUSES_BORDER = (224, 189, 135)

# Beyond this many causes, the box lists only the first N and adds a
# "+K more" line instead of growing indefinitely tall.
_MAX_CAUSES_SHOWN = 6


def _box(
    draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int,
    label: str, value_lines: list[str], highlighted: bool,
) -> None:
    fill = _CAUSES_BG if highlighted else CARD_BG
    border = _CAUSES_BORDER if highlighted else CARD_BORDER
    draw.rounded_rectangle([x, y, x + w, y + h], radius=14, fill=fill, outline=border, width=1)
    draw.text((x + 20, y + 18), label.upper(), font=font(True, 15), fill=MUTED)
    value_font = font(True, 24)
    ty = y + 48
    for line in value_lines:
        draw.text((x + 20, ty), line, font=value_font, fill=INK)
        ty += 32


def render_heads_up_card_image(threat_label: str, incident_name: str, causes: list[str], role_text: str) -> bytes:
    width = 1200
    pad = 56
    header_h = 56
    title_h = 90
    gap = 24
    pill_h = 56
    footer_h = 10

    measure_img = Image.new("RGB", (10, 10))
    measure_draw = ImageDraw.Draw(measure_img)
    box_font = font(True, 24)

    col_w = (width - pad * 2 - 2 * 60) // 3  # two 60px-wide arrow gaps between the 3 boxes

    threat_lines = wrap(measure_draw, threat_label, box_font, col_w - 40)[:3]
    incident_lines = wrap(measure_draw, incident_name, box_font, col_w - 40)[:3]

    shown_causes = causes[:_MAX_CAUSES_SHOWN]
    extra = len(causes) - len(shown_causes)
    cause_lines: list[str] = []
    for c in shown_causes:
        cause_lines.extend(wrap(measure_draw, c, box_font, col_w - 40))
    if extra > 0:
        cause_lines.append(f"+{extra} more")

    box_h = max(48 + 32 * len(threat_lines) + 20, 48 + 32 * len(incident_lines) + 20, 48 + 32 * len(cause_lines) + 20)

    height = pad + header_h + title_h + box_h + gap + pill_h + pad + footer_h

    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)


    badge_text = "HEADS UP"
    badge_font = font(True, 16)
    badge_tw = draw.textlength(badge_text, font=badge_font)
    badge_w = badge_tw + 56
    badge_x0, badge_y0 = width - pad - badge_w, pad
    draw.rounded_rectangle([badge_x0, badge_y0, width - pad, badge_y0 + 40], radius=20, fill=_BADGE_BG, outline=_BADGE_BORDER, width=1)
    dot_cy = badge_y0 + 20
    draw.ellipse([badge_x0 + 20, dot_cy - 4, badge_x0 + 28, dot_cy + 4], fill=_BADGE_FG)
    draw.text((badge_x0 + 36, badge_y0 + 11), badge_text, font=badge_font, fill=_BADGE_FG)

    y = pad + header_h
    title_font = font(True, 48)
    prefix = "A drill with "
    mid = "your role"
    suffix = " runs soon"
    x = pad
    draw.text((x, y), prefix, font=title_font, fill=INK)
    x += draw.textlength(prefix, font=title_font)
    draw.text((x, y), mid, font=title_font, fill=BRAND_RED)
    x += draw.textlength(mid, font=title_font)
    draw.text((x, y), suffix, font=title_font, fill=INK)
    y += title_h

    box1_x = pad
    box2_x = box1_x + col_w + 60
    box3_x = box2_x + col_w + 60

    _box(draw, box1_x, y, col_w, box_h, "THREAT", threat_lines, highlighted=False)
    _box(draw, box2_x, y, col_w, box_h, "INCIDENT", incident_lines, highlighted=False)
    _box(draw, box3_x, y, col_w, box_h, "CAUSES", cause_lines, highlighted=True)

    arrow_font = font(True, 28)
    arrow_y = y + box_h // 2 - 16
    draw.text((box1_x + col_w + 14, arrow_y), "→", font=arrow_font, fill=BRAND_RED)
    draw.text((box2_x + col_w + 14, arrow_y), "→", font=arrow_font, fill=BRAND_RED)

    y += box_h + gap

    pill_font = font(False, 24)
    pill_text = f"Your role · {role_text}"
    pill_tw = draw.textlength(pill_text, font=pill_font)
    pill_w = pill_tw + 96
    draw.rounded_rectangle([pad, y, pad + pill_w, y + pill_h], radius=28, fill=CARD_BG, outline=CARD_BORDER, width=1)
    icon_cy = y + pill_h // 2
    for ox in (pad + 22, pad + 40):
        draw.ellipse([ox, icon_cy - 12, ox + 12, icon_cy], fill=BRAND_RED)
        draw.pieslice([ox - 4, icon_cy - 2, ox + 16, icon_cy + 20], 180, 360, fill=BRAND_RED)
    draw.text((pad + 66, y + 14), pill_text, font=pill_font, fill=INK)

    draw_footer_bar(draw, width, height, footer_h)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def get_heads_up_card_image_url(backend_url: str, threat_label: str, incident_name: str, causes: list[str], role_text: str) -> str:
    # _TEMPLATE_VERSION folded into the cache key so a future design
    # change regenerates every image instead of keeping someone's
    # already-cached file from before the change.
    key_source = "|".join([_TEMPLATE_VERSION, threat_label, incident_name, ";".join(causes), role_text])
    key = hashlib.sha1(key_source.encode("utf-8")).hexdigest()[:20]
    filename = f"headsup_{key}.png"
    path = GENERATED_DIR / filename
    if not path.exists():
        data = render_heads_up_card_image(threat_label, incident_name, causes, role_text)
        path.write_bytes(data)
    return f"{backend_url}/assets/generated/{filename}"
