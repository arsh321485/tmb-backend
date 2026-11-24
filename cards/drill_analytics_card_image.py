"""
Renders the Drill Analytics screens (Overview and Team breakdown) as
real PNGs, from real numbers computed in cards/drill_analytics.py --
nothing fixed/mockup here. Same template-code approach as the other
cards.

"Team breakdown" / "← Overview" navigation stays a real Slack
button underneath these images -- not baked in, same reasoning as
every other card with a genuine click target.
"""

import hashlib
import io

from PIL import Image, ImageDraw

from .card_image_common import (
    BG, BRAND_RED, CARD_BG, CARD_BORDER, GENERATED_DIR, INK, MUTED, TEAL,
    draw_footer_bar, font, wrap,
)

_TEMPLATE_VERSION = "v4"

_BAR_TRACK = (230, 227, 221)
_ACTUAL_RED = (190, 40, 50)
_PLANNED_GRAY = (210, 207, 200)
_TEAL_BG = (223, 241, 238)


def _fmt_minutes(total_min: float) -> str:
    total_min = round(total_min)
    h, m = divmod(max(0, total_min), 60)
    if h and m:
        return f"{h}h {m}m"
    if h:
        return f"{h}h"
    return f"{m}m"


def _fmt_delta(delta_min: float) -> str:
    sign = "+" if delta_min >= 0 else "−"
    return f"{sign}{_fmt_minutes(abs(delta_min))}"


def render_overview_image(data: dict) -> bytes:
    width = 1200
    pad = 56
    header_h = 56
    gap = 20
    meta_h = 24
    box_h = 240
    tile_h = 90
    phase_row_h = 56
    footer_h = 10

    measure_img = Image.new("RGB", (10, 10))
    measure_draw = ImageDraw.Draw(measure_img)
    title_font = font(True, 26)
    module_badge_font = font(True, 13)

    phases = data["phases"]
    phase_section_h = (26 + len(phases) * phase_row_h) if phases else 0

    height = (
        pad + header_h + 40 + meta_h + gap + box_h + gap + tile_h + gap
        + phase_section_h + pad + footer_h
    )

    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)


    badge_text = "DRILL ANALYTICS"
    badge_font = font(True, 16)
    badge_tw = draw.textlength(badge_text, font=badge_font)
    badge_w = badge_tw + 56
    badge_x0, badge_y0 = width - pad - badge_w, pad
    draw.rounded_rectangle([badge_x0, badge_y0, width - pad, badge_y0 + 40], radius=20, outline=CARD_BORDER, width=2)
    dot_cy = badge_y0 + 20
    draw.ellipse([badge_x0 + 20, dot_cy - 4, badge_x0 + 28, dot_cy + 4], fill=INK)
    draw.text((badge_x0 + 36, badge_y0 + 11), badge_text, font=badge_font, fill=INK)

    y = pad + header_h
    module_text = data["module"].upper()
    module_tw = draw.textlength(module_text, font=module_badge_font)
    module_w = module_tw + 28
    draw.rounded_rectangle([pad, y, pad + module_w, y + 26], radius=6, fill=BRAND_RED)
    draw.text((pad + 14, y + 6), module_text, font=module_badge_font, fill="white")
    draw.text((pad + module_w + 14, y + 1), data["title"], font=title_font, fill=INK)
    y += 40

    meta_bits = []
    if data["team_count"]:
        meta_bits.append(f"{data['team_count']} teams")
    if data["people_count"]:
        meta_bits.append(f"{data['people_count']} people")
    meta_bits.append(f"{data['actions_total']} actions")
    draw.text((pad, y), " · ".join(meta_bits), font=font(False, 18), fill=MUTED)
    y += meta_h + gap

    col_gap = 24
    col_w = (width - pad * 2 - col_gap) // 2
    bx1 = pad
    bx2 = pad + col_w + col_gap
    draw.rounded_rectangle([bx1, y, bx1 + col_w, y + box_h], radius=14, fill=CARD_BG, outline=CARD_BORDER, width=2)
    draw.rounded_rectangle([bx2, y, bx2 + col_w, y + box_h], radius=14, fill=CARD_BG, outline=CARD_BORDER, width=2)

    # Box 1: Preparedness level
    ipad = 22
    ix, iy = bx1 + ipad, y + ipad
    draw.text((ix, iy), "PREPAREDNESS LEVEL", font=font(True, 13), fill=MUTED)
    bucket_text = data["bucket_label"].upper()
    bucket_font = font(True, 13)
    bucket_tw = draw.textlength(bucket_text, font=bucket_font)
    bucket_w = bucket_tw + 24
    draw.rounded_rectangle([bx1 + col_w - ipad - bucket_w, iy - 2, bx1 + col_w - ipad, iy - 2 + 24], radius=12, fill=(250, 233, 210))
    draw.text((bx1 + col_w - ipad - bucket_w + 12, iy + 2), bucket_text, font=bucket_font, fill=(184, 120, 40))
    iy += 30

    score_font = font(True, 48)
    denom_font = font(True, 22)
    score_text = str(data["preparedness"])
    draw.text((ix, iy), score_text, font=score_font, fill=INK)
    sx = ix + draw.textlength(score_text, font=score_font)
    draw.text((sx, iy + 16), "/100", font=denom_font, fill=MUTED)
    iy += 60

    bar_w = col_w - ipad * 2
    bar_h = 14
    seg_colors = [(190, 40, 50), (184, 120, 40), (74, 199, 183), (26, 140, 90)]
    seg_bounds = [0, 50, 75, 90, 100]
    for i in range(4):
        sx0 = ix + bar_w * seg_bounds[i] / 100
        sx1 = ix + bar_w * seg_bounds[i + 1] / 100
        draw.rectangle([sx0, iy, sx1, iy + bar_h], fill=seg_colors[i])
    tick_x = ix + bar_w * min(data["preparedness"], 100) / 100
    draw.line([(tick_x, iy - 4), (tick_x, iy + bar_h + 4)], fill=INK, width=2)
    iy += bar_h + 14

    legend_font = font(False, 13)
    legend_items = [("At risk <50", seg_colors[0]), ("Developing 50-74", seg_colors[1]), ("Prepared 75-89", seg_colors[2]), ("Resilient 90+", seg_colors[3])]
    lx = ix
    for i, (text, color) in enumerate(legend_items):
        draw.ellipse([lx, iy + 3, lx + 10, iy + 13], fill=color)
        draw.text((lx + 16, iy), text, font=legend_font, fill=MUTED)
        lx += draw.textlength(text, font=legend_font) + 40
        if i == 1:
            lx = ix
            iy += 20

    # Box 2: Total response time, all teams
    ix2, iy2 = bx2 + ipad, y + ipad
    draw.text((ix2, iy2), "TOTAL RESPONSE TIME · ALL TEAMS", font=font(True, 13), fill=MUTED)
    iy2 += 30
    draw.text((ix2, iy2), _fmt_minutes(data["actual_total_min"]), font=font(True, 40), fill=INK)
    iy2 += 48
    delta = data["actual_total_min"] - data["planned_total_min"]
    if delta > 0:
        draw.text((ix2, iy2), f"{_fmt_delta(delta)} over plan", font=font(True, 17), fill=_ACTUAL_RED)
    elif delta < 0:
        draw.text((ix2, iy2), f"{_fmt_delta(delta)} under plan", font=font(True, 17), fill=TEAL)
    iy2 += 30

    row_bar_w = col_w - ipad * 2 - 110
    planned_frac = min(1.0, data["planned_total_min"] / data["actual_total_min"]) if data["actual_total_min"] else 0
    draw.text((ix2, iy2 + 4), "Planned", font=font(False, 15), fill=MUTED)
    draw.rounded_rectangle([ix2 + 70, iy2 + 4, ix2 + 70 + row_bar_w * planned_frac, iy2 + 16], radius=5, fill=_PLANNED_GRAY)
    draw.text((bx2 + col_w - ipad - 70, iy2), _fmt_minutes(data["planned_total_min"]), font=font(True, 15), fill=INK)
    iy2 += 28
    draw.text((ix2, iy2 + 4), "Actual", font=font(False, 15), fill=MUTED)
    draw.rounded_rectangle([ix2 + 70, iy2 + 4, ix2 + 70 + row_bar_w, iy2 + 16], radius=5, fill=_ACTUAL_RED)
    draw.text((bx2 + col_w - ipad - 70, iy2), _fmt_minutes(data["actual_total_min"]), font=font(True, 15), fill=INK)
    iy2 += 34

    draw.line([(ix2, iy2), (bx2 + col_w - ipad, iy2)], fill=CARD_BORDER, width=1)
    iy2 += 12
    draw.text((ix2, iy2), "Preparedness = planned ÷ actual total response time", font=font(False, 14), fill=MUTED)
    iy2 += 20
    draw.text((ix2, iy2), f"{round(data['planned_total_min'])} min ÷ {round(data['actual_total_min'])} min = {data['preparedness']}", font=font(True, 15), fill=INK)

    y += box_h + gap

    tiles = [
        ("ACTIONS ON TIME", f"{data['actions_on_time']}/{data['actions_total']}", f"{round(100 * data['actions_on_time'] / data['actions_total']) if data['actions_total'] else 0}% on time"),
        ("PARTICIPATION", f"{data['responded_count']}/{data['notified_count']}", f"{data['participation_pct']}% responded"),
        ("MEDIAN ACKNOWLEDGE", _ack_text(data["median_ack_seconds"]), ""),
        ("BACKUPS ACTIVATED", str(data["backups_activated"]), "Roles handed over" if data["backups_activated"] else "None needed"),
    ]
    tile_gap = 20
    tw_each = (width - pad * 2 - tile_gap * 3) // 4
    for i, (label, value, caption) in enumerate(tiles):
        tx = pad + i * (tw_each + tile_gap)
        draw.rounded_rectangle([tx, y, tx + tw_each, y + tile_h], radius=14, fill=CARD_BG, outline=CARD_BORDER, width=2)
        draw.text((tx + 18, y + 14), label, font=font(True, 12), fill=MUTED)
        draw.text((tx + 18, y + 32), value, font=font(True, 26), fill=INK)
        if caption:
            draw.text((tx + 18, y + 64), caption, font=font(False, 13), fill=MUTED)
    y += tile_h + gap

    if phases:
        draw.text((pad, y), "RESPONSE TIME BY PHASE", font=font(True, 13), fill=MUTED)
        legend_x = width - pad - 160
        draw.rounded_rectangle([legend_x, y + 2, legend_x + 14, y + 10], radius=3, fill=_PLANNED_GRAY)
        draw.text((legend_x + 20, y), "Planned", font=font(False, 13), fill=MUTED)
        legend_x2 = legend_x + 90
        draw.rounded_rectangle([legend_x2, y + 2, legend_x2 + 14, y + 10], radius=3, fill=_ACTUAL_RED)
        draw.text((legend_x2 + 20, y), "Actual", font=font(False, 13), fill=MUTED)
        y += 26

        max_min = max((p["actual_min"] for p in phases), default=1) or 1
        bar_x = pad + 180
        bar_max_w = width - pad - bar_x - 140
        for p in phases:
            draw.text((pad, y + 6), p["phase"], font=font(True, 20), fill=INK)
            planned_w = bar_max_w * p["planned_min"] / max_min
            actual_w = bar_max_w * p["actual_min"] / max_min
            draw.rounded_rectangle([bar_x, y, bar_x + planned_w, y + 10], radius=4, fill=_PLANNED_GRAY)
            draw.rounded_rectangle([bar_x, y + 14, bar_x + actual_w, y + 26], radius=4, fill=_ACTUAL_RED)
            delta_p = p["actual_min"] - p["planned_min"]
            value_text = f"{_fmt_minutes(p['actual_min'])}  {_fmt_delta(delta_p)}"
            draw.text((width - pad - 130, y + 6), value_text, font=font(True, 16), fill=INK)
            y += phase_row_h

    draw_footer_bar(draw, width, height, footer_h)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _ack_text(seconds: float) -> str:
    seconds = round(seconds)
    m, s = divmod(seconds, 60)
    return f"{m}m {s}s" if m else f"{s}s"


def render_team_breakdown_image(data: dict) -> bytes:
    width = 1200
    pad = 56
    header_h = 56
    title_h = 56
    gap = 20
    row_h = 70
    insight_h = 110
    footer_h = 10

    measure_img = Image.new("RGB", (10, 10))
    measure_draw = ImageDraw.Draw(measure_img)
    subtitle_font = font(False, 22)
    subtitle = "Total response time by team against plan, ranked by deviation."
    subtitle_lines = wrap(measure_draw, subtitle, subtitle_font, width - pad * 2)

    rows = data["rows"] + [{
        "name": "All teams", "actions_done": data["total_done"], "actions_total": data["total_actions"],
        "planned_min": data["total_planned_min"], "actual_min": data["total_actual_min"],
        "deviation_min": data["total_actual_min"] - data["total_planned_min"],
        "deviation_pct": round(100 * (data["total_actual_min"] - data["total_planned_min"]) / data["total_planned_min"]) if data["total_planned_min"] else 0,
    }]

    has_insights = data.get("bottleneck") or data.get("spof")

    height = (
        pad + header_h + title_h + len(subtitle_lines) * 30 + gap + 26
        + len(rows) * row_h + 12 + gap + (insight_h if has_insights else 0) + pad + footer_h
    )

    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)


    badge_text = "ANALYTICS · TEAMS"
    badge_font = font(True, 16)
    badge_tw = draw.textlength(badge_text, font=badge_font)
    badge_w = badge_tw + 56
    badge_x0, badge_y0 = width - pad - badge_w, pad
    draw.rounded_rectangle([badge_x0, badge_y0, width - pad, badge_y0 + 40], radius=20, outline=CARD_BORDER, width=2)
    dot_cy = badge_y0 + 20
    draw.ellipse([badge_x0 + 20, dot_cy - 4, badge_x0 + 28, dot_cy + 4], fill=INK)
    draw.text((badge_x0 + 36, badge_y0 + 11), badge_text, font=badge_font, fill=INK)

    y = pad + header_h
    title_font = font(True, 44)
    prefix = "Where the "
    x = pad
    draw.text((x, y), prefix, font=title_font, fill=INK)
    x += draw.textlength(prefix, font=title_font)
    time_word = "time"
    draw.text((x, y), time_word, font=title_font, fill=BRAND_RED)
    x += draw.textlength(time_word, font=title_font)
    draw.text((x, y), " went", font=title_font, fill=INK)
    y += title_h

    for line in subtitle_lines:
        draw.text((pad, y), line, font=subtitle_font, fill=MUTED)
        y += 30
    y += gap

    col_team_x = pad
    col_actions_x = pad + 420
    col_planned_x = pad + 540
    col_actual_x = pad + 660
    col_dev_x = pad + 790
    col_bar_x = pad + 900
    bar_w_max = width - pad - col_bar_x

    label_font = font(True, 13)
    draw.text((col_team_x, y), "TEAM", font=label_font, fill=MUTED)
    draw.text((col_actions_x, y), "ACTIONS", font=label_font, fill=MUTED)
    draw.text((col_planned_x, y), "PLANNED", font=label_font, fill=MUTED)
    draw.text((col_actual_x, y), "ACTUAL", font=label_font, fill=MUTED)
    draw.text((col_dev_x, y), "DEVIATION", font=label_font, fill=MUTED)
    faster_tw = draw.textlength("FASTER", font=label_font)
    draw.text((col_bar_x, y), "FASTER", font=label_font, fill=MUTED)
    draw.text((width - pad - draw.textlength("SLOWER", font=label_font), y), "SLOWER", font=label_font, fill=MUTED)
    y += 26

    max_abs_dev = max((abs(r["deviation_min"]) for r in rows), default=1) or 1
    name_font = font(True, 20)

    for i, r in enumerate(rows):
        is_total = r["name"] == "All teams"
        if is_total:
            draw.line([(pad, y), (width - pad, y)], fill=INK, width=1)
            y += 12
        name_lines = wrap(draw, r["name"], name_font, 390)
        ty = y + 10
        for line in name_lines:
            draw.text((col_team_x, ty), line, font=name_font, fill=INK)
            ty += 24

        mid_y = y + 10
        draw.text((col_actions_x, mid_y), f"{r['actions_done']}/{r['actions_total']}", font=font(False, 18), fill=INK)
        draw.text((col_planned_x, mid_y), _fmt_minutes(r["planned_min"]), font=font(False, 18), fill=INK)
        draw.text((col_actual_x, mid_y), _fmt_minutes(r["actual_min"]), font=font(False, 18), fill=INK)

        dev = r["deviation_min"]
        dev_color = _ACTUAL_RED if dev > 0 else TEAL
        dev_text = _fmt_delta(dev)
        draw.text((col_dev_x, mid_y), dev_text, font=font(True, 18), fill=dev_color)
        draw.text((col_dev_x, mid_y + 20), f"{'+' if r['deviation_pct'] >= 0 else ''}{r['deviation_pct']}%", font=font(False, 13), fill=MUTED)

        bar_w = bar_w_max * abs(dev) / max_abs_dev
        bar_color = _ACTUAL_RED if dev > 0 else TEAL
        draw.rounded_rectangle([col_bar_x, mid_y + 4, col_bar_x + max(2, bar_w), mid_y + 16], radius=4, fill=bar_color)

        y += row_h

    y += gap
    if has_insights:
        col_gap = 20
        n_insights = sum(1 for k in ("bottleneck", "spof") if data.get(k))
        ins_w = (width - pad * 2 - col_gap * (n_insights - 1)) // max(1, n_insights) if n_insights else 0
        ix = pad
        if data.get("bottleneck"):
            b = data["bottleneck"]
            draw.rounded_rectangle([ix, y, ix + ins_w, y + insight_h], radius=14, fill=CARD_BG, outline=CARD_BORDER, width=2)
            draw.text((ix + 18, y + 16), "BOTTLENECK · " + b["team_name"].upper(), font=font(True, 12), fill=MUTED)
            text = f"Took {_fmt_minutes(b['wait_min'])} to respond" + (f" to “{b['title']}”" if b.get("title") else "")
            for li, line in enumerate(wrap(draw, text, font(False, 15), ins_w - 36)):
                draw.text((ix + 18, y + 42 + li * 20), line, font=font(False, 15), fill=INK)
            ix += ins_w + col_gap
        if data.get("spof"):
            s = data["spof"]
            draw.rounded_rectangle([ix, y, ix + ins_w, y + insight_h], radius=14, fill=(252, 230, 230), outline=(240, 180, 180), width=2)
            draw.text((ix + 18, y + 16), "SINGLE POINT OF FAILURE · " + s["team_name"].upper(), font=font(True, 12), fill=BRAND_RED)
            text = "Only one person answered for this team — no backup stepped in."
            for li, line in enumerate(wrap(draw, text, font(False, 15), ins_w - 36)):
                draw.text((ix + 18, y + 42 + li * 20), line, font=font(False, 15), fill=INK)
        y += insight_h

    draw_footer_bar(draw, width, height, footer_h)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def get_overview_image_url(backend_url: str, data: dict) -> str:
    key_source = "|".join([
        _TEMPLATE_VERSION, data["title"], str(data["preparedness"]), str(round(data["planned_total_min"])),
        str(round(data["actual_total_min"])), str(data["actions_on_time"]), str(data["actions_total"]),
        str(data["responded_count"]), str(data["notified_count"]), str(round(data["median_ack_seconds"])),
        str(data["backups_activated"]),
        ";".join(f"{p['phase']}:{round(p['planned_min'])}:{round(p['actual_min'])}" for p in data["phases"]),
    ])
    key = hashlib.sha1(key_source.encode("utf-8")).hexdigest()[:20]
    filename = f"drilloverview_{key}.png"
    path = GENERATED_DIR / filename
    if not path.exists():
        path.write_bytes(render_overview_image(data))
    return f"{backend_url}/assets/generated/{filename}"


def get_team_breakdown_image_url(backend_url: str, data: dict) -> str:
    rows_flat = ";".join(f"{r['team_id']}:{r['actions_done']}:{r['actions_total']}:{round(r['planned_min'])}:{round(r['actual_min'])}" for r in data["rows"])
    key_source = f"{_TEMPLATE_VERSION}|{rows_flat}|{data.get('bottleneck')}|{data.get('spof')}"
    key = hashlib.sha1(key_source.encode("utf-8")).hexdigest()[:20]
    filename = f"drillteams_{key}.png"
    path = GENERATED_DIR / filename
    if not path.exists():
        path.write_bytes(render_team_breakdown_image(data))
    return f"{backend_url}/assets/generated/{filename}"
