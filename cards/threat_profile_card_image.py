"""
Renders the "Your threat profile" screen's read-only content as one
real PNG -- logo+badge, title, a status pill (draft/approved), the
risk-count summary + active-module pill, and every threat as a compact
row (category, a one-line impact description, likelihood, and a risk
pill). Same template-code approach as the other cards.

The module tabs (Cybersecurity/Privacy/Business Continuity) and the
action buttons (+ Add a threat / Edit / Approve) stay real Slack
buttons underneath this image -- not baked into it, same reasoning as
every other card with a genuine click target: Slack can't pin a button
to a spot inside a picture.
"""

import hashlib
import io
import re

from PIL import Image, ImageDraw

from .card_image_common import (
    BG, BRAND_RED, CARD_BG, CARD_BORDER, GENERATED_DIR, INK, MUTED, TEAL, TEAL_BG,
    draw_footer_bar, font, wrap,
)

# Bump whenever render_threat_profile_card_image's drawing changes --
# see get_threat_profile_card_image_url's cache-key comment below.
_TEMPLATE_VERSION = "v9"

# Maroon for Critical, red for High, orange for Medium -- three visibly
# different colors instead of Critical/High sharing the same red.
_MAROON = (111, 22, 22)
_ORANGE = (184, 120, 40)

_RISK_PILL_COLORS = {
    "Critical": _MAROON,
    "High": BRAND_RED,
    "Med": _ORANGE,
}

_DRAFT_BG = (250, 224, 213)
_DRAFT_FG = (150, 62, 22)

_MODULE_PILL_BG = (223, 241, 238)
_MODULE_PILL_FG = TEAL


def _split_impact(impact: str) -> str:
    """Reformats "Severe (Client Data Breach/Service Disruption)" into
    "Severe — client data breach, service disruption", matching
    sir's reference design -- falls back to the raw text unchanged if
    it isn't in that "X (Y/Z)" shape."""
    m = re.match(r"^(.+?)\s*\((.+)\)\s*$", impact)
    if not m:
        return impact
    headline, detail = m.group(1).strip(), m.group(2)
    parts = [p.strip().lower() for p in detail.split("/") if p.strip()]
    return f"{headline} — {', '.join(parts)}" if parts else headline


def _spaced_category(category: str) -> str:
    """"SaaS API Misconfiguration/Exposure" -> "SaaS API Misconfiguration
    / Exposure" -- purely a display spacing fix, matching sir's
    reference design."""
    return re.sub(r"\s*/\s*", " / ", category)


def render_threat_profile_card_image(
    status: str,
    risk_counts: dict,
    threats: list[tuple[str, str, str, str]],
    active_module: str = "",
    active_module_icon: str = "shield",
    active_count: int = 0,
    total_count: int = 0,
) -> bytes:
    """
    status: "approved" or "draft".
    risk_counts: {"Critical": n, "High": n, "Med": n}.
    threats: [(category, likelihood, business_impact, risk_level), ...]
    active_module / active_count / total_count: feed the small
    "<module> · X of Y" pill next to the risk counts.
    """
    from .module_select_card_image import _draw_module_icon

    width = 1200
    pad = 56
    header_h = 56
    title_h = 64
    gap = 20
    pill_h = 36
    counts_h = 34
    footer_h = 10
    row_pad_x = 24
    row_pad_y = 18

    measure_img = Image.new("RGB", (10, 10))
    measure_draw = ImageDraw.Draw(measure_img)
    label_font = font(False, 13)
    cat_font = font(True, 22)
    desc_font = font(False, 18)
    like_value_font = font(True, 18)
    risk_font = font(True, 16)

    # Widened so the likelihood block sits further left, away from the
    # risk pill at the far edge, instead of crowding right up against it.
    right_col_w = 340
    left_col_w = width - pad * 2 - row_pad_x * 2 - right_col_w - 20

    row_heights = []
    for category, likelihood, impact, risk in threats:
        cat_text = _spaced_category(category)
        desc_text = _split_impact(impact)
        cat_lines = wrap(measure_draw, cat_text, cat_font, left_col_w)
        desc_lines = wrap(measure_draw, desc_text, desc_font, left_col_w)
        h = row_pad_y + 16 + len(cat_lines) * 28 + 6 + len(desc_lines) * 24 + row_pad_y
        row_heights.append(max(h, 90))

    threats_h = sum(row_heights) + gap * max(0, len(threats) - 1)

    if status == "approved":
        status_text = "Approved — this is your organization's active threat profile."
    else:
        status_text = "Draft · Generated from your organization details"
    status_font = font(False, 18)
    status_tw = measure_draw.textlength(status_text, font=status_font)

    footer_note = "" if status == "approved" else "Review, remove or add threats, then Approve."
    footer_note_font = font(False, 18)
    footer_note_h = 30 if footer_note else 0

    height = (
        pad + header_h + title_h + pill_h + gap + counts_h + gap
        + threats_h + gap + footer_note_h + pad + footer_h
    )

    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)


    # Filled pink badge for draft, filled teal for approved -- matching
    # sir's reference exactly (a filled pill, not the thin-outline
    # style used on the Modules step).
    badge_text = "STEP 2 · THREATS"
    badge_bg, badge_fg = (TEAL_BG, TEAL) if status == "approved" else ((252, 225, 225), (150, 30, 40))
    badge_font = font(True, 16)
    badge_tw = draw.textlength(badge_text, font=badge_font)
    badge_w = badge_tw + 56
    badge_x0, badge_y0 = width - pad - badge_w, pad
    draw.rounded_rectangle([badge_x0, badge_y0, width - pad, badge_y0 + 40], radius=20, fill=badge_bg)
    dot_cy = badge_y0 + 20
    draw.ellipse([badge_x0 + 20, dot_cy - 4, badge_x0 + 28, dot_cy + 4], fill=badge_fg)
    draw.text((badge_x0 + 36, badge_y0 + 11), badge_text, font=badge_font, fill=badge_fg)

    y = pad + header_h
    title_font = font(True, 48)
    prefix = "Your threat "
    x = pad
    draw.text((x, y), prefix, font=title_font, fill=INK)
    x += draw.textlength(prefix, font=title_font)
    draw.text((x, y), "profile", font=title_font, fill=BRAND_RED)
    y += title_h

    # Status pill (page icon + text) instead of the old plain gray line.
    pill_bg, pill_fg = (TEAL_BG, TEAL) if status == "approved" else (_DRAFT_BG, _DRAFT_FG)
    pill_w = status_tw + 56
    draw.rounded_rectangle([pad, y, pad + pill_w, y + pill_h], radius=18, fill=pill_bg)
    draw.rounded_rectangle([pad + 16, y + 9, pad + 16 + 14, y + 9 + 18], radius=2, outline=pill_fg, width=2)
    draw.line([(pad + 19, y + 14), (pad + 27, y + 14)], fill=pill_fg, width=1)
    draw.line([(pad + 19, y + 18), (pad + 27, y + 18)], fill=pill_fg, width=1)
    draw.line([(pad + 19, y + 22), (pad + 24, y + 22)], fill=pill_fg, width=1)
    draw.text((pad + 40, y + 8), status_text, font=status_font, fill=pill_fg)
    y += pill_h + gap

    count_font = font(True, 20)
    cx = pad
    for crit, label in (("Critical", "Critical"), ("High", "High"), ("Med", "Medium")):
        n = risk_counts.get(crit, 0)
        color = _RISK_PILL_COLORS.get(crit, MUTED)
        text = f"{n} {label}"
        draw.rounded_rectangle([cx, y, cx + 16, y + 16], radius=3, fill=color)
        draw.text((cx + 24, y - 2), text, font=count_font, fill=INK)
        cx += draw.textlength(text, font=count_font) + 60

    if active_module and total_count:
        module_text = f"{active_module} · {active_count} of {total_count}"
        module_font = font(True, 16)
        mod_tw = draw.textlength(module_text, font=module_font)
        mod_icon_size = 18
        mod_w = mod_tw + mod_icon_size + 44
        mod_x0 = width - pad - mod_w
        draw.rounded_rectangle([mod_x0, y - 2, width - pad, y - 2 + 28], radius=14, fill=_MODULE_PILL_BG)
        _draw_module_icon(draw, int(mod_x0 + 12), int(y + 3), mod_icon_size, active_module_icon)
        draw.text((mod_x0 + 12 + mod_icon_size + 8, y + 1), module_text, font=module_font, fill=_MODULE_PILL_FG)

    y += counts_h + gap

    for i, (category, likelihood, impact, risk) in enumerate(threats):
        rh = row_heights[i]
        draw.rounded_rectangle([pad, y, width - pad, y + rh], radius=14, fill=CARD_BG, outline=CARD_BORDER, width=2)

        lx = pad + row_pad_x
        ty = y + row_pad_y
        draw.text((lx, ty), "THREAT", font=label_font, fill=MUTED)
        ty += 16
        cat_lines = wrap(draw, _spaced_category(category), cat_font, left_col_w)
        for line in cat_lines:
            draw.text((lx, ty), line, font=cat_font, fill=INK)
            ty += 28
        ty += 6
        desc_lines = wrap(draw, _split_impact(impact), desc_font, left_col_w)
        for line in desc_lines:
            draw.text((lx, ty), line, font=desc_font, fill=MUTED)
            ty += 24

        # "LIKELIHOOD" label and the risk pill share one top row (pill at
        # the far right, vertically centered against the label text);
        # the likelihood value sits on its own row underneath. The whole
        # two-row group is centered within the row's full height -- sir's
        # call: the pill used to sit stacked below the value instead of
        # next to the label, with an uneven gap either side.
        risk_color = _RISK_PILL_COLORS.get(risk, MUTED)
        risk_label = {"Med": "MED"}.get(risk, risk.upper())
        rw = draw.textlength(risk_label, font=risk_font)
        pill_box_w = rw + 32
        pill_box_h = 28

        label_row_h = 20
        value_row_h = 22
        row_gap = 6
        group_h = max(label_row_h, pill_box_h) + row_gap + value_row_h
        group_y = y + (rh - group_h) / 2

        rx = pad + row_pad_x + left_col_w + 20
        draw.text((rx, group_y + (label_row_h - 13) / 2), "LIKELIHOOD", font=label_font, fill=MUTED)
        draw.text((rx, group_y + max(label_row_h, pill_box_h) + row_gap), likelihood, font=like_value_font, fill=INK)

        pill_x0 = width - pad - row_pad_x - pill_box_w
        pill_y0 = group_y + (max(label_row_h, pill_box_h) - pill_box_h) / 2
        draw.rounded_rectangle([pill_x0, pill_y0, pill_x0 + pill_box_w, pill_y0 + pill_box_h], radius=pill_box_h // 2, fill=risk_color)
        draw.text((pill_x0 + 16, pill_y0 + 6), risk_label, font=risk_font, fill=(255, 255, 255))

        y += rh + gap

    if footer_note:
        list_x, list_y = pad, y
        for i in range(3):
            ly = list_y + 4 + i * 5
            draw.line([(list_x, ly), (list_x + 3, ly)], fill=INK, width=2)
            draw.line([(list_x + 7, ly), (list_x + 15, ly)], fill=INK, width=2)
        draw.text((pad + 24, y - 2), footer_note, font=footer_note_font, fill=INK)

    draw_footer_bar(draw, width, height, footer_h)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def get_threat_profile_card_image_url(
    backend_url: str,
    status: str,
    risk_counts: dict,
    threats: list[tuple[str, str, str, str]],
    active_module: str = "",
    active_module_icon: str = "shield",
    active_count: int = 0,
    total_count: int = 0,
) -> str:
    # _TEMPLATE_VERSION + every piece of real data folded into the
    # cache key so a changed drawing or a changed threat profile both
    # bust the cache instead of silently reusing a stale image.
    key_source = "|".join([
        _TEMPLATE_VERSION, status, str(sorted(risk_counts.items())),
        ";".join(f"{c}:{l}:{i}:{r}" for c, l, i, r in threats),
        active_module, active_module_icon, str(active_count), str(total_count),
    ])
    key = hashlib.sha1(key_source.encode("utf-8")).hexdigest()[:20]
    filename = f"threatprofile_{key}.png"
    path = GENERATED_DIR / filename
    if not path.exists():
        data = render_threat_profile_card_image(status, risk_counts, threats, active_module, active_module_icon, active_count, total_count)
        path.write_bytes(data)
    return f"{backend_url}/assets/generated/{filename}"
