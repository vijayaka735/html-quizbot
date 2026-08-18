import os
import re
import tempfile
import unicodedata
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

GROUP_NAME = "QUICK STUDY GROUP"
PAGE_W, PAGE_H = 1240, 1754
MARGIN_X = 72
TOP_Y = 108
BOTTOM_Y = 88
COLUMN_GAP = 42
COLUMN_W = (PAGE_W - 2 * MARGIN_X - COLUMN_GAP) // 2

BASE = Path(__file__).resolve().parent
FONT_DIR = BASE / "fonts"
DEV_REG = FONT_DIR / "NotoSansDevanagari-Regular.ttf"
DEV_BOLD = FONT_DIR / "NotoSansDevanagari-Bold.ttf"
LAT_REG = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
LAT_BOLD = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")

if not DEV_REG.exists():
    raise RuntimeError(f"Missing font: {DEV_REG}")
if not DEV_BOLD.exists():
    DEV_BOLD = DEV_REG


def _font(size, bold=False, devanagari=True):
    path = DEV_BOLD if bold else DEV_REG
    if not devanagari:
        path = LAT_BOLD if bold else LAT_REG
    layout = getattr(ImageFont, "Layout", None)
    engine = layout.RAQM if layout and hasattr(layout, "RAQM") else None
    kwargs = {"size": size}
    if engine is not None:
        kwargs["layout_engine"] = engine
    return ImageFont.truetype(str(path), **kwargs)


def _has_deva(s):
    return bool(re.search(r"[\u0900-\u097F]", s or ""))


def _pick_font(size, bold, text):
    return _font(size, bold, devanagari=_has_deva(text))


def _clean_text(text, keep_latin=False):
    text = unicodedata.normalize("NFC", str(text or ""))
    lines = []
    paren_en = re.compile(r"\s*\([^()]*[A-Za-z][^()]*\)")
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            if lines and lines[-1] != "":
                lines.append("")
            continue
        if "|" in line:
            lines.append(line)
            continue
        if _has_deva(line):
            line = paren_en.sub("", line)
            line = re.sub(r"\b(Assertion|Reason|Statement|Solution|Question|True|False)\b\s*[:：-]?", "", line, flags=re.I)
            line = re.sub(r"\s{2,}", " ", line).strip()
            lines.append(line)
        elif keep_latin and re.fullmatch(r"[A-Za-z0-9\s.,%+\-×÷=<>≤≥→()\[\]{}$:/]+", line):
            lines.append(line)
        elif not re.search(r"[A-Za-z]", line):
            lines.append(line)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def _hindi_text(text):
    return _clean_text(text, keep_latin=False)


def _table_cell(text):
    # Tables often contain compact values such as "1. 75 dB". Keep those,
    # while still removing English duplicates when Hindi is present.
    return _clean_text(text, keep_latin=True).replace("\n", " ").strip()


def _token_font_size(text, size, bold=False):
    return _pick_font(size, bold, text)


def _measure_mixed(draw, text, size, bold=False):
    total = 0
    parts = re.findall(r"[\u0900-\u097F]+|[A-Za-z]+|\d+(?:\.\d+)?|\s+|[^\u0900-\u097FA-Za-z0-9\s]", str(text))
    for part in parts:
        f = _token_font_size(part, size, bold)
        total += draw.textlength(part, font=f)
    return total


def _draw_mixed(draw, xy, text, size, fill, bold=False):
    x, y = xy
    parts = re.findall(r"[\u0900-\u097F]+|[A-Za-z]+|\d+(?:\.\d+)?|\s+|[^\u0900-\u097FA-Za-z0-9\s]", str(text))
    for part in parts:
        f = _token_font_size(part, size, bold)
        draw.text((x, y), part, font=f, fill=fill)
        x += draw.textlength(part, font=f)
    return x


def _wrap_mixed(draw, text, size, max_width, bold=False):
    result = []
    for paragraph in unicodedata.normalize("NFC", str(text or "")).split("\n"):
        if not paragraph:
            result.append("")
            continue
        words = paragraph.split()
        if not words:
            result.append("")
            continue
        current = words[0]
        for word in words[1:]:
            trial = current + " " + word
            if _measure_mixed(draw, trial, size, bold) <= max_width:
                current = trial
            else:
                result.append(current)
                current = word
        result.append(current)
    return result


def _line_height(size):
    return int(size * 1.42)


def _parse_table(text):
    rows = []
    for line in str(text or "").splitlines():
        line = line.strip()
        if "|" not in line:
            continue
        if re.fullmatch(r"\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?", line):
            continue
        cells = [_table_cell(c) for c in line.strip("|").split("|")]
        if len(cells) >= 2:
            rows.append(cells)
    return rows if len(rows) >= 2 else None


def _draw_table(draw, x, y, rows, width):
    cols = max(len(r) for r in rows)
    rows = [r + [""] * (cols - len(r)) for r in rows]
    col_w = width / cols
    regular_size = 17
    bold_size = 17
    pad = 9
    heights = []
    for ri, row in enumerate(rows):
        size = bold_size if ri == 0 else regular_size
        max_lines = 1
        for cell in row:
            max_lines = max(max_lines, len(_wrap_mixed(draw, cell, size, col_w - 2 * pad, ri == 0)))
        heights.append(max(42, max_lines * _line_height(size) + 2 * pad))
    yy = y
    for ri, row in enumerate(rows):
        hh = heights[ri]
        for ci, cell in enumerate(row):
            xx = x + ci * col_w
            fill = "#EAF3EA" if ri == 0 else "#FFFFFF"
            draw.rectangle((xx, yy, xx + col_w, yy + hh), fill=fill, outline="#666666", width=2)
            size = bold_size if ri == 0 else regular_size
            lines = _wrap_mixed(draw, cell, size, col_w - 2 * pad, ri == 0)
            ty = yy + pad
            for line in lines:
                _draw_mixed(draw, (xx + pad, ty), line, size, "#202020", ri == 0)
                ty += _line_height(size)
        yy += hh
    return yy


def _question_height(draw, q, width):
    qsize, osize, esize = 20, 18, 16
    text = str(q.get("question", ""))
    table = _parse_table(text)
    non_table = "\n".join(line for line in text.splitlines() if "|" not in line) if table else text
    h = len(_wrap_mixed(draw, _hindi_text(non_table), qsize, width, True)) * _line_height(qsize) + 10
    if table:
        # Conservative estimate; the actual table renderer will determine height.
        h += 46 * len(table) + 12
    for option in q.get("options", []):
        h += len(_wrap_mixed(draw, _hindi_text(option), osize, width - 12)) * _line_height(osize) + 5
    exp = _hindi_text(q.get("explanation", ""))
    if exp:
        h += 30 + len(_wrap_mixed(draw, "व्याख्या: " + exp, esize, width - 30)) * _line_height(esize) + 14
    return h + 20


def _draw_question(draw, x, y, number, q, width):
    qsize, osize, esize = 20, 18, 16
    dark = "#202020"
    text = str(q.get("question", ""))
    table = _parse_table(text)
    non_table = "\n".join(line for line in text.splitlines() if "|" not in line) if table else text
    qtext = _hindi_text(non_table)
    lines = _wrap_mixed(draw, f"{number}. {qtext}", qsize, width, True)
    for line in lines:
        _draw_mixed(draw, (x, y), line, qsize, dark, True)
        y += _line_height(qsize)
    y += 4

    if table:
        y = _draw_table(draw, x, y, table, width) + 12

    labels = ["(क)", "(ख)", "(ग)", "(घ)"]
    for idx, option in enumerate(q.get("options", [])):
        op = _hindi_text(option)
        if not op:
            continue
        label = labels[idx] if idx < 4 else f"({idx + 1})"
        for line in _wrap_mixed(draw, f"{label} {op}", osize, width - 10):
            _draw_mixed(draw, (x + 7, y), line, osize, dark)
            y += _line_height(osize)
        y += 3

    exp = _hindi_text(q.get("explanation", ""))
    if exp:
        box_text = "व्याख्या: " + exp
        lines = _wrap_mixed(draw, box_text, esize, width - 32)
        box_h = max(55, len(lines) * _line_height(esize) + 20)
        draw.rounded_rectangle((x, y, x + width, y + box_h), radius=6, fill="#E8F5E9", outline="#43A047", width=2)
        ty = y + 9
        for line in lines:
            _draw_mixed(draw, (x + 13, ty), line, esize, "#1B5E20")
            ty += _line_height(esize)
        y += box_h + 11
    return y + 7


def _new_page(title, heading, page_no):
    im = Image.new("RGB", (PAGE_W, PAGE_H), "white")
    d = ImageDraw.Draw(im)
    _draw_mixed(d, (MARGIN_X, 34), GROUP_NAME, 22, "#7D1524", True)
    _draw_mixed(d, (PAGE_W - MARGIN_X - 92, 38), "अभ्यास हेतु", 15, "#555555")
    d.line((MARGIN_X, 80, PAGE_W - MARGIN_X, 80), fill="#8B1E2D", width=2)
    if page_no == 1:
        _draw_mixed(d, (PAGE_W // 2, 115), GROUP_NAME, 29, "#7D1524", True)
        _draw_mixed(d, (PAGE_W // 2, 160), _hindi_text(heading) or "", 18, "#333333")
        _draw_mixed(d, (PAGE_W // 2, 187), _hindi_text(title) or "अभ्यास प्रश्नपत्र", 18, "#333333")
        return im, TOP_Y + 110
    return im, TOP_Y


def generate_quiz_pdf(quiz):
    """Generate Hindi PDF with correct Devanagari shaping, real tables and green explanations."""
    title = quiz.get("title", "अभ्यास प्रश्नपत्र")
    heading = quiz.get("heading", "")
    questions = quiz.get("questions") or []

    pages = []
    page_no = 1
    page, y = _new_page(title, heading, page_no)
    draw = ImageDraw.Draw(page)
    x_positions = [MARGIN_X, MARGIN_X + COLUMN_W + COLUMN_GAP]
    col = 0
    first_page_start = y

    for i, q in enumerate(questions, 1):
        needed = _question_height(draw, q, COLUMN_W)
        if y + needed > PAGE_H - BOTTOM_Y:
            if col == 0:
                col = 1
                y = first_page_start if page_no == 1 else TOP_Y
            else:
                pages.append(page)
                page_no += 1
                page, y = _new_page(title, heading, page_no)
                draw = ImageDraw.Draw(page)
                col = 0
        x = x_positions[col]
        y = _draw_question(draw, x, y, i, q, COLUMN_W)

    pages.append(page)
    total = len(pages)
    for idx, im in enumerate(pages, 1):
        d = ImageDraw.Draw(im)
        d.line((MARGIN_X, PAGE_H - 55, PAGE_W - MARGIN_X, PAGE_H - 55), fill="#BDBDBD", width=1)
        _draw_mixed(d, (MARGIN_X, PAGE_H - 43), GROUP_NAME, 12, "#666666")
        _draw_mixed(d, (PAGE_W - MARGIN_X - 80, PAGE_H - 43), f"पृष्ठ {idx} / {total}", 12, "#666666")

    fd, path = tempfile.mkstemp(prefix="qsg_", suffix=".pdf")
    os.close(fd)
    pages[0].save(path, "PDF", resolution=150.0, save_all=True, append_images=pages[1:])
    return path
