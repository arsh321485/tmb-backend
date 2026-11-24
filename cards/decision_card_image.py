"""
Renders sir's dark decision-card design as a real PNG -- logo,
"DECISION X OF Y" badge, phase tabs, the inject text, the question,
and every option's full text (each with its own A/B/C letter badge).
Posted as the top image block of a real AI decision DM
(cards/ai_drill_v2.py's _build_inject_card).

The live countdown ("Respond by ...") stays as real Slack text below
this image -- it's a live Slack date token that renders in each
viewer's own timezone, and a static image is the same bytes for
everyone, so it can never do that. The actual CLICK still has to be a
real Slack button (Slack can't pin a button to a spot inside a
picture), but since every option's full wording is already shown
inside the image, the buttons underneath only need to be the bare
letters -- A / B / C -- not the repeated option text.
"""

import hashlib
import io

from PIL import Image, ImageDraw

from .card_image_common import (
    BRAND_RED, BRAND_YELLOW, GENERATED_DIR, draw_footer_bar, font, wrap,
)

# Bump this whenever render_decision_card_image's drawing changes --
# see get_decision_card_image_url's cache-key comment below.
_TEMPLATE_VERSION = "v7"

_DARK_BG = (20, 20, 20)
_TAB_BG = (38, 38, 38)
_TAB_BORDER = (70, 70, 70)
_TAB_FG = (170, 170, 170)
_BODY_FG = (200, 200, 200)
_OPTION_BORDER = (60, 60, 60)
_WHITE = (255, 255, 255)
_BLACK = (20, 20, 20)

_LETTERS = "ABCDEFG"


def render_decision_card_image(
    phases: list[str], active_phase: str, decision_number: int, total_decisions: int,
    inject_message: str, decision_question: str, options: list[str],
) -> bytes:
    width = 1200
    pad = 56
    header_h = 56
    tabs_h = 60
    gap = 28
    option_gap = 16
    footer_h = 10

    measure_img = Image.new("RGB", (10, 10))
    measure_draw = ImageDraw.Draw(measure_img)
    body_font = font(False, 24)
    question_font = font(True, 36)
    option_font = font(False, 24)

    badge_col_w = 56
    option_text_w = width - pad * 2 - badge_col_w - 20

    body_lines = wrap(measure_draw, inject_message, body_font, width - pad * 2)
    question_lines = wrap(measure_draw, decision_question, question_font, width - pad * 2)

    option_lines_list = [wrap(measure_draw, opt, option_font, option_text_w) for opt in options]
    option_row_heights = [max(56, 24 + len(lines) * 30) for lines in option_lines_list]

    body_h = len(body_lines) * 32
    question_h = len(question_lines) * 46
    options_h = sum(option_row_heights) + option_gap * max(0, len(options) - 1)

    height = pad + header_h + tabs_h + gap + body_h + gap + question_h + gap + options_h + pad + footer_h

    img = Image.new("RGB", (width, height), _DARK_BG)
    draw = ImageDraw.Draw(img)


    badge_text = f"DECISION {decision_number} OF {total_decisions}"
    badge_font = font(True, 16)
    badge_tw = draw.textlength(badge_text, font=badge_font)
    badge_w = badge_tw + 56
    badge_x0, badge_y0 = width - pad - badge_w, pad
    draw.rounded_rectangle([badge_x0, badge_y0, width - pad, badge_y0 + 40], radius=20, fill=BRAND_RED)
    dot_cy = badge_y0 + 20
    draw.ellipse([badge_x0 + 20, dot_cy - 4, badge_x0 + 28, dot_cy + 4], fill=_WHITE)
    draw.text((badge_x0 + 36, badge_y0 + 11), badge_text, font=badge_font, fill=_WHITE)

    y = pad + header_h
    tab_font = font(True, 15)
    x = pad
    for phase in phases:
        is_active = phase == active_phase
        label = phase.upper()
        tw = draw.textlength(label, font=tab_font)
        tab_w = tw + 56
        if is_active:
            draw.rounded_rectangle([x, y, x + tab_w, y + 40], radius=20, fill=BRAND_RED)
            dot_color, fg = _WHITE, _WHITE
        else:
            draw.rounded_rectangle([x, y, x + tab_w, y + 40], radius=20, fill=_TAB_BG, outline=_TAB_BORDER, width=1)
            dot_color, fg = _TAB_FG, _TAB_FG
        dcy = y + 20
        draw.ellipse([x + 20, dcy - 4, x + 28, dcy + 4], fill=dot_color)
        draw.text((x + 36, y + 11), label, font=tab_font, fill=fg)
        x += tab_w + 16
    y += tabs_h + gap

    for line in body_lines:
        draw.text((pad, y), line, font=body_font, fill=_BODY_FG)
        y += 32
    y += gap

    for line in question_lines:
        draw.text((pad, y), line, font=question_font, fill=_WHITE)
        y += 46
    y += gap

    for i, opt in enumerate(options):
        rh = option_row_heights[i]
        draw.rounded_rectangle([pad, y, width - pad, y + rh], radius=12, outline=_OPTION_BORDER, width=1)
        badge_size = 32
        badge_y = y + (rh - badge_size) // 2
        draw.rounded_rectangle([pad + 16, badge_y, pad + 16 + badge_size, badge_y + badge_size], radius=6, fill=BRAND_YELLOW)
        letter = _LETTERS[i] if i < len(_LETTERS) else "?"
        lw = draw.textlength(letter, font=font(True, 18))
        draw.text((pad + 16 + (badge_size - lw) / 2, badge_y + 6), letter, font=font(True, 18), fill=_BLACK)
        tx = pad + 16 + badge_size + 20
        ty = y + (rh - len(option_lines_list[i]) * 30) // 2
        for line in option_lines_list[i]:
            draw.text((tx, ty), line, font=option_font, fill=_WHITE)
            ty += 30
        y += rh + option_gap

    draw_footer_bar(draw, width, height, footer_h)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def get_decision_card_image_url(
    backend_url: str, phases: list[str], active_phase: str, decision_number: int, total_decisions: int,
    inject_message: str, decision_question: str, options: list[str],
) -> str:
    # _TEMPLATE_VERSION folded into the cache key so a future design
    # change regenerates every image instead of keeping an
    # already-cached file from before the change.
    key_source = "|".join([
        _TEMPLATE_VERSION, ";".join(phases), active_phase, str(decision_number), str(total_decisions),
        inject_message, decision_question, ";".join(options),
    ])
    key = hashlib.sha1(key_source.encode("utf-8")).hexdigest()[:20]
    filename = f"decision_{key}.png"
    path = GENERATED_DIR / filename
    if not path.exists():
        data = render_decision_card_image(phases, active_phase, decision_number, total_decisions, inject_message, decision_question, options)
        path.write_bytes(data)
    return f"{backend_url}/assets/generated/{filename}"
