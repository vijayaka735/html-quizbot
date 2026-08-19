import os
import re
import tempfile
import unicodedata
from datetime import datetime
from pathlib import Path
from functools import lru_cache

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


# ---------------------------------------------------------------------------
# FONT CACHE
# Loading a TTF file repeatedly is expensive. Keep every requested font
# object in memory for the lifetime of this process.
# ---------------------------------------------------------------------------
@lru_cache(maxsize=64)
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


@lru_cache(maxsize=8192)
def _has_deva(text):
    return bool(re.search(r"[\u0900-\u097F]", text or ""))


@lru_cache(maxsize=8192)
def _pick_font(size, bold, text):
    return _font(size, bold, _has_deva(text))


@lru_cache(maxsize=8192)
def _clean_text_cached(text, keep_latin=False):
    """Keep source question text intact. Only normalize whitespace/Unicode.

    In particular, do NOT translate A/B/C/D to Hindi labels and do NOT remove
    words such as Assertion, Reason, Statement or Solution from bilingual
    source text.
    """
    text = unicodedata.normalize("NFC", str(text or ""))
    lines = []

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            if lines and lines[-1] != "":
                lines.append("")
            continue
        lines.append(line)

    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def _clean_text(text, keep_latin=False):
    return _clean_text_cached(str(text or ""), keep_latin)


def _hindi_text(text):
    return _clean_text(text, keep_latin=False)


@lru_cache(maxsize=8192)
def _table_cell_cached(text):
    return _clean_text_cached(
        str(text or ""),
        True,
    ).replace("\n", " ").strip()


def _table_cell(text):
    return _table_cell_cached(str(text or ""))


@lru_cache(maxsize=8192)
def _token_parts(text):
    return tuple(
        re.findall(
            r"[\u0900-\u097F]+|[A-Za-z]+|\d+(?:\.\d+)?|\s+|[^\u0900-\u097FA-Za-z0-9\s]",
            str(text),
        )
    )


def _token_font_size(text, size, bold=False):
    return _pick_font(size, bold, text)


# ---------------------------------------------------------------------------
# SHARED MEASUREMENT CANVAS
# ---------------------------------------------------------------------------
_MEASURE_IMAGE = Image.new(
    "RGB",
    (1, 1),
    "white",
)

_MEASURE_DRAW = ImageDraw.Draw(_MEASURE_IMAGE)


# ---------------------------------------------------------------------------
# TOKEN WIDTH CACHE
# ---------------------------------------------------------------------------
@lru_cache(maxsize=32768)
def _token_width(part, size, bold=False):
    f = _token_font_size(
        part,
        size,
        bold,
    )

    return _MEASURE_DRAW.textlength(
        part,
        font=f,
    )


# ---------------------------------------------------------------------------
# COMPLETE TEXT WIDTH CACHE
# ---------------------------------------------------------------------------
@lru_cache(maxsize=32768)
def _measure_mixed_cached(text, size, bold=False):
    total = 0.0

    for part in _token_parts(str(text)):
        total += _token_width(
            part,
            size,
            bold,
        )

    return total


def _measure_mixed(draw, text, size, bold=False):
    # draw kept in signature for compatibility
    return _measure_mixed_cached(
        str(text),
        size,
        bold,
    )


# ---------------------------------------------------------------------------
# WRAP CACHE
# ---------------------------------------------------------------------------
@lru_cache(maxsize=16384)
def _wrap_mixed_cached(
    text,
    size,
    max_width,
    bold=False,
):
    result = []

    for paragraph in unicodedata.normalize(
        "NFC",
        str(text or ""),
    ).split("\n"):

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

            if _measure_mixed_cached(
                trial,
                size,
                bold,
            ) <= max_width:
                current = trial
            else:
                result.append(current)
                current = word

        result.append(current)

    return tuple(result)


def _wrap_mixed(
    draw,
    text,
    size,
    max_width,
    bold=False,
):
    return list(
        _wrap_mixed_cached(
            str(text or ""),
            size,
            max_width,
            bold,
        )
    )


def _line_height(size):
    return int(size * 1.42)


# ---------------------------------------------------------------------------
# TABLE PARSER CACHE
# ---------------------------------------------------------------------------
@lru_cache(maxsize=4096)
def _parse_table_cached(text):
    rows = []

    for line in str(text or "").splitlines():
        line = line.strip()

        if "|" not in line:
            continue

        if re.fullmatch(
            r"\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?",
            line,
        ):
            continue

        cells = [
            _table_cell(c)
            for c in line.strip("|").split("|")
        ]

        if len(cells) >= 2:
            rows.append(tuple(cells))

    return tuple(rows) if len(rows) >= 2 else None


def _parse_table(text):
    rows = _parse_table_cached(
        str(text or "")
    )

    if not rows:
        return None

    return [list(row) for row in rows]


# ---------------------------------------------------------------------------
# QUESTION HEIGHT CACHE
# ---------------------------------------------------------------------------
@lru_cache(maxsize=8192)
def _question_height_cached(
    question_text,
    options_tuple,
    explanation,
    width,
):
    qsize, osize, esize = 20, 18, 16

    text = str(question_text or "")

    table = _parse_table_cached(text)

    if table:
        non_table = "\n".join(
            line
            for line in text.splitlines()
            if "|" not in line
        )
    else:
        non_table = text

    cleaned_question = _clean_text_cached(
        non_table,
        False,
    )

    h = (
        len(
            _wrap_mixed_cached(
                cleaned_question,
                qsize,
                width,
                True,
            )
        )
        * _line_height(qsize)
        + 10
    )

    if table:
        h += 46 * len(table) + 12

    for option in options_tuple:
        cleaned_option = _clean_text_cached(
            str(option or ""),
            False,
        )

        h += (
            len(
                _wrap_mixed_cached(
                    cleaned_option,
                    osize,
                    width - 12,
                    False,
                )
            )
            * _line_height(osize)
            + 5
        )

    exp = _clean_text_cached(
        str(explanation or ""),
        False,
    )

    if exp:
        h += (
            30
            + len(
                _wrap_mixed_cached(
                    "व्याख्या: " + exp,
                    esize,
                    width - 30,
                    False,
                )
            )
            * _line_height(esize)
            + 14
        )

    return h + 20


def _question_height(draw, q, width):
    options = tuple(
        str(x or "")
        for x in (q.get("options") or [])
    )

    return _question_height_cached(
        str(q.get("question", "")),
        options,
        str(q.get("explanation", "") or ""),
        width,
    )


# ---------------------------------------------------------------------------
# TABLE DRAWING
# ---------------------------------------------------------------------------
def _draw_table(
    draw,
    x,
    y,
    rows,
    width,
):
    cols = max(
        len(r)
        for r in rows
    )

    rows = [
        r + [""] * (cols - len(r))
        for r in rows
    ]

    col_w = width / cols

    regular_size = 17
    bold_size = 17
    pad = 9

    heights = []

    for ri, row in enumerate(rows):
        size = (
            bold_size
            if ri == 0
            else regular_size
        )

        max_lines = 1

        for cell in row:
            max_lines = max(
                max_lines,
                len(
                    _wrap_mixed(
                        draw,
                        cell,
                        size,
                        col_w - 2 * pad,
                        ri == 0,
                    )
                ),
            )

        heights.append(
            max(
                42,
                max_lines
                * _line_height(size)
                + 2 * pad,
            )
        )

    yy = y

    for ri, row in enumerate(rows):
        hh = heights[ri]

        for ci, cell in enumerate(row):
            xx = x + ci * col_w

            fill = (
                "#EAF3EA"
                if ri == 0
                else "#FFFFFF"
            )

            draw.rectangle(
                (
                    xx,
                    yy,
                    xx + col_w,
                    yy + hh,
                ),
                fill=fill,
                outline="#666666",
                width=2,
            )

            size = (
                bold_size
                if ri == 0
                else regular_size
            )

            lines = _wrap_mixed(
                draw,
                cell,
                size,
                col_w - 2 * pad,
                ri == 0,
            )

            ty = yy + pad

            for line in lines:
                _draw_mixed(
                    draw,
                    (xx + pad, ty),
                    line,
                    size,
                    "#202020",
                    ri == 0,
                )

                ty += _line_height(size)

        yy += hh

    return yy


# ---------------------------------------------------------------------------
# MIXED TEXT DRAWING
# ---------------------------------------------------------------------------
def _draw_mixed(
    draw,
    xy,
    text,
    size,
    fill,
    bold=False,
):
    x, y = xy

    for part in _token_parts(str(text)):
        f = _token_font_size(
            part,
            size,
            bold,
        )

        draw.text(
            (x, y),
            part,
            font=f,
            fill=fill,
        )

        x += _token_width(
            part,
            size,
            bold,
        )

    return x


# ---------------------------------------------------------------------------
# QUESTION DRAWING
# ---------------------------------------------------------------------------
def _draw_question(
    draw,
    x,
    y,
    number,
    q,
    width,
):
    qsize, osize, esize = 20, 18, 16

    dark = "#202020"

    text = str(
        q.get("question", "")
    )

    table = _parse_table_cached(text)

    if table:
        non_table = "\n".join(
            line
            for line in text.splitlines()
            if "|" not in line
        )
    else:
        non_table = text

    qtext = _clean_text_cached(
        non_table,
        False,
    )

    lines = _wrap_mixed_cached(
        f"{number}. {qtext}",
        qsize,
        width,
        True,
    )

    for line in lines:
        _draw_mixed(
            draw,
            (x, y),
            line,
            qsize,
            dark,
            True,
        )

        y += _line_height(qsize)

    y += 4

    if table:
        y = _draw_table(
            draw,
            x,
            y,
            [list(row) for row in table],
            width,
        ) + 12

    # Keep the original English option labels. The parser stores option text
    # without A/B/C/D, so add the labels back here and never translate them.
    labels = ["A)", "B)", "C)", "D)"]

    for idx, option in enumerate(
        q.get("options", []) or []
    ):
        op = _clean_text_cached(
            str(option or ""),
            False,
        )

        if not op:
            continue

        label = (
            labels[idx]
            if idx < 4
            else f"{chr(65 + idx)})"
        )

        lines = _wrap_mixed_cached(
            f"{label} {op}",
            osize,
            width - 10,
            False,
        )

        for line in lines:
            _draw_mixed(
                draw,
                (x + 7, y),
                line,
                osize,
                dark,
            )

            y += _line_height(osize)

        y += 3

    exp = _clean_text_cached(
        str(q.get("explanation", "") or ""),
        False,
    )

    if exp:
        answer_index = q.get("answer")
        if isinstance(answer_index, int) and 0 <= answer_index < 26:
            answer_label = chr(65 + answer_index)
        else:
            answer_label = ""

        solution_prefix = (
            f"Solution ({answer_label})"
            if answer_label
            else "Solution"
        )
        box_text = solution_prefix + "\n" + exp

        lines = _wrap_mixed_cached(
            box_text,
            esize,
            width - 32,
            False,
        )

        box_h = max(
            62,
            len(lines)
            * _line_height(esize)
            + 24,
        )

        # Reference-style light yellow/cream solution box.
        draw.rounded_rectangle(
            (
                x,
                y,
                x + width,
                y + box_h,
            ),
            radius=6,
            fill="#FFF8E1",
            outline="#C9B77E",
            width=2,
        )

        ty = y + 9

        for line_no, line in enumerate(lines):
            _draw_mixed(
                draw,
                (x + 13, ty),
                line,
                esize,
                "#4A4028" if line_no else "#2F2A1F",
                bool(line_no == 0),
            )
            ty += _line_height(esize)

        y += box_h + 11

    return y + 7


# ---------------------------------------------------------------------------
# PAGE HEADER HELPER
# ---------------------------------------------------------------------------
def _draw_centered(draw, text, center_x, y, size, fill, bold=False):
    text = str(text or "")
    width = _measure_mixed(draw, text, size, bold)
    _draw_mixed(draw, (center_x - width / 2, y), text, size, fill, bold)


# ---------------------------------------------------------------------------
# NEW PAGE
# ---------------------------------------------------------------------------
def _new_page(
    title,
    heading,
    page_no,
):
    im = Image.new(
        "RGB",
        (PAGE_W, PAGE_H),
        "white",
    )

    d = ImageDraw.Draw(im)

    # Subtle red watermark first, so all real content remains readable above it.
    layer = Image.new("RGBA", (PAGE_W, PAGE_H), (255, 255, 255, 0))
    ld = ImageDraw.Draw(layer)
    wm_font = _font(64, True, False)
    wm = "QUICK QUIZ BOT"
    bbox = ld.textbbox((0, 0), wm, font=wm_font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    ld.text(
        ((PAGE_W - tw) / 2, (PAGE_H - th) / 2),
        wm,
        font=wm_font,
        fill=(180, 30, 45, 24),
    )
    layer = layer.rotate(32, resample=Image.Resampling.BICUBIC, expand=False)
    im = Image.alpha_composite(im.convert("RGBA"), layer).convert("RGB")
    d = ImageDraw.Draw(im)

    _draw_mixed(
        d,
        (MARGIN_X, 34),
        GROUP_NAME,
        22,
        "#7D1524",
        True,
    )

    date_text = datetime.now().strftime("GENERATED: %d-%b-%Y").upper()
    date_width = _measure_mixed(d, date_text, 14, False)
    _draw_mixed(
        d,
        (PAGE_W - MARGIN_X - date_width, 38),
        date_text,
        14,
        "#666666",
        False,
    )

    d.line(
        (
            MARGIN_X,
            80,
            PAGE_W - MARGIN_X,
            80,
        ),
        fill="#8B1E2D",
        width=2,
    )

    if page_no == 1:
        _draw_centered(
            d,
            GROUP_NAME,
            PAGE_W // 2,
            115,
            29,
            "#7D1524",
            True,
        )

        subject = _hindi_text(heading) or ""
        if subject:
            _draw_centered(
                d,
                subject,
                PAGE_W // 2,
                160,
                18,
                "#333333",
                True,
            )

        _draw_centered(
            d,
            _hindi_text(title) or "अभ्यास प्रश्नपत्र",
            PAGE_W // 2,
            187,
            18,
            "#333333",
            True,
        )

        return im, TOP_Y + 110

    return im, TOP_Y


# ---------------------------------------------------------------------------
# MAIN PDF GENERATOR
# ---------------------------------------------------------------------------
def generate_quiz_pdf(quiz):
    """Generate the existing quiz PDF with bilingual-safe labels, tables and solution boxes."""

    title = quiz.get(
        "title",
        "अभ्यास प्रश्नपत्र",
    )

    heading = quiz.get(
        "heading",
        "",
    )

    questions = quiz.get(
        "questions"
    ) or []

    if not questions:
        raise ValueError(
            "No questions available for PDF generation."
        )

    pages = []

    page_no = 1

    page, y = _new_page(
        title,
        heading,
        page_no,
    )

    draw = ImageDraw.Draw(page)

    x_positions = [
        MARGIN_X,
        MARGIN_X
        + COLUMN_W
        + COLUMN_GAP,
    ]

    col = 0

    first_page_start = y

    for i, q in enumerate(
        questions,
        1,
    ):
        needed = _question_height(
            draw,
            q,
            COLUMN_W,
        )

        if y + needed > PAGE_H - BOTTOM_Y:

            if col == 0:
                col = 1

                y = (
                    first_page_start
                    if page_no == 1
                    else TOP_Y
                )

            else:
                pages.append(page)

                page_no += 1

                page, y = _new_page(
                    title,
                    heading,
                    page_no,
                )

                draw = ImageDraw.Draw(page)

                col = 0

        x = x_positions[col]

        y = _draw_question(
            draw,
            x,
            y,
            i,
            q,
            COLUMN_W,
        )

    pages.append(page)

    total = len(pages)

    for idx, im in enumerate(
        pages,
        1,
    ):
        d = ImageDraw.Draw(im)

        d.line(
            (
                MARGIN_X,
                PAGE_H - 55,
                PAGE_W - MARGIN_X,
                PAGE_H - 55,
            ),
            fill="#BDBDBD",
            width=1,
        )

        _draw_mixed(
            d,
            (
                MARGIN_X,
                PAGE_H - 43,
            ),
            GROUP_NAME,
            12,
            "#666666",
        )

        _draw_mixed(
            d,
            (
                PAGE_W - MARGIN_X - 80,
                PAGE_H - 43,
            ),
            f"पृष्ठ {idx} / {total}",
            12,
            "#666666",
        )

    fd, path = tempfile.mkstemp(
        prefix="qsg_",
        suffix=".pdf",
    )

    os.close(fd)

    # Keep the existing PDF output format and quality.
    pages[0].save(
        path,
        "PDF",
        resolution=150.0,
        save_all=True,
        append_images=pages[1:],
    )

    return path
