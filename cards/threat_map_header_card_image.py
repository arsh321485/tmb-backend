"""
Renders the Organizational Threats screen's static chrome as a real
PNG -- logo+badge, the "N organizational threats" title, the intro
paragraph, a stacked severity bar + legend, and the Sector/Region/
Regulation/By-Module stat tiles. Same template-code approach as the
other cards.

The module tabs (Cybersecurity/Privacy), the criticality tabs
(Critical/High/Med/Dropped), and every threat row below all stay real
Slack elements -- not baked into this image, same reasoning as every
other card with a genuine click target.
"""

import hashlib
import io

from PIL import Image, ImageDraw

from .card_image_common import (
    BG, BRAND_RED, CARD_BG, CARD_BORDER, GENERATED_DIR, INK, MUTED,
    draw_footer_bar, font, wrap,
)

# Bump whenever render_threat_map_header_image's drawing changes -- see
# get_threat_map_header_image_url's cache-key comment below.
_TEMPLATE_VERSION = "v4"

_MAROON = (111, 22, 22)
_ORANGE = (184, 120, 40)
_DROPPED = (210, 207, 200)

_SEVERITY_COLORS = {
    "Critical": _MAROON,
    "High": BRAND_RED,
    "Med": _ORANGE,
    "Dropped": _DROPPED,
}

_TILE_ICON_BG = (223, 236, 252)
_TILE_ICON_FG = (40, 80, 150)


def _draw_tile_icon(draw: ImageDraw.ImageDraw, x0: int, y0: int, size: int, icon_key: str) -> None:
    cx, cy = x0 + size / 2, y0 + size / 2
    s = size
    w = max(2, int(s * 0.1))
    color = _TILE_ICON_FG
    if icon_key == "globe":
        r = s * 0.32
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=w)
        draw.line([(cx - r, cy), (cx + r, cy)], fill=color, width=max(1, w - 1))
        draw.ellipse([cx - r * 0.5, cy - r, cx + r * 0.5, cy + r], outline=color, width=max(1, w - 1))
    elif icon_key == "scales":
        draw.line([(cx, cy - s * 0.3), (cx, cy + s * 0.3)], fill=color, width=w)
        draw.line([(cx - s * 0.28, cy - s * 0.15), (cx + s * 0.28, cy - s * 0.15)], fill=color, width=w)
        for dx in (-s * 0.28, s * 0.28):
            draw.arc([cx + dx - s * 0.12, cy - s * 0.15, cx + dx + s * 0.12, cy + s * 0.1], start=0, end=180, fill=color, width=max(1, w - 1))
    elif icon_key == "grid":
        gs = s * 0.6
        gx0, gy0 = cx - gs / 2, cy - gs / 2
        cell = gs / 2
        pad_c = cell * 0.15
        for r in range(2):
            for c in range(2):
                draw.rectangle(
                    [gx0 + c * cell + pad_c, gy0 + r * cell + pad_c, gx0 + (c + 1) * cell - pad_c, gy0 + (r + 1) * cell - pad_c],
                    fill=color,
                )
    else:  # "building" -- Sector
        bw, bh = s * 0.4, s * 0.5
        bx0, by0 = cx - bw / 2, cy - bh / 2 + s * 0.05
        draw.rectangle([bx0, by0, bx0 + bw, by0 + bh], outline=color, width=w)
        for row in range(3):
            for col in range(2):
                wx0 = bx0 + bw * (0.18 + col * 0.46)
                wy0 = by0 + bh * (0.15 + row * 0.28)
                draw.rectangle([wx0, wy0, wx0 + bw * 0.18, wy0 + bh * 0.16], fill=color)


def render_threat_map_header_image(
    total_kept: int, counts: dict, sector: str, region_text: str, regulation_text: str, module_summary: str
) -> bytes:
    """
    counts: {"Critical": n, "High": n, "Med": n, "Dropped": n}.
    sector/region_text/regulation_text/module_summary: pre-formatted
    display strings for each stat tile (empty string hides that tile).
    """
    width = 1200
    pad = 56
    header_h = 56
    title_h = 64
    gap = 24
    bar_h = 16
    legend_h = 30
    tile_h = 100
    footer_h = 10

    subtitle = (
        "Generated from what you told us at sign-up — nothing to fill in, and it comes first: the threats decide "
        "which modules you need admins and teams for. Drop anything that doesn't apply, or change a criticality."
    )

    measure_img = Image.new("RGB", (10, 10))
    measure_draw = ImageDraw.Draw(measure_img)
    title_font = font(True, 48)
    subtitle_font = font(False, 22)
    subtitle_lines = wrap(measure_draw, subtitle, subtitle_font, width - pad * 2)

    tiles = [
        ("building", "SECTOR", sector),
        ("globe", "REGION", region_text),
        ("scales", "REGULATION", regulation_text),
        ("grid", "BY MODULE", module_summary),
    ]
    tiles = [t for t in tiles if t[2]]

    height = (
        pad + header_h + title_h + len(subtitle_lines) * 30 + gap
        + bar_h + 12 + legend_h + gap
        + (tile_h + gap if tiles else 0) + pad + footer_h
    )

    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)


    badge_text = "STEP 5 · ORGANIZATIONAL THREATS"
    badge_font = font(True, 16)
    badge_tw = draw.textlength(badge_text, font=badge_font)
    badge_w = badge_tw + 56
    badge_x0, badge_y0 = width - pad - badge_w, pad
    draw.rounded_rectangle([badge_x0, badge_y0, width - pad, badge_y0 + 40], radius=20, fill=(252, 225, 225))
    dot_cy = badge_y0 + 20
    draw.ellipse([badge_x0 + 20, dot_cy - 4, badge_x0 + 28, dot_cy + 4], fill=(150, 30, 40))
    draw.text((badge_x0 + 36, badge_y0 + 11), badge_text, font=badge_font, fill=(150, 30, 40))

    y = pad + header_h
    prefix = f"{total_kept} "
    suffix = "organizational threats"
    x = pad
    draw.text((x, y), prefix, font=title_font, fill=BRAND_RED)
    x += draw.textlength(prefix, font=title_font)
    draw.text((x, y), suffix, font=title_font, fill=INK)
    y += title_h

    for line in subtitle_lines:
        draw.text((pad, y), line, font=subtitle_font, fill=MUTED)
        y += 30
    y += gap

    total_bar = sum(counts.values()) or 1
    bar_x = pad
    bar_w_total = width - pad * 2
    for crit in ("Critical", "High", "Med", "Dropped"):
        n = counts.get(crit, 0)
        if n <= 0:
            continue
        seg_w = bar_w_total * n / total_bar
        draw.rectangle([bar_x, y, bar_x + seg_w, y + bar_h], fill=_SEVERITY_COLORS[crit])
        bar_x += seg_w
    y += bar_h + 12

    legend_font = font(True, 20)
    lx = pad
    for crit, label in (("Critical", "Critical"), ("High", "High"), ("Med", "Medium"), ("Dropped", "Dropped")):
        n = counts.get(crit, 0)
        text = f"{label} {n}"
        draw.ellipse([lx, y + 3, lx + 14, y + 17], fill=_SEVERITY_COLORS[crit])
        draw.text((lx + 22, y), text, font=legend_font, fill=INK)
        lx += draw.textlength(text, font=legend_font) + 22 + 28
    y += legend_h + gap

    if tiles:
        cols = len(tiles)
        gap_box = 20
        col_w = (width - pad * 2 - gap_box * (cols - 1)) // cols
        label_font = font(False, 13)
        value_font = font(True, 22)
        for i, (icon_key, label, value) in enumerate(tiles):
            bx = pad + i * (col_w + gap_box)
            draw.rounded_rectangle([bx, y, bx + col_w, y + tile_h], radius=14, fill=CARD_BG, outline=CARD_BORDER, width=2)
            icon_size = 28
            _draw_tile_icon(draw, bx + 18, y + 18, icon_size, icon_key)
            draw.text((bx + 18 + icon_size + 10, y + 24), label, font=label_font, fill=MUTED)
            vy = y + 54
            for line in wrap(draw, value, value_font, col_w - 36):
                draw.text((bx + 18, vy), line, font=value_font, fill=INK)
                vy += 26

    draw_footer_bar(draw, width, height, footer_h)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def get_threat_map_header_image_url(
    backend_url: str, total_kept: int, counts: dict, sector: str, region_text: str, regulation_text: str, module_summary: str
) -> str:
    # _TEMPLATE_VERSION + every piece of real data folded into the
    # cache key so a changed drawing or a changed threat profile both
    # bust the cache instead of silently reusing a stale image.
    key_source = "|".join([
        _TEMPLATE_VERSION, str(total_kept), str(sorted(counts.items())), sector, region_text, regulation_text, module_summary,
    ])
    key = hashlib.sha1(key_source.encode("utf-8")).hexdigest()[:20]
    filename = f"threatmaphdr_{key}.png"
    path = GENERATED_DIR / filename
    if not path.exists():
        path.write_bytes(render_threat_map_header_image(total_kept, counts, sector, region_text, regulation_text, module_summary))
    return f"{backend_url}/assets/generated/{filename}"
