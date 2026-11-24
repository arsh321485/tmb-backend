"""
Renders sir's "Select your modules" design as a real PNG -- the
header, heading, subtitle, the module boxes (icon, name, description,
a checkmark badge showing whether it's currently on, and a "SCORED ON"
row of tags), and a footer tip note above the footer bar.

The actual TOGGLE still has to be a real Slack element (checkboxes),
not baked into this image -- same reasoning as every other card with a
genuine per-item click target. This image is regenerated with the
CURRENT on/off state every time the admin toggles a module, so the
checkmark badges always match what's really selected; the real Slack
checkboxes stay underneath it for the actual click.
"""

import hashlib
import io
import math

from PIL import Image, ImageDraw

from .card_image_common import (
    BG, BRAND_RED, CARD_BG, CARD_BORDER, GENERATED_DIR, INK, MUTED,
    draw_footer_bar, font, wrap,
)

# Bump this whenever render_module_select_card_image's drawing changes
# -- see get_module_select_card_image_url's cache-key comment below.
_TEMPLATE_VERSION = "v9"

_ICON_BG = (252, 230, 230)
_ICON_FG = (60, 58, 58)
_TAG_DARK_BG = (26, 26, 26)
_TAG_DARK_FG = (255, 255, 255)
_TAG_LIGHT_BG = (237, 235, 231)
_TAG_LIGHT_FG = MUTED


def _draw_module_icon(draw: ImageDraw.ImageDraw, x0: int, y0: int, size: int, icon_key: str) -> None:
    cx, cy = x0 + size / 2, y0 + size / 2
    s = size
    color = _ICON_FG
    w = max(2, int(s * 0.08))
    if icon_key == "shield":
        draw.polygon(
            [(cx, cy - s * 0.3), (cx + s * 0.26, cy - s * 0.18), (cx + s * 0.26, cy + s * 0.06),
             (cx, cy + s * 0.3), (cx - s * 0.26, cy + s * 0.06), (cx - s * 0.26, cy - s * 0.18)],
            outline=color, width=w,
        )
    elif icon_key == "refresh":
        # Two ~230-degree arcs offset by 180 degrees, each ending in an
        # arrowhead tangent to the circle -- standard refresh/cycle
        # glyph, confirmed by rendering it standalone before using it.
        r = s * 0.28
        draw.arc([cx - r, cy - r, cx + r, cy + r], start=20, end=250, fill=color, width=w)
        draw.arc([cx - r, cy - r, cx + r, cy + r], start=200, end=430, fill=color, width=w)
        for ang in (250, 70):
            rad = math.radians(ang)
            tx, ty = cx + r * math.cos(rad), cy + r * math.sin(rad)
            tdx, tdy = -math.sin(rad), math.cos(rad)
            tip_size = s * 0.12
            p1 = (tx + tdx * tip_size, ty + tdy * tip_size)
            p2 = (tx - tdy * tip_size * 0.8, ty + tdx * tip_size * 0.8)
            p3 = (tx + tdy * tip_size * 0.8, ty - tdx * tip_size * 0.8)
            draw.polygon([p1, p2, p3], fill=color)
    else:  # lock
        body_w, body_h = s * 0.42, s * 0.3
        bx0, by0 = cx - body_w / 2, cy - body_h / 2 + s * 0.1
        shackle_w = max(3, int(s * 0.06))
        shackle_r = body_w * 0.34
        draw.pieslice([cx - shackle_r, by0 - shackle_r, cx + shackle_r, by0 + shackle_r], 180, 360, fill=color)
        inner_r = shackle_r - shackle_w
        draw.pieslice([cx - inner_r, by0 - inner_r, cx + inner_r, by0 + inner_r], 180, 360, fill=_ICON_BG)
        draw.rectangle([cx - shackle_r, by0, cx - shackle_r + shackle_w, by0], fill=color)
        draw.rectangle([cx + shackle_r - shackle_w, by0, cx + shackle_r, by0], fill=color)
        draw.rounded_rectangle([bx0, by0, bx0 + body_w, by0 + body_h], radius=int(s * 0.05), fill=color)


def _draw_tag(draw: ImageDraw.ImageDraw, x: int, y: int, text: str, emphasized: bool, tag_font) -> int:
    """Draws one SCORED-ON tag pill at (x, y); returns its right edge x
    so the caller can place the next one after it."""
    tw = draw.textlength(text, font=tag_font)
    tag_w = tw + 24
    tag_h = 28
    bg, fg = (_TAG_DARK_BG, _TAG_DARK_FG) if emphasized else (_TAG_LIGHT_BG, _TAG_LIGHT_FG)
    draw.rounded_rectangle([x, y, x + tag_w, y + tag_h], radius=6, fill=bg)
    draw.text((x + 12, y + 5), text, font=tag_font, fill=fg)
    return x + tag_w


def render_module_select_card_image(
    modules: list[tuple[str, str, str, bool, list[tuple[str, bool]]]], picked_count: int, total: int, footer_note: str = ""
) -> bytes:
    """
    modules: [(icon_key, title, description, checked, tags), ...]
    tags: [(tag_text, emphasized), ...] shown under a "SCORED ON" label.
    footer_note: optional tip line shown above the footer bar, with a
    small clock icon -- same role as the other cards' footer tips.
    """
    width = 1200
    pad = 56
    header_h = 56
    title_h = 64
    gap = 24
    counter_h = 34
    footer_h = 10

    measure_img = Image.new("RGB", (10, 10))
    measure_draw = ImageDraw.Draw(measure_img)
    name_font = font(True, 24)
    desc_font = font(False, 20)
    subtitle_font = font(False, 24)
    tag_label_font = font(True, 13)
    tag_font = font(True, 15)

    subtitle = "Each one is scored on what matters for that kind of incident. Nothing here is permanent."
    subtitle_lines = wrap(measure_draw, subtitle, subtitle_font, width - pad * 2)

    cols = len(modules) or 1
    gap_box = 24
    col_w = (width - pad * 2 - gap_box * (cols - 1)) // cols
    tag_area_w = col_w - 48

    def _tags_height(tags: list) -> int:
        if not tags:
            return 0
        rows = 1
        row_w = 0
        for text, _ in tags:
            tw = measure_draw.textlength(text, font=tag_font) + 24 + 10
            if row_w and row_w + tw > tag_area_w:
                rows += 1
                row_w = 0
            row_w += tw
        return 16 + 16 + rows * 28 + (rows - 1) * 10

    box_h = 0
    for _, name, desc, _checked, tags in modules:
        name_lines = wrap(measure_draw, name, name_font, col_w - 48)
        desc_lines = wrap(measure_draw, desc, desc_font, col_w - 48)
        h = 20 + 56 + 16 + len(name_lines) * 30 + 10 + len(desc_lines) * 27 + _tags_height(tags) + 24
        box_h = max(box_h, h)

    footer_note_lines = wrap(measure_draw, footer_note, font(False, 20), width - pad * 2 - 40) if footer_note else []
    footer_note_h = (len(footer_note_lines) * 26 + 20) if footer_note_lines else 0

    height = (
        pad + header_h + title_h + len(subtitle_lines) * 32 + gap + box_h + gap + counter_h
        + footer_note_h + pad + footer_h
    )

    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)


    badge_text = "STEP 1 · MODULES"
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
    prefix = "Select your "
    x = pad
    draw.text((x, y), prefix, font=title_font, fill=INK)
    x += draw.textlength(prefix, font=title_font)
    draw.text((x, y), "modules", font=title_font, fill=BRAND_RED)
    y += title_h

    for line in subtitle_lines:
        draw.text((pad, y), line, font=subtitle_font, fill=MUTED)
        y += 32
    y += gap

    for i, (icon_key, name, desc, checked, tags) in enumerate(modules):
        bx = pad + i * (col_w + gap_box)
        draw.rounded_rectangle([bx, y, bx + col_w, y + box_h], radius=14, fill=CARD_BG, outline=CARD_BORDER, width=2)
        icon_size = 56
        draw.rounded_rectangle([bx + 20, y + 20, bx + 20 + icon_size, y + 20 + icon_size], radius=14, fill=_ICON_BG)
        _draw_module_icon(draw, bx + 20, y + 20, icon_size, icon_key)

        check_size = 36
        check_x0, check_y0 = bx + col_w - 20 - check_size, y + 20
        if checked:
            draw.rounded_rectangle([check_x0, check_y0, check_x0 + check_size, check_y0 + check_size], radius=8, fill=BRAND_RED)
            ccx, ccy = check_x0 + check_size / 2, check_y0 + check_size / 2
            draw.line([(ccx - 8, ccy), (ccx - 2, ccy + 7)], fill=(255, 255, 255), width=3)
            draw.line([(ccx - 2, ccy + 7), (ccx + 9, ccy - 8)], fill=(255, 255, 255), width=3)
        else:
            draw.rounded_rectangle([check_x0, check_y0, check_x0 + check_size, check_y0 + check_size], radius=8, outline=CARD_BORDER, width=2)

        ty = y + 20 + icon_size + 16
        for line in wrap(draw, name, name_font, col_w - 48):
            draw.text((bx + 20, ty), line, font=name_font, fill=INK)
            ty += 30
        ty += 10
        for line in wrap(draw, desc, desc_font, col_w - 48):
            draw.text((bx + 20, ty), line, font=desc_font, fill=MUTED)
            ty += 27

        if tags:
            ty += 16
            draw.line([(bx + 20, ty), (bx + col_w - 20, ty)], fill=CARD_BORDER, width=1)
            ty += 16
            draw.text((bx + 20, ty), "SCORED ON", font=tag_label_font, fill=MUTED)
            ty += 22
            tx = bx + 20
            row_right = bx + col_w - 20
            for text, emphasized in tags:
                tw = draw.textlength(text, font=tag_font) + 24
                if tx != bx + 20 and tx + tw > row_right:
                    tx = bx + 20
                    ty += 38
                tx = _draw_tag(draw, tx, ty, text, emphasized, tag_font) + 10
    y += box_h + gap

    counter_font = font(True, 22)
    draw.text((pad, y), f"{picked_count} / {total}", font=counter_font, fill=INK)
    cw = draw.textlength(f"{picked_count} / {total} ", font=counter_font)
    draw.text((pad + cw, y), "selected", font=font(False, 22), fill=MUTED)
    y += counter_h

    if footer_note_lines:
        y += 20
        clock_r = 12
        draw.ellipse([pad, y, pad + clock_r * 2, y + clock_r * 2], fill=INK)
        ccx, ccy = pad + clock_r, y + clock_r
        draw.line([(ccx, ccy), (ccx, ccy - clock_r * 0.55)], fill="white", width=2)
        draw.line([(ccx, ccy), (ccx + clock_r * 0.4, ccy)], fill="white", width=2)
        note_font = font(True, 20)
        ny = y - 3
        for line in footer_note_lines:
            draw.text((pad + clock_r * 2 + 14, ny), line, font=note_font, fill=INK)
            ny += 26

    draw_footer_bar(draw, width, height, footer_h)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def get_module_select_card_image_url(
    backend_url: str,
    modules: list[tuple[str, str, str, bool, list[tuple[str, bool]]]],
    picked_count: int,
    total: int,
    footer_note: str = "",
) -> str:
    # _TEMPLATE_VERSION folded into the cache key so a future design
    # change regenerates every image instead of keeping an
    # already-cached file from before the change. The checked state is
    # also in the key, so toggling a module always regenerates (not
    # reuses a stale cached image showing the old state).
    def _mod_key(k: str, n: str, d: str, c: bool, tags: list) -> str:
        tags_key = ";".join(f"{t}:{int(e)}" for t, e in tags)
        return f"{k}:{n}:{d}:{int(c)}:{tags_key}"

    key_source = "|".join([
        _TEMPLATE_VERSION, str(picked_count), str(total), footer_note,
        ";".join(_mod_key(k, n, d, c, tags) for k, n, d, c, tags in modules),
    ])
    key = hashlib.sha1(key_source.encode("utf-8")).hexdigest()[:20]
    filename = f"moduleselect_{key}.png"
    path = GENERATED_DIR / filename
    if not path.exists():
        data = render_module_select_card_image(modules, picked_count, total, footer_note)
        path.write_bytes(data)
    return f"{backend_url}/assets/generated/{filename}"
