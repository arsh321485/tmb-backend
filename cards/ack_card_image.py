"""
Renders sir's "One last step" acknowledge-confirmation design as a
real PNG -- same template-image approach as welcome_card_image.py /
role_card_image.py: mostly-static layout, filled in with the real
role, team and person's name, drawn by code in well under a second.

The sentence highlights the role and team inline (yellow text on the
dark background) -- render_ack_card_image takes the sentence as
(text, highlighted) chunks instead of one flat string, so the caller
decides exactly what gets highlighted without this module needing to
know anything about role/team text itself.

Sir's rebrand: dark background, yellow highlight (not a pink box),
outlined badge pill, red signature line, red+yellow footer bar.
"""

import hashlib
import io
import re

from PIL import Image, ImageDraw

from .card_image_common import (
    BRAND_RED, BRAND_YELLOW, GENERATED_DIR,
    draw_footer_bar, font,
)

# Bump this whenever render_ack_card_image's drawing changes -- see
# get_ack_card_image_url's cache-key comment below.
_TEMPLATE_VERSION = "v9"

_DARK_BG = (20, 20, 20)
_WHITE = (255, 255, 255)


def _split_words(sentence_parts: list[tuple[str, bool]]) -> list[tuple[str, bool]]:
    """
    Tokenizes across chunk boundaries, not within each chunk
    separately -- splitting each chunk on its own ran into a real bug
    where a chunk starting right on a punctuation mark (e.g.
    ". I've reviewed...", directly after a highlighted chunk with no
    space) produced "." as its own standalone word, which then got a
    forced space inserted before it like every other word -- rendering
    as "Infrastructure ." instead of "Infrastructure.". Concatenating
    first and tokenizing on whitespace across the whole sentence
    tokenizes it the same way a reader would, so punctuation stays
    attached to the word it belongs to.
    """
    full = ""
    ranges: list[tuple[int, int, bool]] = []
    for text, highlighted in sentence_parts:
        start = len(full)
        full += text
        ranges.append((start, len(full), highlighted))

    words: list[tuple[str, bool]] = []
    for m in re.finditer(r"\S+", full):
        word_start = m.start()
        highlighted = any(r_start <= word_start < r_end and hl for r_start, r_end, hl in ranges)
        words.append((m.group(), highlighted))
    return words


def render_ack_card_image(sentence_parts: list[tuple[str, bool]], recipient_name: str) -> bytes:
    """
    sentence_parts: [(text_chunk, highlighted), ...] -- consecutive
    chunks that make up the full confirmation sentence, each either
    plain (white) or highlighted (yellow).
    """
    width = 1200
    pad = 56
    header_h = 56
    text_font_size = 34
    line_h = 50
    sig_gap = 56
    sig_h = 50
    footer_h = 10

    text_font = font(True, text_font_size)

    measure_img = Image.new("RGB", (10, 10))
    measure_draw = ImageDraw.Draw(measure_img)
    space_w = measure_draw.textlength(" ", font=text_font)
    max_width = width - pad * 2

    words = _split_words(sentence_parts)
    lines: list[list[tuple[str, bool]]] = []
    current: list[tuple[str, bool]] = []
    current_w = 0.0
    for word, hl in words:
        ww = measure_draw.textlength(word, font=text_font)
        extra = space_w if current else 0
        if current and current_w + extra + ww > max_width:
            lines.append(current)
            current, current_w = [], 0.0
        current.append((word, hl))
        current_w += (space_w if len(current) > 1 else 0) + ww
    if current:
        lines.append(current)

    paragraph_h = line_h * len(lines)
    height = pad + header_h + paragraph_h + sig_gap + sig_h + pad + footer_h

    img = Image.new("RGB", (width, height), _DARK_BG)
    draw = ImageDraw.Draw(img)


    badge_text = "ONE LAST STEP"
    badge_font = font(True, 16)
    badge_tw = draw.textlength(badge_text, font=badge_font)
    badge_w = badge_tw + 56
    badge_x0, badge_y0 = width - pad - badge_w, pad
    draw.rounded_rectangle([badge_x0, badge_y0, width - pad, badge_y0 + 40], radius=20, outline=(70, 70, 70), width=1)
    dot_cy = badge_y0 + 20
    draw.ellipse([badge_x0 + 20, dot_cy - 4, badge_x0 + 28, dot_cy + 4], fill=BRAND_YELLOW)
    draw.text((badge_x0 + 36, badge_y0 + 11), badge_text, font=badge_font, fill=BRAND_YELLOW)

    y = pad + header_h
    for line in lines:
        x = pad
        for word, hl in line:
            ww = draw.textlength(word, font=text_font)
            draw.text((x, y), word, font=text_font, fill=BRAND_YELLOW if hl else _WHITE)
            x += ww + space_w
        y += line_h

    y += sig_gap
    sig_line_y = y + sig_h // 2
    draw.line([(pad, sig_line_y), (pad + 70, sig_line_y)], fill=BRAND_RED, width=2)
    draw.text((pad + 90, y), recipient_name, font=font(True, 28), fill=_WHITE)

    draw_footer_bar(draw, width, height, footer_h)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def get_ack_card_image_url(backend_url: str, sentence_parts: list[tuple[str, bool]], recipient_name: str) -> str:
    # _TEMPLATE_VERSION folded into the cache key so a future design
    # change regenerates every image instead of keeping someone's
    # already-cached file from before the change.
    key_source = "|".join([
        _TEMPLATE_VERSION, recipient_name,
        ";".join(f"{text}:{int(hl)}" for text, hl in sentence_parts),
    ])
    key = hashlib.sha1(key_source.encode("utf-8")).hexdigest()[:20]
    filename = f"ack_{key}.png"
    path = GENERATED_DIR / filename
    if not path.exists():
        data = render_ack_card_image(sentence_parts, recipient_name)
        path.write_bytes(data)
    return f"{backend_url}/assets/generated/{filename}"
