"""
Renders the "file uploaded and read successfully" / services-with-RTO
design as one real PNG -- logo+badge, a bordered file-info box
(filename + uploaded checkmark), the big "Found N services with an
RTO" title, the numbered services table (urgency-colored RTO pills),
and the trailing status note. Same template-code approach as the
other cards. One combined image, not split -- sir's call, matching the
same single-image choice made for the Threat Profile card.

All actions ("Want to change the file?", "Continue to Teams",
"Review & confirm", "Check again", ...) stay real Slack buttons
underneath this image -- not baked in, same reasoning as every other
card with a genuine click target.
"""

import hashlib
import io
import re

from PIL import Image, ImageDraw

from .card_image_common import (
    BG, CARD_BG, CARD_BORDER, GENERATED_DIR, INK, MUTED,
    draw_footer_bar, font, wrap,
)

# Bump whenever render_bia_services_card_image's drawing changes -- see
# get_bia_services_card_image_url's cache-key comment below.
_TEMPLATE_VERSION = "v12"

_ROW_H = 46

_TIER_COLORS = {
    "urgent": ((250, 221, 221), (190, 40, 50)),
    "warn": ((250, 233, 210), (180, 110, 30)),
    "calm": (None, INK),  # None fill -> drawn as a plain outlined pill
}


def _draw_file_icon(draw: ImageDraw.ImageDraw, x0: int, y0: int, size: int, is_ai_draft: bool = False) -> None:
    s = size
    color = (166, 90, 36) if is_ai_draft else (26, 110, 90)
    fold_color = (214, 150, 90) if is_ai_draft else (70, 160, 140)
    fold = s * 0.3
    draw.polygon(
        [(x0 + s * 0.2, y0), (x0 + s * 0.8 - fold, y0), (x0 + s * 0.8, y0 + fold),
         (x0 + s * 0.8, y0 + s), (x0 + s * 0.2, y0 + s)],
        fill=color,
    )
    draw.polygon([(x0 + s * 0.8 - fold, y0), (x0 + s * 0.8, y0 + fold), (x0 + s * 0.8 - fold, y0 + fold)], fill=fold_color)


def render_bia_services_card_image(
    filename: str, found_text: str, rows: list[tuple[str, str, str]], overflow_count: int, status_note: str, is_ai_draft: bool = False
) -> bytes:
    """
    found_text: e.g. "Found 6 services with an RTO" (a real upload) or
    "We drafted 6 services for you" (an AI-generated draft) -- the
    number of services is rendered in red, the rest in black.
    rows: [(name, rto, tier), ...] -- tier is "urgent"/"warn"/"calm",
    already sorted/budgeted by the caller.
    overflow_count: how many more services exist but aren't shown.
    status_note: the plain line shown after the table.
    is_ai_draft: an AI-generated draft was never actually uploaded by a
    person, so the badge, file-box status and footer icon all say so
    plainly instead of claiming a real upload happened.
    """
    width = 1200
    pad = 56
    header_h = 56
    file_box_h = 76
    gap = 24
    colhead_h = 28
    footer_h = 10

    measure_img = Image.new("RGB", (10, 10))
    measure_draw = ImageDraw.Draw(measure_img)
    title_font = font(True, 40)
    title_lines = wrap(measure_draw, found_text, title_font, width - pad * 2)

    note_font = font(False, 20)
    note_lines = wrap(measure_draw, status_note, note_font, width - pad * 2 - 30)

    rows_h = len(rows) * _ROW_H
    overflow_h = 30 if overflow_count else 0

    height = (
        pad + header_h + file_box_h + gap + len(title_lines) * 50 + gap
        + colhead_h + rows_h + overflow_h + gap + len(note_lines) * 26 + pad + footer_h
    )

    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)


    # Filled badge -- pink "STEP 3 · UPLOAD" for a real upload, tan
    # "DRAFT · NOT UPLOADED" for an AI-generated draft (sir's call: a
    # draft never actually went through the upload step, so the badge
    # shouldn't claim it did).
    badge_text = "DRAFT · NOT UPLOADED" if is_ai_draft else "STEP 3 · UPLOAD"
    badge_bg, badge_fg = ((250, 224, 213), (150, 62, 22)) if is_ai_draft else ((252, 225, 225), (150, 30, 40))
    badge_font = font(True, 16)
    badge_tw = draw.textlength(badge_text, font=badge_font)
    badge_w = badge_tw + 56
    badge_x0, badge_y0 = width - pad - badge_w, pad
    draw.rounded_rectangle([badge_x0, badge_y0, width - pad, badge_y0 + 40], radius=20, fill=badge_bg)
    dot_cy = badge_y0 + 20
    draw.ellipse([badge_x0 + 20, dot_cy - 4, badge_x0 + 28, dot_cy + 4], fill=badge_fg)
    draw.text((badge_x0 + 36, badge_y0 + 11), badge_text, font=badge_font, fill=badge_fg)

    y = pad + header_h
    draw.rounded_rectangle([pad, y, width - pad, y + file_box_h], radius=14, fill=CARD_BG, outline=CARD_BORDER, width=2)
    icon_size = 32
    icon_x, icon_y = pad + 20, y + (file_box_h - icon_size) // 2
    _draw_file_icon(draw, icon_x, icon_y, icon_size, is_ai_draft)
    name_font = font(True, 22)
    draw.text((icon_x + icon_size + 16, y + 16), filename, font=name_font, fill=INK)
    status_font = font(False, 17)
    if is_ai_draft:
        draw.text((icon_x + icon_size + 16, y + 44), "A researched draft — not a document you uploaded", font=status_font, fill=(150, 62, 22))
    else:
        check_color = (26, 140, 90)
        check_x, check_y = icon_x + icon_size + 16, y + 48
        # Drawn as real lines, not a Unicode checkmark glyph -- the font
        # doesn't have that glyph and renders it as a tofu box instead
        # (same issue found and fixed on the file-type chips earlier).
        draw.line([(check_x, check_y + 4), (check_x + 4, check_y + 8), (check_x + 11, check_y - 2)], fill=check_color, width=2)
        draw.text((check_x + 20, y + 44), "Uploaded and read successfully", font=status_font, fill=check_color)
    y += file_box_h + gap

    # "N services" (the count) drawn in red; the rest of the title in
    # black -- only the first wrapped line can contain that phrase.
    red_match = re.search(r"\d+\s+services", title_lines[0]) if title_lines else None
    for li, line in enumerate(title_lines):
        ty = y + li * 50
        if li == 0 and red_match:
            pre, red_part, post = line[: red_match.start()], line[red_match.start() : red_match.end()], line[red_match.end() :]
            x = pad
            draw.text((x, ty), pre, font=title_font, fill=INK)
            x += draw.textlength(pre, font=title_font)
            draw.text((x, ty), red_part, font=title_font, fill=(211, 30, 40))
            x += draw.textlength(red_part, font=title_font)
            draw.text((x, ty), post, font=title_font, fill=INK)
        else:
            draw.text((pad, ty), line, font=title_font, fill=INK)
    y += len(title_lines) * 50 + gap

    colhead_font = font(True, 14)
    draw.text((pad, y), "#", font=colhead_font, fill=MUTED)
    draw.text((pad + 40, y), "SERVICE", font=colhead_font, fill=MUTED)
    # Right-aligned to the same right edge the RTO pills use below
    # (width - pad), not a fixed offset -- that's what was misaligning
    # the header from the pills.
    rto_head_tw = draw.textlength("RTO", font=colhead_font)
    draw.text((width - pad - rto_head_tw, y), "RTO", font=colhead_font, fill=MUTED)
    y += colhead_h
    draw.line([(pad, y), (width - pad, y)], fill=CARD_BORDER, width=1)

    name_font = font(True, 20)
    num_font = font(False, 16)
    rto_font = font(True, 16)
    for i, (name, rto, tier) in enumerate(rows, 1):
        row_y = y + 10
        draw.text((pad, row_y + 4), f"{i:02d}", font=num_font, fill=MUTED)
        draw.text((pad + 40, row_y), name, font=name_font, fill=INK)

        rto_tw = draw.textlength(rto, font=rto_font)
        pill_w = rto_tw + 28
        pill_h = 30
        pill_x0 = width - pad - pill_w
        pill_y0 = row_y - 2
        bg, fg = _TIER_COLORS.get(tier, (None, INK))
        if bg is not None:
            draw.rounded_rectangle([pill_x0, pill_y0, pill_x0 + pill_w, pill_y0 + pill_h], radius=pill_h // 2, fill=bg)
        else:
            draw.rounded_rectangle([pill_x0, pill_y0, pill_x0 + pill_w, pill_y0 + pill_h], radius=pill_h // 2, outline=CARD_BORDER, width=2)
        draw.text((pill_x0 + 14, pill_y0 + 6), rto, font=rto_font, fill=fg)

        y += _ROW_H
        if i < len(rows):
            draw.line([(pad, y - 2), (width - pad, y - 2)], fill=(240, 238, 233), width=1)

    if overflow_count:
        draw.text((pad, y + 4), f"+ {overflow_count} more, used in ranking but not shown here", font=font(False, 16), fill=MUTED)
        y += overflow_h

    y += gap
    if is_ai_draft:
        # Small checklist icon, matching the "10 quick questions" note's
        # meaning (a confirm step), instead of the plain-upload eye icon.
        list_x, list_y = pad, y + 4
        for i in range(3):
            ly = list_y + i * 5
            draw.line([(list_x, ly), (list_x + 3, ly)], fill=INK, width=2)
            draw.line([(list_x + 7, ly), (list_x + 15, ly)], fill=INK, width=2)
        icon_w = 20 + 12
    else:
        eye_r = 9
        draw.ellipse([pad, y + 3, pad + eye_r * 2, y + 3 + eye_r], outline=(190, 40, 50), width=2)
        draw.ellipse([pad + eye_r - 3, y + 3 + eye_r / 2 - 3, pad + eye_r + 3, y + 3 + eye_r / 2 + 3], fill=(190, 40, 50))
        icon_w = eye_r * 2 + 12
    for line in note_lines:
        draw.text((pad + icon_w, y), line, font=note_font, fill=INK)
        y += 26

    draw_footer_bar(draw, width, height, footer_h)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def get_bia_services_card_image_url(
    backend_url: str, filename: str, found_text: str, rows: list[tuple[str, str, str]], overflow_count: int, status_note: str, is_ai_draft: bool = False
) -> str:
    # _TEMPLATE_VERSION + every piece of real data folded into the
    # cache key so a changed document or a changed drawing both bust
    # the cache instead of silently reusing a stale image.
    flat = ";".join(f"{n}:{r}:{t}" for n, r, t in rows)
    raw = f"{_TEMPLATE_VERSION}|{filename}|{found_text}|{flat}|{overflow_count}|{status_note}|{int(is_ai_draft)}"
    key = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]
    filename_out = f"biasvc_{key}.png"
    path = GENERATED_DIR / filename_out
    if not path.exists():
        path.write_bytes(render_bia_services_card_image(filename, found_text, rows, overflow_count, status_note, is_ai_draft))
    return f"{backend_url}/assets/generated/{filename_out}"
