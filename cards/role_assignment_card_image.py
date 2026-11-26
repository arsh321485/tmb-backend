"""
Read-only "Role / Primary / Backup" card for one team, drawn as a real
PNG -- same template-by-code approach as role_card_image.py and
admin_welcome_card_image.py. Picking/editing Primary and Backup happens
on the website's Teams portal; this card is just the Slack-side VIEW of
whatever was picked there.

Every assigned role for the currently-selected team/priority tab is
drawn into ONE image (sir's call: one picture per team, not one per
role) -- up to _ROWS_PER_PAGE rows per picture; teams_v2_data.py pages
through the rest with Prev/Back buttons when there are more than that.
"""

import hashlib
import io
import math

from PIL import Image, ImageDraw

from .card_image_common import (
    BG, CARD_BG, CARD_BORDER, GENERATED_DIR, INK, MUTED, PURPLE, TEAL, TEAL_BG,
    draw_footer_bar, font, wrap,
)

# Bump whenever render_team_roles_card_image's drawing changes -- see
# get_team_roles_card_image_url's cache-key comment below.
_TEMPLATE_VERSION = "v1"

ROWS_PER_PAGE = 3


def render_team_roles_card_image(team_name: str, role_rows: list[tuple[str, str, str]], page: int, total_pages: int) -> bytes:
    """role_rows: [(role, primary_name, backup_name), ...] -- already
    sliced to this one page by the caller."""
    width = 1100
    pad = 40
    gap = 18
    row_h = 118
    footer_h = 10

    measure_img = Image.new("RGB", (10, 10))
    measure_draw = ImageDraw.Draw(measure_img)
    title_font = font(True, 28)
    role_font = font(True, 22)
    box_h = 70

    page_text = f"PAGE {page} OF {total_pages}" if total_pages > 1 else ""
    page_font = font(True, 15)

    title_h = 44
    height = pad + title_h + gap + len(role_rows) * row_h + max(0, len(role_rows) - 1) * gap + pad + footer_h

    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)

    draw.text((pad, pad), team_name, font=title_font, fill=INK)
    if page_text:
        pt_w = draw.textlength(page_text, font=page_font)
        draw.text((width - pad - pt_w, pad + 10), page_text, font=page_font, fill=MUTED)

    y = pad + title_h + gap
    col_w = (width - pad * 2 - gap) // 2
    for role, primary_name, backup_name in role_rows:
        role_lines = wrap(measure_draw, role, role_font, width - pad * 2)[:1]
        draw.text((pad, y), role_lines[0] if role_lines else role, font=role_font, fill=INK)
        by = y + 30

        for i, (label, name, color) in enumerate([("PRIMARY", primary_name, TEAL), ("BACKUP", backup_name, PURPLE)]):
            bx = pad + i * (col_w + gap)
            draw.rounded_rectangle([bx, by, bx + col_w, by + box_h], radius=12, fill=CARD_BG, outline=CARD_BORDER, width=1)
            draw.text((bx + 16, by + 10), label, font=font(True, 13), fill=MUTED)
            draw.rounded_rectangle([bx + 16, by + 32, bx + 50, by + 66], radius=9, fill=color)
            initial = (name or "?").strip()[:1].upper() or "?"
            draw.text((bx + 26, by + 38), initial, font=font(True, 18), fill=(255, 255, 255))
            draw.text((bx + 60, by + 40), (name or "Not assigned")[:26], font=font(True, 18), fill=INK)

        y += row_h + gap

    draw_footer_bar(draw, width, height, footer_h)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def get_team_roles_card_image_url(backend_url: str, team_name: str, role_rows: list[tuple[str, str, str]], page: int, total_pages: int) -> str:
    key_source = "|".join([
        _TEMPLATE_VERSION, team_name, str(page), str(total_pages),
        ";".join(f"{r}:{p}:{b}" for r, p, b in role_rows),
    ])
    key = hashlib.sha1(key_source.encode("utf-8")).hexdigest()[:20]
    filename = f"teamroles_{key}.png"
    path = GENERATED_DIR / filename
    if not path.exists():
        data = render_team_roles_card_image(team_name, role_rows, page, total_pages)
        path.write_bytes(data)
    return f"{backend_url}/assets/generated/{filename}"


def role_pages(role_rows: list[tuple[str, str, str]]) -> list[list[tuple[str, str, str]]]:
    """Splits every assigned role for a team into ROWS_PER_PAGE-sized
    pages -- shared by teams_v2_data.py (building the card) and
    interactivity_v2.py (clamping the Next/Back button's page number)."""
    if not role_rows:
        return []
    pages = math.ceil(len(role_rows) / ROWS_PER_PAGE)
    return [role_rows[i * ROWS_PER_PAGE:(i + 1) * ROWS_PER_PAGE] for i in range(pages)]
