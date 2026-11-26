"""
Shared drawing pieces for every template-rendered card image (role_card_image.py,
welcome_card_image.py, ...) -- same fonts, colors and the decorative
header circles, so every card image stays visually consistent instead
of each file redefining its own slightly-different copy.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

STATIC_ASSETS_DIR = Path(__file__).parent / "static_assets"
GENERATED_DIR = STATIC_ASSETS_DIR / "generated"
GENERATED_DIR.mkdir(parents=True, exist_ok=True)

_FONT_DIR = Path(__file__).parent / "static_assets" / "fonts"
_REGULAR_FONT = "LiberationSans-Regular.ttf"
_BOLD_FONT = "LiberationSans-Bold.ttf"

BG = (250, 248, 245)
INK = (17, 24, 28)
MUTED = (110, 118, 125)
TEAL = (14, 110, 105)
TEAL_BG = (223, 241, 238)
# Brighter accent used only for the footer bar's middle segment -- sir's
# call: the dark TEAL above (used elsewhere for badges/checkmarks) read
# as too dark there; this lighter turquoise is the closest match to the
# reference color he pointed at.
FOOTER_TEAL = (74, 199, 183)
CARD_BG = (255, 255, 255)
CARD_BORDER = (225, 222, 216)
PURPLE = (124, 103, 196)
LOGO_RED = (230, 90, 70)
CIRCLE_LINE = (233, 229, 221)

# Sir's rebrand -- the live "TMP" mark (red/black/yellow) and the
# red+yellow footer bar every card now ends on, replacing the earlier
# round teal logo and left-edge accent bar.
BRAND_RED = (211, 30, 40)
BRAND_BLACK = (20, 20, 20)
BRAND_YELLOW = (247, 181, 0)


def font(bold: bool, size: int) -> ImageFont.FreeTypeFont:
    name = _BOLD_FONT if bold else _REGULAR_FONT
    try:
        return ImageFont.truetype(str(_FONT_DIR / name), size)
    except OSError:
        # Font files aren't guaranteed to exist outside this Windows dev
        # box -- falls back to Pillow's built-in bitmap font rather than
        # crashing image generation entirely.
        return ImageFont.load_default()


def wrap(draw: ImageDraw.ImageDraw, text: str, text_font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=text_font) <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def draw_wordmark(draw: ImageDraw.ImageDraw, pad: int) -> None:
    """Top-left "TestMyPlan" logo mark -- the OLD round teal mark.
    Superseded by draw_tmp_logo (sir's rebrand); kept only in case
    something still references the old look."""
    draw.rounded_rectangle([pad, pad, pad + 44, pad + 44], radius=10, fill=LOGO_RED)
    draw.ellipse([pad + 10, pad + 10, pad + 34, pad + 34], outline=(255, 255, 255), width=3)
    draw.ellipse([pad + 17, pad + 17, pad + 27, pad + 27], fill=(255, 255, 255))
    draw.text((pad + 56, pad + 8), "TestMyPlan", font=font(True, 26), fill=INK)


def tmp_font(size: int) -> ImageFont.FreeTypeFont:
    """Verdana Bold -- closest wide/rounded match on this system to
    sir's reference "TMP" lettering. Used only for the logo mark
    itself; every other font on a card stays the normal font() above."""
    try:
        return ImageFont.truetype(str(_FONT_DIR / "verdanab.ttf"), size)
    except OSError:
        return font(True, size)


# Exact brand-guideline values for the logo mark specifically (page 3)
# -- kept separate from BRAND_RED/BRAND_YELLOW above, which are the UI
# accent colors used elsewhere on a card and are intentionally
# different shades from the logo tile itself per the guideline's own
# color page (Signal Coral #F14F44 for UI vs the logo tile's #E2000F).
_LOGO_TILE_RED = (226, 0, 15)
_LOGO_TAG_YELLOW = (255, 198, 14)
_LOGO_TAG_INK = (26, 26, 26)


def _rounded_corner_mask(box_w: int, box_h: int, r_tl: int, r_tr: int, r_bl: int, r_br: int) -> Image.Image:
    """An L-mode mask, opaque everywhere except the 4 corners outside
    each one's own quarter-circle radius -- lets a tile use a
    DIFFERENT radius per corner, which plain rounded_rectangle (one
    radius for all 4) can't do."""
    mask = Image.new("L", (box_w, box_h), 255)
    mdraw = ImageDraw.Draw(mask)
    if r_tl > 0:
        mdraw.rectangle([0, 0, r_tl, r_tl], fill=0)
        mdraw.pieslice([0, 0, 2 * r_tl, 2 * r_tl], 180, 270, fill=255)
    if r_tr > 0:
        mdraw.rectangle([box_w - r_tr, 0, box_w, r_tr], fill=0)
        mdraw.pieslice([box_w - 2 * r_tr, 0, box_w, 2 * r_tr], 270, 360, fill=255)
    if r_bl > 0:
        mdraw.rectangle([0, box_h - r_bl, r_bl, box_h], fill=0)
        mdraw.pieslice([0, box_h - 2 * r_bl, 2 * r_bl, box_h], 90, 180, fill=255)
    if r_br > 0:
        mdraw.rectangle([box_w - r_br, box_h - r_br, box_w, box_h], fill=0)
        mdraw.pieslice([box_w - 2 * r_br, box_h - 2 * r_br, box_w, box_h], 0, 90, fill=255)
    return mask


def draw_tmp_logo(img: Image.Image, draw: ImageDraw.ImageDraw, pad: int, wordmark_color: tuple = BRAND_BLACK) -> int:
    """Sir's rebrand mark, drawn to the exact brand-guideline spec
    (page 3): red #E2000F tile, corners 15% top-left / 6% top-right /
    11% bottom-left / square bottom-right, white "TMP" monogram, a
    yellow #FFC60E "Prepared" tag (70% x 23% of the tile) flush to the
    tile's own square bottom-right corner, "TestMyPlan" wordmark
    beside it. wordmark_color lets a dark-background card (e.g. the
    "One last step" screen) show it in white instead of the default
    black, which would be invisible there. Takes the Image itself (not
    just its ImageDraw) because per-corner rounding needs to paste a
    separately-masked tile, not just draw shapes. Returns the logo
    block's bottom y, so the caller knows how much vertical space it
    actually used.

    Disabled per request: logo removed from all cards. Returns pad
    (zero height used) so every caller's existing layout math still
    works, just with no logo drawn."""
    return pad
    box_w, box_h = 76, 70
    r_tl, r_tr, r_bl, r_br = int(box_w * 0.15), int(box_w * 0.06), int(box_w * 0.11), 0

    tile = Image.new("RGBA", (box_w, box_h), (*_LOGO_TILE_RED, 255))
    tile.putalpha(_rounded_corner_mask(box_w, box_h, r_tl, r_tr, r_bl, r_br))
    img.paste(tile, (pad, pad), tile)

    tmp_text_font = tmp_font(30)
    tw = draw.textlength("TMP", font=tmp_text_font)
    draw.text((pad + (box_w - tw) / 2, pad + 10), "TMP", font=tmp_text_font, fill=(255, 255, 255))

    # Tag -- 70% x 23% of the tile, flush to its square bottom-right
    # corner (the one corner the tile itself leaves unrounded).
    ribbon_w, ribbon_h = int(box_w * 0.70), int(box_h * 0.23)
    ribbon_x0 = pad + box_w - ribbon_w
    ribbon_y0 = pad + box_h - ribbon_h
    draw.rectangle([ribbon_x0, ribbon_y0, ribbon_x0 + ribbon_w, ribbon_y0 + ribbon_h], fill=_LOGO_TAG_YELLOW)
    ribbon_font = font(True, 12)
    rw = draw.textlength("Prepared", font=ribbon_font)
    draw.text((ribbon_x0 + (ribbon_w - rw) / 2, ribbon_y0 + 3), "Prepared", font=ribbon_font, fill=_LOGO_TAG_INK)

    draw.text((pad + box_w + 16, pad + (box_h - 28) / 2), "TestMyPlan", font=font(True, 26), fill=wordmark_color)
    return pad + box_h


def draw_footer_bar(draw: ImageDraw.ImageDraw, width: int, height: int, footer_h: int = 10) -> None:
    """Full-width red / teal / red footer bar along the very bottom
    edge -- replaces the old left-edge accent bar in sir's rebrand.
    Three segments (red, then teal, then red again), not a two-tone
    split. Middle segment changed from yellow to teal per sir's call."""
    y0 = height - footer_h
    mid_start = int(width * 0.73)
    mid_end = int(width * 0.88)
    draw.rectangle([0, y0, mid_start, height], fill=BRAND_RED)
    draw.rectangle([mid_start, y0, mid_end, height], fill=FOOTER_TEAL)
    draw.rectangle([mid_end, y0, width, height], fill=BRAND_RED)


def draw_decorative_header_circles(width: int, header_h: int, cx: int, cy: int, fill_color: tuple = TEAL_BG) -> Image.Image:
    """
    Returns a (width x header_h) strip with the two outline rings + one
    filled circle, meant to be pasted at (0, 0) onto the real card
    before anything else is drawn. Drawn onto its own strip (not
    directly onto the full card) so it's always clipped to the header
    band and can never bleed into the content below it, no matter how
    tall or short the rest of that particular card ends up being.
    """
    # The two thin outline rings are meant to bleed off the edge of the
    # frame (sir's design -- a large, soft decorative shape, not a
    # contained icon), so they keep their original big radii and are
    # allowed to clip at the band's edges. The one thing that genuinely
    # needs to stay a real, uncut circle is the solid FILLED one --
    # confirmed live, that one used to be a non-square bounding box
    # (rendered as an oval) and got sliced by the header band's bottom
    # edge. Its radius is capped against the real header_h so it always
    # stays a full circle with a visible margin, regardless of what
    # header_h a particular card uses; the rings stay as striking,
    # intentionally oversized background shapes.
    filled_r = max(10, min(cy, header_h - cy) - 12)

    band = Image.new("RGB", (width, header_h), BG)
    band_draw = ImageDraw.Draw(band)
    band_draw.ellipse([cx - 220, cy - 220, cx + 220, cy + 220], outline=CIRCLE_LINE, width=2)
    band_draw.ellipse([cx - 160, cy - 160, cx + 160, cy + 160], outline=CIRCLE_LINE, width=2)
    band_draw.ellipse([cx - filled_r, cy - filled_r, cx + filled_r, cy + filled_r], fill=fill_color)
    return band
