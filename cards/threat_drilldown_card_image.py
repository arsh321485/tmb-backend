"""
Renders the two read-only content blocks inside the Threat Mapping
drill-down as real PNGs:
  - the selected THREAT's detail (why it's critical, impact if it
    happens, and any real services from the plan it maps to)
  - the selected INCIDENT's list of causes

Same template-code approach as the other cards. Unlike the full-screen
cards, these have no logo/badge of their own -- they sit embedded
between several rows of real tabs that are already on screen (Module /
Criticality / Threat / Incident), so they're just a styled content box,
not a whole card.

The Module/Criticality/Threat/Incident tabs themselves, and the
"Build scenario" button, all stay real Slack elements above and below
these images -- not baked in, same reasoning as every other card with
a genuine click target: a picture can't be clickable per-tab.
"""

import hashlib
import io

from PIL import Image, ImageDraw

from .card_image_common import (
    BG, BRAND_RED, GENERATED_DIR, INK, TEAL,
    draw_footer_bar, font, wrap,
)

# Bump whenever either render function's drawing changes -- see the
# two get_*_url functions' cache-key comments below.
_TEMPLATE_VERSION = "v5"

# ONE cream (BG) box with a single border -- no separate white inner
# card and no left accent bar (sir's call: two nested boxes in two
# different shades read as "two boxes stuck together", not one
# screen). OUTER_PAD is just the margin to the canvas edge so the
# rounded corners aren't clipped; FOOTER_H adds the same red/teal/red
# bar every other card ends on.
_OUTER_PAD = 18
_FOOTER_H = 10

_RTO_BG = (250, 221, 221)
_RTO_FG = (190, 40, 50)

# Same three-color risk scale as threat_profile_card_image.py (sir's
# rebrand) -- reused here so this embedded box reads as the same
# branded template as every other card, not a plain leftover box.
_MAROON = (111, 22, 22)
_ORANGE = (184, 120, 40)
_RISK_PILL_COLORS = {
    "Critical": _MAROON,
    "High": BRAND_RED,
    "Med": _ORANGE,
}


def render_threat_detail_image(threat_label: str, why_text: str, impact_text: str, mapped_services: list[tuple[str, str]], crit: str = "") -> bytes:
    """
    mapped_services: [(service_name, rto), ...] -- real services from
    the uploaded plan this threat maps to; empty if there's no real
    plan yet or nothing mapped. crit (Critical/High/Med) drives the
    left accent bar + badge pill color, same scale as the Threat
    Profile screen's risk pills, so this box reads as the same severity
    everywhere it's shown.
    """
    width = 1100
    pad = 28
    gap = 14
    card_x0 = _OUTER_PAD
    card_x1 = width - _OUTER_PAD
    left = card_x0 + pad
    right = card_x1 - pad

    measure_img = Image.new("RGB", (10, 10))
    measure_draw = ImageDraw.Draw(measure_img)
    title_font = font(True, 26)
    label_font = font(True, 14)
    value_font = font(False, 20)
    badge_font = font(True, 14)

    title_lines = wrap(measure_draw, threat_label, title_font, right - left - 130)
    why_lines = wrap(measure_draw, why_text, value_font, right - left) if why_text else []
    impact_lines = wrap(measure_draw, impact_text, value_font, right - left) if impact_text else []

    mapped_h = 0
    if mapped_services:
        mapped_h = 20 + 22 + len(mapped_services) * 36

    card_h = (
        pad + len(title_lines) * 32 + gap
        + (16 + len(why_lines) * 26 if why_lines else 0)
        + (gap + 16 + len(impact_lines) * 26 if impact_lines else 0)
        + (gap + mapped_h if mapped_services else 0)
        + pad
    )
    height = _OUTER_PAD + card_h + _OUTER_PAD + _FOOTER_H

    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)
    # No rectangle drawn here at all -- the whole canvas is already BG,
    # and Slack's own image frame is the one real border around this
    # picture. Drawing our own border on top of that duplicated it into
    # a visible "box inside a box".
    card_y0 = _OUTER_PAD

    accent_color = _RISK_PILL_COLORS.get(crit, TEAL)

    y = card_y0 + pad
    title_y = y
    for line in title_lines:
        draw.text((left, y), line, font=title_font, fill=INK)
        y += 32

    if crit:
        badge_text = crit.upper()
        badge_tw = draw.textlength(badge_text, font=badge_font)
        badge_w = badge_tw + 28
        badge_x0 = right - badge_w
        draw.rounded_rectangle([badge_x0, title_y + 2, badge_x0 + badge_w, title_y + 2 + 28], radius=14, fill=accent_color)
        draw.text((badge_x0 + 14, title_y + 9), badge_text, font=badge_font, fill=(255, 255, 255))

    y += gap

    if why_lines:
        draw.text((left, y), "WHY CRITICAL", font=label_font, fill=TEAL)
        y += 20
        for line in why_lines:
            draw.text((left, y), line, font=value_font, fill=INK)
            y += 26

    if impact_lines:
        y += gap
        draw.text((left, y), "IMPACT IF IT HAPPENS", font=label_font, fill=TEAL)
        y += 20
        for line in impact_lines:
            draw.text((left, y), line, font=value_font, fill=INK)
            y += 26

    if mapped_services:
        y += gap
        draw.text((left, y), "MAPPED SERVICES FROM YOUR PLAN", font=label_font, fill=TEAL)
        y += 24
        name_font = font(False, 19)
        rto_font = font(True, 15)
        for name, rto in mapped_services:
            draw.text((left, y + 6), name, font=name_font, fill=INK)
            rto_tw = draw.textlength(rto, font=rto_font)
            pill_w = rto_tw + 24
            pill_h = 26
            pill_x0 = right - pill_w
            draw.rounded_rectangle([pill_x0, y + 2, pill_x0 + pill_w, y + 2 + pill_h], radius=pill_h // 2, fill=_RTO_BG)
            draw.text((pill_x0 + 12, y + 7), rto, font=rto_font, fill=_RTO_FG)
            y += 36

    draw_footer_bar(draw, width, height, _FOOTER_H)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def render_incident_causes_image(incident_name: str, causes: list[str]) -> bytes:
    width = 1100
    pad = 28
    gap = 10
    card_x0 = _OUTER_PAD
    card_x1 = width - _OUTER_PAD
    left = card_x0 + pad
    right = card_x1 - pad

    measure_img = Image.new("RGB", (10, 10))
    measure_draw = ImageDraw.Draw(measure_img)
    title_font = font(True, 24)
    label_font = font(True, 14)
    cause_font = font(False, 19)

    title_lines = wrap(measure_draw, incident_name, title_font, right - left)
    cause_lines_counts = [len(wrap(measure_draw, c, cause_font, right - left - 26)) for c in causes]

    card_h = pad + len(title_lines) * 30 + gap + 20 + gap + sum(max(1, n) * 26 for n in cause_lines_counts) + pad
    height = _OUTER_PAD + card_h + _OUTER_PAD + _FOOTER_H

    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)
    card_y0 = _OUTER_PAD

    y = card_y0 + pad
    for line in title_lines:
        draw.text((left, y), line, font=title_font, fill=INK)
        y += 30
    y += gap

    draw.text((left, y), "CAUSES", font=label_font, fill=TEAL)
    y += 20 + gap

    for cause in causes:
        bullet_cy = y + 10
        draw.ellipse([left + 2, bullet_cy - 3, left + 8, bullet_cy + 3], fill=BRAND_RED)
        lines = wrap(draw, cause, cause_font, right - left - 26)
        for line in lines or [""]:
            draw.text((left + 26, y), line, font=cause_font, fill=INK)
            y += 26

    draw_footer_bar(draw, width, height, _FOOTER_H)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def get_threat_detail_image_url(backend_url: str, threat_label: str, why_text: str, impact_text: str, mapped_services: list[tuple[str, str]], crit: str = "") -> str:
    # _TEMPLATE_VERSION + every piece of real data folded into the
    # cache key so a changed drawing or a changed threat both bust the
    # cache instead of silently reusing a stale image.
    flat = ";".join(f"{n}:{r}" for n, r in mapped_services)
    raw = f"{_TEMPLATE_VERSION}|{threat_label}|{why_text}|{impact_text}|{flat}|{crit}"
    key = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]
    filename = f"threatdetail_{key}.png"
    path = GENERATED_DIR / filename
    if not path.exists():
        path.write_bytes(render_threat_detail_image(threat_label, why_text, impact_text, mapped_services, crit))
    return f"{backend_url}/assets/generated/{filename}"


def get_incident_causes_image_url(backend_url: str, incident_name: str, causes: list[str]) -> str:
    raw = f"{_TEMPLATE_VERSION}|{incident_name}|{';'.join(causes)}"
    key = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]
    filename = f"incidentcauses_{key}.png"
    path = GENERATED_DIR / filename
    if not path.exists():
        path.write_bytes(render_incident_causes_image(incident_name, causes))
    return f"{backend_url}/assets/generated/{filename}"
