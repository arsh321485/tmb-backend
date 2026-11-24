"""
Renders sir's role-card design as a real PNG, filled in with each
person's own role/team/backup/activities -- not AI-generated (too slow
and another thing that can fail, for something sent constantly) and
not 150 hand-made picture files (can't be kept in sync, and still
wouldn't cover every team/backup combination). One template, drawn by
code (Pillow), in well under a second, same as drawing any other image
-- works for any role, any team, any number of roles, automatically.

Generated images are cached on disk under static_assets/generated/,
keyed by their own content, so re-sending the exact same role card
(same role, team, backup, activities) reuses the same file instead of
redrawing it.

Sir's rebrand (red/black/yellow "TMP" mark, pink highlight pills, red
checkmarks, red+yellow footer bar) -- the earlier teal/round-logo
version is gone; this is now the one live design.
"""

import hashlib
import io
import math

from PIL import Image, ImageDraw

from .card_image_common import (
    BG, BRAND_RED, CARD_BG, CARD_BORDER, GENERATED_DIR, INK, MUTED, PURPLE, TEAL, TEAL_BG,
    draw_footer_bar, font, wrap,
)

# Bump this whenever render_role_card_image's drawing changes -- see
# get_role_card_image_url's cache-key comment below.
_TEMPLATE_VERSION = "v14"

_HIGHLIGHT_BG = (253, 223, 223)


def render_role_card_image(
    role: str,
    module_label: str,
    backup_role_label: str,
    backup_name: str,
    responsibility: str,
    phase_activities: list[tuple[str, list[str]]],
) -> bytes:
    """
    phase_activities: [(phase_name, [activity, ...]), ...] -- one box
    per phase, up to 3 per row, matching the picture's layout.
    """
    width = 1200
    pad = 56
    gap = 24

    header_h = 56
    role_label_h = 34
    subtitle_h = 44
    role_font = font(True, 48)
    role_line_h = 58
    footer_h = 10

    cols = min(3, max(1, len(phase_activities))) if phase_activities else 0
    box_w = (width - pad * 2 - gap * (cols - 1)) // cols if cols else 0
    rows = math.ceil(len(phase_activities) / cols) if cols else 0

    measure_img = Image.new("RGB", (10, 10))
    measure_draw = ImageDraw.Draw(measure_img)
    act_font = font(True, 22)

    # Confirmed live: a long role name ("Designated CERT-In Point of
    # Contact") only ever drew the FIRST wrapped line and silently
    # dropped the rest ("Contact" vanished). Wrap it onto up to 2 real
    # lines instead, sized into the card's own height below, so nothing
    # gets cut off -- the role title row starts below the
    # Primary/Backup box (not beside it), so it can use the full card
    # width, not a narrower one.
    role_lines = wrap(measure_draw, role, role_font, width - pad * 2 - 20)[:2]
    role_name_h = role_line_h * max(1, len(role_lines)) + 24

    row_heights: list[int] = []
    for r in range(rows):
        chunk = phase_activities[r * cols: (r + 1) * cols]
        max_lines = 0
        for _, acts in chunk:
            # +34 per activity reserves room for the checkbox icon's
            # own left indent, same width budget as role_card_image's
            # plain-text version used before the icon was added.
            lines = sum(len(wrap(measure_draw, a, act_font, box_w - 48 - 34)) for a in acts)
            max_lines = max(max_lines, lines)
        row_heights.append(60 + max_lines * 30 + 24)

    resp_lines = wrap(measure_draw, responsibility, font(True, 24), width - pad * 2 - 70) if responsibility else []
    resp_h = (len(resp_lines[:2]) * 32 + 36) if resp_lines else 0
    activities_label_h = 40 if phase_activities else 0
    boxes_h = sum(row_heights) + gap * max(0, rows - 1)

    height = pad + header_h + role_label_h + role_name_h + subtitle_h + gap + resp_h + activities_label_h + boxes_h + pad + footer_h

    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)


    # "YOUR ROLE" pill, above the Primary/Backup box -- same teal badge
    # style the Welcome card still uses (unlike the logo/pills/footer,
    # which moved to red/black/yellow).
    box_w2 = 240
    box_x = width - pad - box_w2
    pill_text = "YOUR ROLE"
    pill_font = font(True, 16)
    pill_tw = draw.textlength(pill_text, font=pill_font)
    pill_w = pill_tw + 56
    pill_x0 = box_x + box_w2 - pill_w
    draw.rounded_rectangle([pill_x0, pad, box_x + box_w2, pad + 36], radius=18, fill=TEAL_BG)
    dot_cy = pad + 18
    draw.ellipse([pill_x0 + 16, dot_cy - 4, pill_x0 + 24, dot_cy + 4], fill=TEAL)
    draw.text((pill_x0 + 32, pad + 9), pill_text, font=pill_font, fill=TEAL)

    # Primary/Backup box, below the pill -- rounded-square avatar
    # (not a circle), matching sir's updated design.
    box_y = pad + 46
    draw.rounded_rectangle([box_x, box_y, box_x + box_w2, box_y + 90], radius=14, fill=CARD_BG, outline=CARD_BORDER, width=1)
    draw.text((box_x + 18, box_y + 14), backup_role_label.upper(), font=font(True, 15), fill=MUTED)
    avatar_color = PURPLE if backup_role_label.upper() == "BACKUP" else TEAL
    draw.rounded_rectangle([box_x + 18, box_y + 42, box_x + 58, box_y + 82], radius=10, fill=avatar_color)
    initial = (backup_name or "?").strip()[:1].upper() or "?"
    draw.text((box_x + 30, box_y + 50), initial, font=font(True, 22), fill=(255, 255, 255))
    draw.text((box_x + 70, box_y + 52), (backup_name or "—")[:22], font=font(True, 22), fill=INK)

    y = pad + header_h
    draw.text((pad, y), "ROLE", font=font(True, 16), fill=MUTED)
    y += role_label_h
    line_y = y
    for line in role_lines or [role]:
        draw.text((pad, line_y), line, font=role_font, fill=INK)
        line_y += role_line_h
    y += role_name_h
    draw.text((pad, y), module_label, font=font(False, 26), fill=MUTED)
    y += subtitle_h + gap

    if resp_lines:
        # Red stylized quote mark instead of the old plain vertical bar.
        quote_font = font(True, 64)
        draw.text((pad - 4, y - 18), "“", font=quote_font, fill=BRAND_RED)
        line_y = y
        for line in resp_lines[:2]:
            draw.text((pad + 46, line_y), line, font=font(True, 24), fill=INK)
            line_y += 32
        y += resp_h

    if phase_activities:
        draw.text((pad, y), "YOUR ACTIVITIES IN A DRILL", font=font(True, 16), fill=MUTED)
        y += activities_label_h

        for r in range(rows):
            chunk = phase_activities[r * cols: (r + 1) * cols]
            rh = row_heights[r]
            for i, (phase, acts) in enumerate(chunk):
                bx = pad + i * (box_w + gap)
                draw.rounded_rectangle([bx, y, bx + box_w, y + rh], radius=14, fill=CARD_BG, outline=CARD_BORDER, width=1)
                pill_font = font(True, 15)
                pill_text = phase.upper()
                pill_w = draw.textlength(pill_text, font=pill_font)
                draw.rounded_rectangle([bx + 16, y + 14, bx + 16 + pill_w + 20, y + 40], radius=12, fill=_HIGHLIGHT_BG)
                draw.text((bx + 26, y + 18), pill_text, font=pill_font, fill=BRAND_RED)
                ay = y + 52
                for a in acts:
                    lines = wrap(draw, a, act_font, box_w - 48 - 34)
                    # Small red checkbox (rounded square + white check)
                    # beside the first line of each activity, replacing
                    # the old plain bullet-less text.
                    draw.rounded_rectangle([bx + 16, ay + 2, bx + 32, ay + 18], radius=4, fill=BRAND_RED)
                    draw.line([(bx + 19, ay + 10), (bx + 23, ay + 14)], fill=(255, 255, 255), width=2)
                    draw.line([(bx + 23, ay + 14), (bx + 29, ay + 6)], fill=(255, 255, 255), width=2)
                    for line in lines:
                        draw.text((bx + 42, ay), line, font=act_font, fill=INK)
                        ay += 30
            y += rh + gap

    draw_footer_bar(draw, width, height, footer_h)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def get_role_card_image_url(
    backend_url: str,
    role: str,
    module_label: str,
    backup_role_label: str,
    backup_name: str,
    responsibility: str,
    phase_activities: list[tuple[str, list[str]]],
) -> str:
    # _TEMPLATE_VERSION is folded into the cache key so a design change
    # (new element, repositioned box, ...) regenerates every image
    # instead of silently keeping everyone's existing cached file from
    # before the change -- confirmed live: the accent-bar fix didn't
    # show up for a role already cached from an earlier version, since
    # the key only covered the DATA, not the drawing code. Bump this
    # whenever render_role_card_image's actual drawing changes.
    key_source = "|".join([
        _TEMPLATE_VERSION, role, module_label, backup_role_label, backup_name or "", responsibility or "",
        ";".join(f"{phase}:{','.join(acts)}" for phase, acts in phase_activities),
    ])
    key = hashlib.sha1(key_source.encode("utf-8")).hexdigest()[:20]
    filename = f"role_{key}.png"
    path = GENERATED_DIR / filename
    if not path.exists():
        data = render_role_card_image(role, module_label, backup_role_label, backup_name, responsibility, phase_activities)
        path.write_bytes(data)
    return f"{backend_url}/assets/generated/{filename}"
