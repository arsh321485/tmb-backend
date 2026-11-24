"""
Renders the Teams step's static chrome as a real PNG -- logo+badge,
the "Staff your response teams" title, and the progress summary
(mandatory-staffed count + bar, members-added count). Same
template-code approach as the other cards.

Deliberately does NOT cover the tier tabs (Mandatory/Recommended/
Optional/External), the "Jump to a team…" select, the per-team tiles,
or the selected team's own detail section -- every one of those is a
genuine per-item click target (pick a tier, jump to a team, expand a
team's detail) that a flat image can't provide a button for. Those
stay real Slack elements underneath this image, same reasoning as
every other card with a genuine click target, even though it means
they keep Slack's own plain button styling rather than the fully
custom tile look in sir's reference -- a picture can't be clickable
per-tile.
"""

import hashlib
import io

from PIL import Image, ImageDraw

from .card_image_common import (
    BG, BRAND_RED, CARD_BORDER, GENERATED_DIR, INK, MUTED,
    draw_footer_bar, font,
)

# Bump whenever render_teams_card_image's drawing changes -- see
# get_teams_card_image_url's cache-key comment below.
_TEMPLATE_VERSION = "v5"

_BAR_TRACK = (230, 227, 221)


def render_teams_card_image(staffed: int, total: int, members_added: int) -> bytes:
    width = 1200
    pad = 56
    header_h = 56
    title_h = 64
    gap = 24
    progress_h = 70
    footer_h = 10

    height = pad + header_h + title_h + gap + progress_h + pad + footer_h

    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)


    badge_text = "STEP 4 · TEAMS"
    badge_font = font(True, 16)
    badge_tw = draw.textlength(badge_text, font=badge_font)
    badge_w = badge_tw + 56
    badge_x0, badge_y0 = width - pad - badge_w, pad
    draw.rounded_rectangle([badge_x0, badge_y0, width - pad, badge_y0 + 40], radius=20, outline=CARD_BORDER, width=2)
    dot_cy = badge_y0 + 20
    draw.ellipse([badge_x0 + 20, dot_cy - 4, badge_x0 + 28, dot_cy + 4], fill=INK)
    draw.text((badge_x0 + 36, badge_y0 + 11), badge_text, font=badge_font, fill=INK)

    y = pad + header_h
    title_font = font(True, 48)
    prefix = "Staff your "
    x = pad
    draw.text((x, y), prefix, font=title_font, fill=INK)
    x += draw.textlength(prefix, font=title_font)
    draw.text((x, y), "response teams", font=title_font, fill=BRAND_RED)
    y += title_h + gap

    # Big fraction + caption on the left.
    frac_font = font(True, 56)
    denom_font = font(True, 32)
    frac_text = str(staffed)
    draw.text((pad, y), frac_text, font=frac_font, fill=BRAND_RED)
    fx = pad + draw.textlength(frac_text, font=frac_font)
    denom_text = f"/{total}"
    draw.text((fx, y + 14), denom_text, font=denom_font, fill=MUTED)
    caption_font = font(False, 18)
    draw.text((pad, y + 58), "Mandatory teams staffed", font=caption_font, fill=MUTED)

    # Progress bar in the middle.
    bar_x0 = pad + 140
    bar_x1 = width - pad - 260
    bar_y0 = y + 20
    bar_h = 14
    draw.rounded_rectangle([bar_x0, bar_y0, bar_x1, bar_y0 + bar_h], radius=bar_h // 2, fill=_BAR_TRACK)
    if total > 0 and staffed > 0:
        fill_x1 = bar_x0 + (bar_x1 - bar_x0) * min(staffed, total) / total
        draw.rounded_rectangle([bar_x0, bar_y0, max(fill_x1, bar_x0 + bar_h), bar_y0 + bar_h], radius=bar_h // 2, fill=BRAND_RED)

    # Members-added count on the right.
    members_font = font(True, 28)
    members_label_font = font(False, 18)
    members_text = str(members_added)
    label_text = " members added"
    members_tw = draw.textlength(members_text, font=members_font)
    label_tw = draw.textlength(label_text, font=members_label_font)
    icon_w = 28
    total_w = icon_w + 10 + members_tw + 6 + label_tw
    rx = width - pad - total_w
    _draw_people_icon(draw, rx, int(y + 12), icon_w)
    draw.text((rx + icon_w + 10, y + 10), members_text, font=members_font, fill=INK)
    draw.text((rx + icon_w + 10 + members_tw + 6, y + 16), label_text, font=members_label_font, fill=MUTED)

    draw_footer_bar(draw, width, height, footer_h)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _draw_people_icon(draw: ImageDraw.ImageDraw, x0: int, y0: int, size: int) -> None:
    """Two simple person silhouettes (head + shoulders arc), confirmed
    by rendering it standalone before using it -- an earlier attempt
    using overlapping arcs/ellipses for the "two people" look rendered
    as an unrecognizable blob."""
    s = size

    def _person(cx: float, cy: float) -> None:
        head_r = s * 0.16
        draw.ellipse([cx - head_r, cy - s * 0.3 - head_r, cx + head_r, cy - s * 0.3 + head_r], outline=BRAND_RED, width=2)
        body_w, body_h = s * 0.5, s * 0.34
        draw.arc([cx - body_w / 2, cy - s * 0.05, cx + body_w / 2, cy - s * 0.05 + body_h * 2], start=180, end=360, fill=BRAND_RED, width=2)

    _person(x0 + s * 0.32, y0 + s * 0.5)
    _person(x0 + s * 0.68, y0 + s * 0.5)


def get_teams_card_image_url(backend_url: str, staffed: int, total: int, members_added: int) -> str:
    # _TEMPLATE_VERSION + every piece of real data folded into the
    # cache key so a changed drawing or a changed staffing count both
    # bust the cache instead of silently reusing a stale image.
    key = hashlib.sha1(f"{_TEMPLATE_VERSION}|{staffed}|{total}|{members_added}".encode("utf-8")).hexdigest()[:20]
    filename = f"teams_{key}.png"
    path = GENERATED_DIR / filename
    if not path.exists():
        path.write_bytes(render_teams_card_image(staffed, total, members_added))
    return f"{backend_url}/assets/generated/{filename}"
