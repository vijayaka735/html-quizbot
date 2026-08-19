import os
import re
import tempfile
import unicodedata
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

GROUP_NAME = "QUICK STUDY GROUP"

# Large enough for a readable Telegram PDF. Rows are split across pages.
PAGE_W, PAGE_H = 1654, 2339
MARGIN = 55
HEADER_TITLE_H = 100
HEADER_SUB_H = 82
INFO_H = 70
TABLE_HEADER_H = 72
ROW_H = 57
FOOTER_H = 125
ROWS_PER_PAGE = 28

BASE = Path(__file__).resolve().parent
FONT_DIR = BASE / "fonts"
DEV_REG = FONT_DIR / "NotoSansDevanagari-Regular.ttf"
DEV_BOLD = FONT_DIR / "NotoSansDevanagari-Bold.ttf"

if not DEV_REG.exists():
    raise RuntimeError(f"Missing font: {DEV_REG}")
if not DEV_BOLD.exists():
    DEV_BOLD = DEV_REG


def _font(size, bold=False, devanagari=False):
    if devanagari:
        path = DEV_BOLD if bold else DEV_REG
    else:
        path = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
                    else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    layout = getattr(ImageFont, "Layout", None)
    kwargs = {"size": int(size)}
    if layout is not None and hasattr(layout, "RAQM"):
        kwargs["layout_engine"] = layout.RAQM
    return ImageFont.truetype(str(path), **kwargs)


def _has_deva(text):
    return bool(re.search(r"[\u0900-\u097F]", str(text or "")))


def _font_for_part(part, size, bold=False):
    return _font(size, bold, devanagari=_has_deva(part))


def _parts(text):
    return re.findall(
        r"[\u0900-\u097F]+|[A-Za-z]+|\d+(?:\.\d+)?|"
        r"\s+|[^\u0900-\u097FA-Za-z0-9\s]",
        unicodedata.normalize("NFC", str(text or "")),
    )


def _text_width(draw, text, size, bold=False):
    total = 0
    for part in _parts(text):
        total += draw.textlength(part, font=_font_for_part(part, size, bold))
    return total


def _fit_text(draw, text, size, max_width, bold=False):
    text = unicodedata.normalize("NFC", str(text or ""))
    if _text_width(draw, text, size, bold) <= max_width:
        return text

    suffix = "..."
    chars = list(text)
    while chars and _text_width(draw, "".join(chars) + suffix, size, bold) > max_width:
        chars.pop()
    return "".join(chars).rstrip() + suffix


def _wrap_text(draw, text, size, max_width, bold=False, max_lines=2):
    text = unicodedata.normalize("NFC", str(text or "")).strip()
    if not text:
        return [""]

    words = text.split()
    lines = []
    current = ""

    for word in words:
        trial = word if not current else current + " " + word
        if _text_width(draw, trial, size, bold) <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
            if len(lines) == max_lines - 1:
                break

    if current:
        lines.append(current)

    if len(lines) > max_lines:
        lines = lines[:max_lines]

    consumed = " ".join(lines).split()
    if len(consumed) < len(words) and lines:
        lines[-1] = _fit_text(draw, lines[-1], size, max_width, bold)

    return lines or [""]


def _draw_mixed_center(draw, box, text, size, fill="black", bold=False,
                       max_lines=1):
    x0, y0, x1, y1 = box
    max_width = x1 - x0 - 14
    lines = _wrap_text(
        draw, text, size, max_width, bold, max_lines
    )

    line_h = int(size * 1.30)
    total_h = line_h * len(lines)
    first_center_y = y0 + (y1 - y0 - total_h) / 2 + line_h / 2

    for li, line in enumerate(lines):
        width = _text_width(draw, line, size, bold)
        x = x0 + (x1 - x0 - width) / 2
        cy = first_center_y + li * line_h

        for part in _parts(line):
            font = _font_for_part(part, size, bold)
            draw.text(
                (x, cy),
                part,
                font=font,
                fill=fill,
                anchor="lm",
            )
            x += draw.textlength(part, font=font)


def _draw_mixed_left(draw, box, text, size, fill="black", bold=False):
    x0, y0, x1, y1 = box
    value = _fit_text(draw, text, size, x1 - x0 - 18, bold)
    line_h = int(size * 1.30)
    cy = y0 + (y1 - y0) / 2
    x = x0 + 9

    for part in _parts(value):
        font = _font_for_part(part, size, bold)
        draw.text(
            (x, cy),
            part,
            font=font,
            fill=fill,
            anchor="lm",
        )
        x += draw.textlength(part, font=font)

def _draw_page(q, rows, page_no, total_pages, total_attempts):
    img = Image.new("RGB", (PAGE_W, PAGE_H), "white")
    draw = ImageDraw.Draw(img)

    orange = (242, 126, 12)
    green = (24, 145, 0)
    grid = (35, 35, 35)
    light = (248, 248, 248)
    row_alt = (250, 250, 250)

    x0 = MARGIN
    x1 = PAGE_W - MARGIN
    y = MARGIN

    # ---------- Orange group header ----------
    draw.rectangle(
        (x0, y, x1, y + HEADER_TITLE_H),
        fill=orange,
        outline=grid,
        width=2,
    )
    _draw_mixed_center(draw, (x0, y, x1, y + HEADER_TITLE_H), GROUP_NAME, 42, bold=True)
    y += HEADER_TITLE_H

    # ---------- Test title ----------
    draw.rectangle(
        (x0, y, x1, y + HEADER_SUB_H),
        fill="white",
        outline=grid,
        width=2,
    )
    _draw_mixed_center(draw, (x0, y, x1, y + HEADER_SUB_H), q.get("title", "Practice Set"), 29, bold=True, max_lines=2)
    y += HEADER_SUB_H

    # ---------- Attempt count ----------
    draw.rectangle(
        (x0, y, x1, y + INFO_H),
        fill=light,
        outline=grid,
        width=2,
    )
    _draw_mixed_center(draw, (x0, y, x1, y + INFO_H), f"Rank List  •  Total Unique Attempts: {total_attempts}", 24, bold=True)
    y += INFO_H

    columns = [
        ("Rank", 100),
        ("Name", 410),
        ("Category", 205),
        ("TRUE", 150),
        ("FALSE", 150),
        ("Final Marks", 235),
        ("%", 149),
    ]
    # Exact total width = page width inside margins.
    total_w = x1 - x0
    widths_sum = sum(w for _, w in columns)
    scale = total_w / widths_sum
    widths = [int(w * scale) for _, w in columns]
    widths[-1] += total_w - sum(widths)

    xs = [x0]
    for w in widths:
        xs.append(xs[-1] + w)

    # ---------- Table header ----------
    draw.rectangle(
        (x0, y, x1, y + TABLE_HEADER_H),
        fill=green,
        outline=grid,
        width=2,
    )
    f_head = _font(23, True, devanagari=False)
    for i, (label, _) in enumerate(columns):
        _draw_mixed_center(
            draw,
            (xs[i], y, xs[i + 1], y + TABLE_HEADER_H),
            label,
            23,
            fill="white",
            bold=True,
        )
        if i:
            draw.line(
                (xs[i], y, xs[i], y + TABLE_HEADER_H),
                fill=grid,
                width=2,
            )
    y += TABLE_HEADER_H

    # ---------- Rows ----------
    f_cell = _font(21, False, devanagari=False)
    f_rank = _font(22, True, devanagari=False)

    for idx, r in enumerate(rows):
        fill = "white" if idx % 2 == 0 else row_alt
        draw.rectangle(
            (x0, y, x1, y + ROW_H),
            fill=fill,
            outline=grid,
            width=1,
        )

        values = [
            str(r.get("rank", "")),
            str(r.get("name", "") or ""),
            str(r.get("category", "") or "-"),
            str(r.get("correct", 0)),
            str(r.get("wrong", 0)),
            f"{float(r.get('score', 0) or 0):.2f}",
            f"{float(r.get('percentage', 0) or 0):.2f}",
        ]

        for i, value in enumerate(values):
            box = (xs[i], y, xs[i + 1], y + ROW_H)
            font = f_rank if i == 0 else f_cell
            if i == 1:
                _draw_mixed_left(draw, box, value, 21)
            else:
                _draw_mixed_center(draw, box, value, 21, bold=(i == 0))

            if i < len(values) - 1:
                draw.line(
                    (xs[i + 1], y, xs[i + 1], y + ROW_H),
                    fill=grid,
                    width=1,
                )
        y += ROW_H

    # ---------- Footer ----------
    footer_y = PAGE_H - MARGIN - FOOTER_H
    draw.rounded_rectangle(
        (x0, footer_y, x1, PAGE_H - MARGIN),
        radius=22,
        fill=orange,
        outline=grid,
        width=2,
    )
    useful = "Useful for: Bihar Police  •  SSC GD  •  Railway  •  BSSC  •  SSC CGL  •  RRB"
    _draw_mixed_center(
        draw,
        (x0 + 15, footer_y + 8, x1 - 15, footer_y + 58),
        useful,
        22,
        bold=True,
    )
    _draw_mixed_center(
        draw,
        (x0 + 15, footer_y + 58, x1 - 15, footer_y + 98),
        GROUP_NAME + "  •  Telegram",
        25,
        bold=True,
    )

    # Page number stays readable and separate from the table.
    page_text = f"Page {page_no} / {total_pages}"
    _draw_mixed_left(
        draw,
        (x1 - 180, PAGE_H - 48, x1, PAGE_H - 10),
        page_text,
        18,
        fill=(80, 80, 80),
    )

    return img


def generate_leaderboard_pdf(q, rows):
    """
    Generate a multi-page PDF leaderboard.

    All rows supplied by db.leaderboard() are included; there is no 50-row
    limit. Hindi text is rendered with Noto Sans Devanagari + RAQM so
    matras/shaping remain correct.
    """
    if not rows:
        raise ValueError("No leaderboard rows available")

    total_attempts = len(rows)
    pages = [
        rows[i:i + ROWS_PER_PAGE]
        for i in range(0, total_attempts, ROWS_PER_PAGE)
    ]
    total_pages = len(pages)

    images = []
    try:
        for page_no, page_rows in enumerate(pages, 1):
            images.append(
                _draw_page(
                    q,
                    page_rows,
                    page_no,
                    total_pages,
                    total_attempts,
                )
            )

        temp = tempfile.NamedTemporaryFile(
            suffix=".pdf",
            delete=False,
        )
        temp.close()

        first, rest = images[0], images[1:]
        # JPEG-backed PDF keeps a 1000-user leaderboard practical to send
        # through Telegram while retaining clear text at this page size.
        first.save(
            temp.name,
            "PDF",
            resolution=150.0,
            save_all=True,
            append_images=rest,
        )
        return temp.name
    finally:
        # Images are held in memory only while the PDF is written.
        for image in images:
            try:
                image.close()
            except Exception:
                pass
