#!/usr/bin/env python3
"""
presentation.py — renders a diocese's scraped data as a high-res PNG "card"
suitable for screenshotting/sharing to social media. Triggered by the 'P' key
in main.py; never drawn to the terminal itself.

Four output shapes, chosen at 'P'-time (see main.py's format picker):
  landscape  1600x900   two-column (images left, text right) — X/Twitter desktop
  portrait   1080x1350  single column, stacked — Instagram feed
  square     1080x1080  single column, stacked, tighter — Instagram square
  mobile     1080x1920  single column, stacked, largest fonts — fills an
                         iPhone-size screen in the X/Substack apps without
                         needing to pinch-zoom to read it

The About excerpt is never truncated: build_presentation() measures the full
paragraph before drawing anything, shrinks its font only as far as needed to
fit the space available, and — if it still needs more room than the format's
nominal canvas has — grows the canvas a bit taller rather than cut text.
"""

import io
import subprocess
import sys
import textwrap
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

DIR = Path(__file__).parent
MARGIN = 40

FORMATS = {
    "landscape": (1600, 900),
    "portrait":  (1080, 1350),
    "square":    (1080, 1080),
    "mobile":    (1080, 1920),
}

# Classic ecclesiastical palette: ivory page, deep gold, cardinal maroon.
BG          = (253, 251, 246)   # warm ivory page background
PANEL       = (246, 242, 233)   # tile / image-box fill, a touch off the page
GOLD        = (168, 122, 38)    # primary accent — labels, header band, borders
GOLD_DIM    = (206, 182, 138)   # softer gold for hairline borders
MAROON      = (96, 18, 26)      # secondary accent — sub band, social handles
INK         = (36, 32, 28)      # primary text, near-black warm charcoal
MUTED       = (132, 124, 110)   # captions, source line
DIVIDER     = (223, 214, 196)   # hairline dividers on ivory
HEADER_TEXT = (26, 20, 10)      # header band text — sits on gold, always dark
SUB_TEXT    = (238, 224, 202)   # sub band text — sits on maroon

FONT_DIR = Path("/System/Library/Fonts/Supplemental")
UA = "get-diocese/1.0 (terminal explorer; https://github.com/coderanger76/currents)"
TIMEOUT = 10


def _font(name, size):
    path = FONT_DIR / name
    if path.exists():
        return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def _fetch_image(url):
    if not url:
        return None
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT)
        if not r.ok:
            return None
        return Image.open(io.BytesIO(r.content)).convert("RGBA")
    except Exception:
        return None


def _fit_into(img, box_w, box_h):
    """Downscale (never upscale) to fit within box_w x box_h, preserving aspect."""
    w, h = img.size
    scale = min(box_w / w, box_h / h, 1.0)
    return img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)


def _paste_centered(canvas, img, box):
    x0, y0, x1, y1 = box
    fitted = _fit_into(img, x1 - x0, y1 - y0)
    fw, fh = fitted.size
    px = x0 + (x1 - x0 - fw) // 2
    py = y0 + (y1 - y0 - fh) // 2
    canvas.paste(fitted, (px, py), fitted)


def _image_box(draw, canvas, img, box, caption, caption_font):
    x0, y0, x1, y1 = box
    draw.rectangle(box, fill=PANEL, outline=GOLD_DIM, width=2)
    if img is not None:
        _paste_centered(canvas, img, (x0 + 10, y0 + 10, x1 - 10, y1 - 10))
    else:
        msg = "not found"
        bbox = draw.textbbox((0, 0), msg, font=caption_font)
        tw = bbox[2] - bbox[0]
        draw.text(((x0 + x1) / 2 - tw / 2, (y0 + y1) / 2 - 8), msg, font=caption_font, fill=MUTED)
    cap_bbox = draw.textbbox((0, 0), caption, font=caption_font)
    cw = cap_bbox[2] - cap_bbox[0]
    draw.text(((x0 + x1) / 2 - cw / 2, y1 + 8), caption, font=caption_font, fill=MUTED)


def _plan_about(draw, text, sizes, max_width, avail_height):
    """Measure the FULL About paragraph (never truncates). Tries font sizes
    largest-to-smallest and returns the first that fits avail_height; if none
    fit, returns the smallest anyway so the caller can grow the canvas rather
    than lose text. Returns (font, lines, line_h, total_h) or None."""
    if not text:
        return None
    fallback = None
    for size in sizes:
        font = _font("Georgia.ttf", size)
        line_h = size + 7
        avg_char_w = draw.textlength("n", font=font) or 10
        chars_per_line = max(10, int(max_width / avg_char_w))
        lines = textwrap.wrap(text, chars_per_line)
        total_h = len(lines) * line_h
        fallback = (font, lines, line_h, total_h)
        if total_h <= avail_height:
            return fallback
    return fallback


TILE_VALUE_SIZES = (30, 26, 22, 18, 15, 13)


def _fit_font(draw, text, family, max_width, sizes=TILE_VALUE_SIZES):
    for size in sizes:
        font = _font(family, size)
        if draw.textlength(text, font=font) <= max_width:
            return font
    return _font(family, sizes[-1])


def _stat_tile(draw, box, label, value, f_label, f_value_max_sizes):
    x0, y0, x1, y1 = box
    draw.rectangle(box, fill=PANEL, outline=DIVIDER, width=1)
    draw.text((x0 + 16, y0 + 12), label.upper(), font=f_label, fill=GOLD)
    val = value if value else "—"
    font = _fit_font(draw, val, "Georgia Bold.ttf", (x1 - x0) - 32, f_value_max_sizes)
    draw.text((x0 + 16, y0 + 12 + f_label.size + 8), val, font=font, fill=INK)


def _title_font(draw, text, max_width, sizes=(46, 40, 34, 29, 25, 22)):
    for size in sizes:
        font = _font("Georgia Bold.ttf", size)
        if draw.textlength(text, font=font) <= max_width:
            return font
    return _font("Georgia Bold.ttf", sizes[-1])


def _header(draw, W, name, dtype, city, state, founded, header_h=90, sub_h=48,
            tag_size=20, sub_size=24, title_sizes=(46, 40, 34, 29, 25, 22), title_max=None):
    """Draws the gold name band + maroon location/founded band. Returns the y
    just below the sub band (i.e. where content starts)."""
    f_tag = _font("Georgia Bold.ttf", tag_size)
    tag = f"FAITH · {dtype}"
    tag_bbox = draw.textbbox((0, 0), tag, font=f_tag)
    tag_w = tag_bbox[2] - tag_bbox[0]

    header_box = (MARGIN, MARGIN, W - MARGIN, MARGIN + header_h)
    draw.rectangle(header_box, fill=GOLD)
    avail_title_w = (title_max or (W - 2 * MARGIN)) - 48 - tag_w - 20
    f_title = _title_font(draw, name, avail_title_w, sizes=title_sizes)
    title_y = MARGIN + (header_h - f_title.size) / 2 - 4
    draw.text((MARGIN + 24, title_y), name, font=f_title, fill=HEADER_TEXT)
    draw.text((W - MARGIN - 24 - tag_w, MARGIN + (header_h - f_tag.size) / 2), tag,
              font=f_tag, fill=HEADER_TEXT)

    sub_top = MARGIN + header_h
    sub_box = (MARGIN, sub_top, W - MARGIN, sub_top + sub_h)
    draw.rectangle(sub_box, fill=MAROON)
    parts = []
    if city and state:
        parts.append(f"{city}, {state}")
    elif state:
        parts.append(state)
    if founded:
        parts.append(f"Founded {founded}")
    sub_text = "  ·  ".join(parts)
    sub_sizes = [s for s in (sub_size, sub_size - 2, sub_size - 4, sub_size - 6, sub_size - 8) if s >= 12]
    f_sub = _fit_font(draw, sub_text, "Georgia.ttf", W - 2 * MARGIN - 48, sizes=sub_sizes or (12,))
    draw.text((MARGIN + 24, sub_top + (sub_h - f_sub.size) / 2 - 2), sub_text,
               font=f_sub, fill=SUB_TEXT)

    return sub_top + sub_h


def _footer(draw, W, y_top, site, stacked, foot_size=16, brand_size=16):
    f_foot = _font("Georgia.ttf", foot_size)
    f_brand = _font("Georgia Bold.ttf", brand_size)
    draw.line((MARGIN, y_top, W - MARGIN, y_top), fill=DIVIDER, width=1)

    source_bits = ["Source: Wikipedia"]
    if site:
        domain = site.replace("https://", "").replace("http://", "").rstrip("/")
        source_bits.append(domain)
    source_line = "  ·  ".join(source_bits)
    handles = "@_catholicwest · X      @catholicwest · Substack"

    if stacked:
        draw.text((MARGIN, y_top + 14), source_line, font=f_foot, fill=MUTED)
        draw.text((MARGIN, y_top + 14 + f_foot.size + 6), handles, font=f_brand, fill=MAROON)
    else:
        draw.text((MARGIN, y_top + 22), source_line, font=f_foot, fill=MUTED)
        hw = draw.textbbox((0, 0), handles, font=f_brand)[2]
        draw.text((W - MARGIN - hw, y_top + 22), handles, font=f_brand, fill=MAROON)


def _bishop_cathedral_block(draw, x0, x1, y, dtype, bishop, cathedral, f_label, f_value, line_h):
    if bishop:
        leader = "ARCHBISHOP" if dtype == "ARCHDIOCESE" else ("BISHOP" if dtype != "EPARCHY" else "BISHOP/EPARCH")
        draw.text((x0, y), leader, font=f_label, fill=GOLD)
        draw.text((x0, y + f_label.size + 4), bishop, font=f_value, fill=INK)
        y += line_h
    if cathedral:
        draw.text((x0, y), "CATHEDRAL", font=f_label, fill=GOLD)
        draw.text((x0, y + f_label.size + 4), cathedral, font=f_value, fill=INK)
        y += line_h
    return y


def _stat_grid(draw, x0, x1, y, stats, tile_h, gap, f_label, f_value_sizes):
    cols, rows = 3, 2
    tile_w = (x1 - x0 - gap * (cols - 1)) // cols
    for i, (label, value) in enumerate(stats):
        r, col = divmod(i, cols)
        tx0 = x0 + col * (tile_w + gap)
        ty0 = y + r * (tile_h + gap)
        _stat_tile(draw, (tx0, ty0, tx0 + tile_w, ty0 + tile_h), label, value, f_label, f_value_sizes)
    return y + rows * tile_h + (rows - 1) * gap


def _stats_list(merged):
    return [
        ("Catholics", merged.get("catholics", "")),
        ("Total Population", merged.get("population", "")),
        ("Parishes", merged.get("parishes", "")),
        ("Priests", merged.get("priests", "")),
        ("Deacons", merged.get("deacons", "")),
        ("Area", merged.get("area", "")),
    ]


LANDSCAPE_TUNING = dict(
    header_h=90, sub_h=48, top_gap=30, bishop_line_h=66, divider_gap1=10, divider_gap2=26,
    tile_h=92, gap=20, post_stats_gap=30, label_size=17, body_sizes=(20, 18, 16, 14, 13),
    footer_zone=90,
)


def _landscape_before_about(has_bishop, has_cathedral):
    """Pure arithmetic mirror of _render_landscape's layout up through the
    stat grid — used to plan the About block before the canvas is created.
    Keep in sync with _render_landscape."""
    t = LANDSCAPE_TUNING
    y = MARGIN + t["header_h"] + t["sub_h"] + t["top_gap"]
    if has_bishop:
        y += t["bishop_line_h"]
    if has_cathedral:
        y += t["bishop_line_h"]
    y += t["divider_gap1"] + t["divider_gap2"]
    y += 2 * t["tile_h"] + t["gap"]
    y += t["post_stats_gap"]
    return y


def _render_landscape(canvas, draw, merged, coat_img, cathedral_img, map_img,
                       map_content_bottom, about_plan, footer_top_y):
    W = FORMATS["landscape"][0]
    name = merged.get("name", "").upper()
    dtype = (merged.get("diocese_type") or "diocese").upper()

    content_top = _header(draw, W, name, dtype, merged.get("city", ""), merged.get("state", ""),
                           merged.get("founded", ""))
    content_top += 30

    f_caption = _font("Georgia Bold.ttf", 14)
    CAPTION_H = 26

    left_w = 420
    left_x0 = MARGIN
    left_x1 = MARGIN + left_w
    top_row_h = 230
    top_gap = 20
    tile_w = (left_w - top_gap) // 2

    crest_box = (left_x0, content_top, left_x0 + tile_w, content_top + top_row_h)
    _image_box(draw, canvas, coat_img, crest_box, "COAT OF ARMS", f_caption)

    cathedral_box = (left_x0 + tile_w + top_gap, content_top, left_x1, content_top + top_row_h)
    _image_box(draw, canvas, cathedral_img, cathedral_box, "CATHEDRAL", f_caption)

    map_top = content_top + top_row_h + CAPTION_H + 34
    map_box = (left_x0, map_top, left_x1, map_content_bottom - CAPTION_H)
    _image_box(draw, canvas, map_img, map_box, "DIOCESAN MAP", f_caption)

    right_x0 = left_x1 + 50
    right_x1 = W - MARGIN
    f_label = _font("Georgia Bold.ttf", 17)
    f_value = _font("Georgia.ttf", 26)
    ry = _bishop_cathedral_block(draw, right_x0, right_x1, content_top, dtype,
                                  merged.get("bishop", ""), merged.get("cathedral", ""),
                                  f_label, f_value, 66)
    ry += 10
    draw.line((right_x0, ry, right_x1, ry), fill=DIVIDER, width=1)
    ry += 26

    ry = _stat_grid(draw, right_x0, right_x1, ry, _stats_list(merged), 92, 20,
                     _font("Georgia Bold.ttf", 15), TILE_VALUE_SIZES)
    ry += 30

    if about_plan:
        font, lines, line_h, _ = about_plan
        draw.text((right_x0, ry), "ABOUT", font=f_label, fill=GOLD)
        ry += f_label.size + 10
        for line in lines:
            draw.text((right_x0, ry), line, font=font, fill=INK)
            ry += line_h

    _footer(draw, W, footer_top_y, merged.get("url", ""), stacked=False)


STACKED_TUNING = {
    "square": dict(
        header_h=76, sub_h=40, tag_size=16, sub_size=19, title_sizes=(40, 34, 29, 25, 22, 19),
        top_gap=18, img_row_h=165, map_h=182, gap=12, caption_size=13, caption_gap=20,
        label_size=15, value_size=18, bishop_line_h=48, divider_gap1=8, divider_gap2=18,
        stat_label_size=13, stat_value_sizes=(24, 20, 17, 14, 12), tile_h=70, post_stats_gap=22,
        body_sizes=(16, 15, 14, 13, 12), footer_zone=66, foot_size=15, brand_size=15,
    ),
    "portrait": dict(
        header_h=84, sub_h=44, tag_size=18, sub_size=21, title_sizes=(42, 36, 31, 27, 23, 20),
        top_gap=18, img_row_h=250, map_h=280, gap=18, caption_size=14, caption_gap=20,
        label_size=17, value_size=22, bishop_line_h=62, divider_gap1=8, divider_gap2=18,
        stat_label_size=14, stat_value_sizes=(28, 24, 20, 17, 14), tile_h=90, post_stats_gap=22,
        body_sizes=(19, 18, 16, 15, 13), footer_zone=66, foot_size=16, brand_size=16,
    ),
    "mobile": dict(
        header_h=110, sub_h=56, tag_size=22, sub_size=26, title_sizes=(52, 46, 40, 34, 29, 25),
        top_gap=24, img_row_h=380, map_h=420, gap=22, caption_size=18, caption_gap=26,
        label_size=20, value_size=28, bishop_line_h=82, divider_gap1=12, divider_gap2=24,
        stat_label_size=17, stat_value_sizes=(36, 32, 28, 24, 20), tile_h=140, post_stats_gap=30,
        body_sizes=(23, 21, 19, 17, 15), footer_zone=100, foot_size=19, brand_size=19,
    ),
}


def _stacked_before_about(t, has_bishop, has_cathedral):
    """Pure arithmetic mirror of _render_stacked's layout up through the stat
    grid — used to plan the About block before the canvas is created. Keep in
    sync with _render_stacked."""
    content_top = MARGIN + t["header_h"] + t["sub_h"] + t["top_gap"]
    y = content_top + t["img_row_h"] + t["map_h"] + 2 * t["caption_gap"] + 2 * t["gap"] + t["divider_gap1"] // 2
    if has_bishop:
        y += t["bishop_line_h"]
    if has_cathedral:
        y += t["bishop_line_h"]
    y += t["divider_gap1"] + t["divider_gap2"]
    y += 2 * t["tile_h"] + t["gap"]
    y += t["post_stats_gap"]
    return y


def _render_stacked(canvas, draw, merged, coat_img, cathedral_img, map_img, fmt,
                     about_plan, footer_top_y):
    W = FORMATS[fmt][0]
    name = merged.get("name", "").upper()
    dtype = (merged.get("diocese_type") or "diocese").upper()
    t = STACKED_TUNING[fmt]

    content_top = _header(draw, W, name, dtype, merged.get("city", ""), merged.get("state", ""),
                           merged.get("founded", ""), header_h=t["header_h"], sub_h=t["sub_h"],
                           tag_size=t["tag_size"], sub_size=t["sub_size"], title_sizes=t["title_sizes"])
    content_top += t["top_gap"]

    x0, x1 = MARGIN, W - MARGIN
    f_caption = _font("Georgia Bold.ttf", t["caption_size"])
    CAPTION_H = t["caption_gap"]

    gap = t["gap"]
    tile_w = (x1 - x0 - gap) // 2
    row1_h = t["img_row_h"]

    crest_box = (x0, content_top, x0 + tile_w, content_top + row1_h)
    _image_box(draw, canvas, coat_img, crest_box, "COAT OF ARMS", f_caption)
    cathedral_box = (x0 + tile_w + gap, content_top, x1, content_top + row1_h)
    _image_box(draw, canvas, cathedral_img, cathedral_box, "CATHEDRAL", f_caption)

    map_top = content_top + row1_h + CAPTION_H + gap
    map_h = t["map_h"]
    map_box = (x0, map_top, x1, map_top + map_h)
    _image_box(draw, canvas, map_img, map_box, "DIOCESAN MAP", f_caption)

    y = map_top + map_h + CAPTION_H + gap + t["divider_gap1"] // 2

    f_label = _font("Georgia Bold.ttf", t["label_size"])
    f_value = _font("Georgia.ttf", t["value_size"])
    y = _bishop_cathedral_block(draw, x0, x1, y, dtype, merged.get("bishop", ""),
                                 merged.get("cathedral", ""), f_label, f_value, t["bishop_line_h"])
    y += t["divider_gap1"]
    draw.line((x0, y, x1, y), fill=DIVIDER, width=1)
    y += t["divider_gap2"]

    y = _stat_grid(draw, x0, x1, y, _stats_list(merged), t["tile_h"], gap,
                    _font("Georgia Bold.ttf", t["stat_label_size"]), t["stat_value_sizes"])
    y += t["post_stats_gap"]

    if about_plan:
        font, lines, line_h, _ = about_plan
        draw.text((x0, y), "ABOUT", font=f_label, fill=GOLD)
        y += f_label.size + 10
        for line in lines:
            draw.text((x0, y), line, font=font, fill=INK)
            y += line_h

    _footer(draw, W, footer_top_y, merged.get("url", ""), stacked=True,
            foot_size=t["foot_size"], brand_size=t["brand_size"])


def build_presentation(diocese, data, fmt="landscape", out_path=None):
    """Composite the scraped diocese info + crest + cathedral + map into one
    PNG in the requested shape. The About excerpt always shows in full — see
    module docstring — which can make the output slightly taller than the
    format's nominal size for an unusually long paragraph.
    Returns the Path written to."""
    if fmt not in FORMATS:
        raise ValueError(f"unknown format {fmt!r}, expected one of {list(FORMATS)}")
    W, H_nominal = FORMATS[fmt]
    out_path = Path(out_path) if out_path else DIR / f"presentation_{fmt}.png"

    merged = {**diocese, **{k: v for k, v in data.items() if v}}
    has_bishop = bool(merged.get("bishop"))
    has_cathedral = bool(merged.get("cathedral"))
    summary = merged.get("summary", "")

    coat_img = _fetch_image(merged.get("coat_of_arms_url", ""))
    cathedral_img = _fetch_image(merged.get("cathedral_photo_url", ""))
    map_img = _fetch_image(merged.get("map_url", ""))

    # Measure-only pass: figure out how tall the About block needs to be
    # BEFORE creating the real canvas, so the canvas can grow to fit it.
    mdraw = ImageDraw.Draw(Image.new("RGB", (10, 10)))

    if fmt == "landscape":
        right_x0 = MARGIN + 420 + 50
        about_max_width = W - MARGIN - right_x0
        y_before_about = _landscape_before_about(has_bishop, has_cathedral)
        footer_zone = LANDSCAPE_TUNING["footer_zone"]
        label_h = 17 + 10
        body_sizes = LANDSCAPE_TUNING["body_sizes"]
        footer_gap = 12
    else:
        t = STACKED_TUNING[fmt]
        about_max_width = W - 2 * MARGIN
        y_before_about = _stacked_before_about(t, has_bishop, has_cathedral)
        footer_zone = t["footer_zone"]
        label_h = t["label_size"] + 10
        body_sizes = t["body_sizes"]
        footer_gap = 10

    nominal_content_bottom = H_nominal - MARGIN - footer_zone
    avail_height = max(0, nominal_content_bottom - y_before_about - label_h)
    about_plan = _plan_about(mdraw, summary, body_sizes, about_max_width, avail_height)
    about_block_h = (label_h + about_plan[3]) if about_plan else 0

    actual_content_bottom = max(nominal_content_bottom, y_before_about + about_block_h)
    H = max(H_nominal, actual_content_bottom + MARGIN + footer_zone)

    canvas = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((4, 4, W - 5, H - 5), outline=GOLD_DIM, width=2)

    footer_top_y = actual_content_bottom + footer_gap

    if fmt == "landscape":
        _render_landscape(canvas, draw, merged, coat_img, cathedral_img, map_img,
                           nominal_content_bottom, about_plan, footer_top_y)
    else:
        _render_stacked(canvas, draw, merged, coat_img, cathedral_img, map_img, fmt,
                         about_plan, footer_top_y)

    canvas.save(out_path, "PNG")

    if sys.platform == "darwin":
        try:
            subprocess.Popen(["open", str(out_path)])
        except Exception:
            pass

    return out_path
