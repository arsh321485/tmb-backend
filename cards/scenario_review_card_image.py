"""
Renders the Scenario Review screen's read-only content as one real
PNG -- the breadcrumb, the Approved pill, the "Phases, injects &
decisions" title, and every inject in the active phase (title, who
it's sent to, the message, the decision question, and its three
options with their Best/Partial/Poor rating badges). Same
template-code approach as the other cards.

Nothing on this screen is a per-item click target BEFORE a scenario
goes live -- this is the exercise lead reviewing the AI's draft output,
not the live drill itself (cards/ai_drill_v2.py fires the real
decisions later, with real clickable letter buttons, once this has
been approved). So the whole inject list here is safe to bake into one
image. Only the Phase tabs and the Approve/Continue/regenerate buttons
stay real Slack elements underneath it.

The "Consequences" tab (a packed, paginated list of consequence-only
injects) is NOT covered by this image -- it keeps its existing plain
text blocks, since its pagination logic is a separate concern from the
phase-by-phase inject review this image covers.
"""

import hashlib
import io

from PIL import Image, ImageDraw

from .card_image_common import (
    BG, BRAND_RED, CARD_BG, CARD_BORDER, GENERATED_DIR, INK, MUTED, TEAL,
    draw_footer_bar, font, wrap,
)

# Bump whenever render_scenario_review_image's drawing changes -- see
# get_scenario_review_image_url's cache-key comment below.
_TEMPLATE_VERSION = "v2"

_APPROVED_BG = (223, 241, 238)
_APPROVED_FG = TEAL

_RATING_COLORS = {
    "best": (TEAL, (255, 255, 255)),
    "partial": ((230, 180, 120), (255, 255, 255)),
    "poor": ((180, 178, 172), (255, 255, 255)),
}


def _rating_colors(rating: str):
    r = (rating or "").lower()
    if "best" in r or "good" in r:
        return _RATING_COLORS["best"]
    if "poor" in r or "bad" in r:
        return _RATING_COLORS["poor"]
    return _RATING_COLORS["partial"]


def render_scenario_review_image(
    breadcrumb_parts: list[tuple[str, str]], approved: bool, injects: list[dict]
) -> bytes:
    """
    breadcrumb_parts: [(label, value), ...] e.g. [("Threat", "SaaS API
    Misconfiguration/Exposure"), ("Incident", "..."), ("Cause", "...")].
    injects: [{"seq", "title", "phase", "role", "team_label", "message",
    "decision_question", "options": [{"rating","score","option_text"}]}].
    """
    width = 1200
    pad = 56
    gap = 24
    footer_h = 10

    measure_img = Image.new("RGB", (10, 10))
    measure_draw = ImageDraw.Draw(measure_img)
    crumb_font = font(False, 18)
    crumb_label_font = font(True, 12)

    title_font = font(True, 44)

    # Breadcrumb height (single line; it's short enough in practice).
    crumb_h = 26

    approved_pill_h = 32 if approved else 0

    row_pad_x, row_pad_y = 24, 20
    title_font_card = font(True, 22)
    meta_font = font(False, 15)
    msg_font = font(False, 19)
    prompt_font = font(True, 19)
    opt_font = font(False, 18)
    badge_font = font(True, 13)

    card_inner_w = width - pad * 2 - row_pad_x * 2

    def _inject_height(inj: dict) -> int:
        title_text = f"{inj.get('seq', '?')}. {inj.get('title', 'Untitled')}"
        title_lines = wrap(measure_draw, title_text, title_font_card, card_inner_w)
        msg_lines = wrap(measure_draw, inj.get("message", ""), msg_font, card_inner_w)
        prompt_lines = wrap(measure_draw, inj.get("decision_question", ""), prompt_font, card_inner_w)
        h = row_pad_y
        h += len(title_lines) * 28
        h += 20  # meta line
        h += len(msg_lines) * 26 + 10
        h += len(prompt_lines) * 26 + 10
        for opt in inj.get("options", []):
            opt_lines = wrap(measure_draw, opt.get("option_text", ""), opt_font, card_inner_w - 140)
            h += max(len(opt_lines), 1) * 24 + 8
        h += row_pad_y
        return h

    inject_heights = [_inject_height(inj) for inj in injects]

    height = (
        pad + crumb_h + gap + (approved_pill_h + 12 if approved else 0) + 56 + gap
        + sum(inject_heights) + gap * max(0, len(injects) - 1) + pad + footer_h
    )

    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)

    y = pad
    # Breadcrumb: "Label: Value  >  Label: Value  >  ..."
    x = pad
    for i, (label, value) in enumerate(breadcrumb_parts):
        if i > 0:
            draw.text((x, y), "  ›  ", font=crumb_font, fill=MUTED)
            x += draw.textlength("  ›  ", font=crumb_font)
        if label:
            label_text = f"{label}: "
            draw.text((x, y + 4), label_text, font=crumb_label_font, fill=MUTED)
            x += draw.textlength(label_text, font=crumb_label_font)
        draw.text((x, y), value, font=crumb_font, fill=INK)
        x += draw.textlength(value, font=crumb_font)

    if approved:
        pill_text = "Approved"
        pill_font = font(True, 15)
        pill_tw = draw.textlength(pill_text, font=pill_font)
        pill_w = pill_tw + 48
        pill_x0 = width - pad - pill_w
        draw.rounded_rectangle([pill_x0, y - 4, pill_x0 + pill_w, y - 4 + 28], radius=14, fill=_APPROVED_BG)
        cx, cy = pill_x0 + 18, y + 10
        draw.line([(cx - 5, cy), (cx - 1, cy + 4), (cx + 6, cy - 6)], fill=_APPROVED_FG, width=2)
        draw.text((pill_x0 + 28, y), pill_text, font=pill_font, fill=_APPROVED_FG)

    y += crumb_h + gap

    prefix = "Phases, injects & "
    tx = pad
    draw.text((tx, y), prefix, font=title_font, fill=INK)
    tx += draw.textlength(prefix, font=title_font)
    draw.text((tx, y), "decisions", font=title_font, fill=BRAND_RED)
    y += 56 + gap

    for inj, inj_h in zip(injects, inject_heights):
        draw.rounded_rectangle([pad, y, width - pad, y + inj_h], radius=14, fill=CARD_BG, outline=CARD_BORDER, width=2)
        cy = y + row_pad_y
        cx = pad + row_pad_x

        seq_text = f"{inj.get('seq', '?')}. "
        draw.text((cx, cy), seq_text, font=title_font_card, fill=BRAND_RED)
        seq_w = draw.textlength(seq_text, font=title_font_card)
        title_lines = wrap(draw, inj.get("title", "Untitled"), title_font_card, card_inner_w - seq_w)
        for i, line in enumerate(title_lines):
            draw.text((cx + (seq_w if i == 0 else 0), cy), line, font=title_font_card, fill=INK)
            cy += 28
        cy += 2

        meta_text = f"To: {inj.get('role', '?')}"
        if inj.get("team_label"):
            meta_text += f"  ·  {inj['team_label']}"
        draw.text((cx, cy), meta_text, font=meta_font, fill=MUTED)
        cy += 24

        for line in wrap(draw, inj.get("message", ""), msg_font, card_inner_w):
            draw.text((cx, cy), line, font=msg_font, fill=INK)
            cy += 26
        cy += 8

        for line in wrap(draw, inj.get("decision_question", ""), prompt_font, card_inner_w):
            draw.text((cx, cy), line, font=prompt_font, fill=INK)
            cy += 26
        cy += 8

        for opt in inj.get("options", []):
            rating = opt.get("rating", "")
            score = opt.get("score", "")
            badge_bg, badge_fg = _rating_colors(rating)
            badge_text = f"{rating.upper()} · {score}"
            badge_tw = draw.textlength(badge_text, font=badge_font)
            badge_w = badge_tw + 20
            badge_h = 22
            draw.rounded_rectangle([cx, cy, cx + badge_w, cy + badge_h], radius=5, fill=badge_bg)
            draw.text((cx + 10, cy + 4), badge_text, font=badge_font, fill=badge_fg)

            opt_lines = wrap(draw, opt.get("option_text", ""), opt_font, card_inner_w - badge_w - 16)
            oy = cy + 2
            for line in opt_lines or [""]:
                draw.text((cx + badge_w + 16, oy), line, font=opt_font, fill=INK)
                oy += 24
            cy += max(badge_h, len(opt_lines) * 24) + 8

        y += inj_h + gap

    draw_footer_bar(draw, width, height, footer_h)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def get_scenario_review_image_url(backend_url: str, breadcrumb_parts: list[tuple[str, str]], approved: bool, injects: list[dict]) -> str:
    # _TEMPLATE_VERSION + every piece of real data folded into the
    # cache key so a changed drawing or a changed scenario both bust
    # the cache instead of silently reusing a stale image.
    crumb_flat = ";".join(f"{l}:{v}" for l, v in breadcrumb_parts)
    inj_flat = ";".join(
        f"{i.get('seq')}:{i.get('title')}:{i.get('message')}:{i.get('decision_question')}:"
        + ",".join(f"{o.get('rating')}-{o.get('score')}-{o.get('option_text')}" for o in i.get("options", []))
        for i in injects
    )
    raw = f"{_TEMPLATE_VERSION}|{crumb_flat}|{int(approved)}|{inj_flat}"
    key = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]
    filename = f"scenarioreview_{key}.png"
    path = GENERATED_DIR / filename
    if not path.exists():
        path.write_bytes(render_scenario_review_image(breadcrumb_parts, approved, injects))
    return f"{backend_url}/assets/generated/{filename}"
