import os
import re
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    KeepTogether,
    PageBreak,
)

GROUP_NAME = "QUICK STUDY GROUP"


def _find_font(patterns):
    roots = [
        str(Path(__file__).resolve().parent / "fonts"),
        "/usr/share/fonts/truetype/noto",
        "/usr/share/fonts/opentype/noto",
        "/usr/share/fonts/truetype/freefont",
        "/usr/share/fonts/truetype/dejavu",
    ]
    for root in roots:
        if not os.path.isdir(root):
            continue
        for name in patterns:
            p = os.path.join(root, name)
            if os.path.exists(p):
                return p
    return None


REGULAR_FONT = _find_font([
    "NotoSansDevanagari-Regular.ttf",
    "NotoSansDevanagariUI-Regular.ttf",
    "FreeSerif.ttf",
    "DejaVuSans.ttf",
])
BOLD_FONT = _find_font([
    "NotoSansDevanagari-Bold.ttf",
    "NotoSansDevanagariUI-Bold.ttf",
    "NotoSerifDevanagari-Bold.ttf",
    "FreeSerifBold.ttf",
    "DejaVuSans-Bold.ttf",
])

if not REGULAR_FONT:
    raise RuntimeError("Devanagari-compatible font not found on the server")
if not BOLD_FONT:
    BOLD_FONT = REGULAR_FONT

pdfmetrics.registerFont(TTFont("QSGDeva", REGULAR_FONT))
pdfmetrics.registerFont(TTFont("QSGDevaBold", BOLD_FONT))

PAGE_W, PAGE_H = A4
LEFT = 13 * mm
RIGHT = 13 * mm
TOP = 26 * mm
BOTTOM = 16 * mm
GAP = 8 * mm
COLUMN_W = (PAGE_W - LEFT - RIGHT - GAP) / 2


# Common English labels/words are removed from bilingual source text when a
# Hindi counterpart is present. This is deliberately conservative: it does
# not invent translations and therefore does not change the actual question.
_LATIN_RE = re.compile(r"[A-Za-z]")
_DEV_RE = re.compile(r"[\u0900-\u097F]")
_PAREN_EN_RE = re.compile(r"\s*\([^()]*[A-Za-z][^()]*\)")


def _hindi_line(line):
    line = str(line or "").strip()
    if not line:
        return ""

    # Markdown table separators are handled separately.
    if re.fullmatch(r"[|:\-\s]+", line):
        return line

    # If the line contains Devanagari, keep it and remove only parenthetical
    # English duplicates such as (Sound), (Ultrasonic Waves), etc.
    if _DEV_RE.search(line):
        line = _PAREN_EN_RE.sub("", line)
        # Remove common English-only headings/labels while preserving Hindi.
        line = re.sub(r"\b(Assertion|Reason|Statement|Solution|Question|Ex|True|False)\b\s*[:：-]?", "", line, flags=re.I)
        line = re.sub(r"\s{2,}", " ", line).strip()
        return line

    # If there is no Hindi at all, keep formulas/numbers but drop prose-only
    # English. This prevents an English duplicate from taking over the Hindi
    # PDF; the source remains unchanged in the HTML test.
    if _LATIN_RE.search(line):
        return ""
    return line


def _hindi_text(text):
    lines = []
    for raw in str(text or "").splitlines():
        value = _hindi_line(raw)
        if value:
            lines.append(value)
    return "\n".join(lines).strip()


def _clean_math(text):
    text = str(text or "")
    text = text.replace("\\text{", "").replace("\\mathrm{", "")
    text = text.replace("\\times", "×").replace("\\cdot", "·")
    text = text.replace("\\le", "≤").replace("\\ge", "≥")
    text = text.replace("\\rightarrow", "→").replace("\\to", "→")
    text = text.replace("\\lambda", "λ").replace("\\Delta", "Δ")
    text = re.sub(r"\\frac\{([^{}]+)\}\{([^{}]+)\}", r"(\1/\2)", text)
    text = re.sub(r"\\[a-zA-Z]+", "", text)
    text = text.replace("$", "")
    text = text.replace("{", "").replace("}", "")
    return text


def _para(text, style):
    text = _clean_math(_hindi_text(text))
    if not text:
        return None
    # Preserve line breaks.
    safe = escape(text).replace("\n", "<br/>")
    return Paragraph(safe, style)


class NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        canvas.Canvas.__init__(self, *args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_number(total)
            canvas.Canvas.showPage(self)
        canvas.Canvas.save(self)

    def draw_page_number(self, total):
        self.saveState()
        self.setFont("QSGDeva", 7.5)
        self.setFillColor(colors.HexColor("#555555"))
        self.drawString(LEFT, 7 * mm, GROUP_NAME)
        self.drawRightString(PAGE_W - RIGHT, 7 * mm, f"पृष्ठ {self._pageNumber} / {total}")
        self.restoreState()


class QSGDocTemplate(BaseDocTemplate):
    def __init__(self, filename, **kwargs):
        BaseDocTemplate.__init__(self, filename, pagesize=A4, **kwargs)
        frame1 = Frame(LEFT, BOTTOM, COLUMN_W, PAGE_H - TOP - BOTTOM, id="left", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        frame2 = Frame(LEFT + COLUMN_W + GAP, BOTTOM, COLUMN_W, PAGE_H - TOP - BOTTOM, id="right", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        self.addPageTemplates([PageTemplate(id="TwoCol", frames=[frame1, frame2], onPage=self._header)])

    @staticmethod
    def _header(canv, doc):
        canv.saveState()
        canv.setStrokeColor(colors.HexColor("#8B1E2D"))
        canv.setLineWidth(1.2)
        canv.line(LEFT, PAGE_H - 16 * mm, PAGE_W - RIGHT, PAGE_H - 16 * mm)
        canv.setFont("Helvetica-Bold", 12)
        canv.setFillColor(colors.HexColor("#7D1524"))
        canv.drawString(LEFT, PAGE_H - 12 * mm, GROUP_NAME)
        canv.setFont("QSGDeva", 7.5)
        canv.setFillColor(colors.HexColor("#555555"))
        canv.drawRightString(PAGE_W - RIGHT, PAGE_H - 12 * mm, "अभ्यास हेतु")
        canv.restoreState()


def _styles():
    return {
        "q": ParagraphStyle("q", fontName="QSGDevaBold", fontSize=9.3, leading=13.2, textColor=colors.HexColor("#202020"), spaceAfter=3),
        "opt": ParagraphStyle("opt", fontName="QSGDeva", fontSize=8.5, leading=11.8, textColor=colors.HexColor("#202020"), leftIndent=2),
        "sol": ParagraphStyle("sol", fontName="QSGDeva", fontSize=7.8, leading=10.8, textColor=colors.HexColor("#3F321D")),
        "solhead": ParagraphStyle("solhead", fontName="QSGDevaBold", fontSize=7.8, leading=10.5, textColor=colors.HexColor("#6B4A11")),
        "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=16, leading=20, alignment=TA_CENTER, textColor=colors.HexColor("#7D1524")),
        "subtitle": ParagraphStyle("subtitle", fontName="QSGDeva", fontSize=9.2, leading=12, alignment=TA_CENTER, textColor=colors.HexColor("#333333")),
    }


def _question_block(number, q, styles):
    qtext = q.get("question", "")
    qpara = _para(f"{number}. {qtext}", styles["q"])
    if not qpara:
        return []

    items = [qpara]
    labels = ["(क)", "(ख)", "(ग)", "(घ)"]
    for idx, option in enumerate(q.get("options", [])):
        op = _hindi_text(option)
        if not op:
            continue
        p = _para(f"{labels[idx] if idx < 4 else '(' + str(idx + 1) + ')'} {op}", styles["opt"])
        if p:
            items.extend([Spacer(1, 1.2 * mm), p])

    explanation = _hindi_text(q.get("explanation", ""))
    if explanation:
        sol = _para("व्याख्या: " + explanation, styles["sol"])
        if sol:
            box = Table([[sol]], colWidths=[COLUMN_W - 7 * mm])
            box.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FFF7E6")),
                ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#C9A86A")),
                ("LEFTPADDING", (0, 0), (-1, -1), 3.5 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3.5 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 2.2 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2 * mm),
            ]))
            items.extend([Spacer(1, 2 * mm), box])

    return [KeepTogether(items), Spacer(1, 4 * mm)]


def generate_quiz_pdf(quiz):
    """Generate a Hindi-focused, two-column exam-style PDF for a quiz."""
    fd, path = tempfile.mkstemp(prefix="qsg_", suffix=".pdf")
    os.close(fd)

    styles = _styles()
    doc = QSGDocTemplate(path, leftMargin=LEFT, rightMargin=RIGHT, topMargin=TOP, bottomMargin=BOTTOM)

    story = []
    story.append(Paragraph(escape(GROUP_NAME), styles["title"]))
    story.append(Spacer(1, 2 * mm))
    title = _hindi_text(quiz.get("title", "अभ्यास प्रश्नपत्र")) or "अभ्यास प्रश्नपत्र"
    story.append(Paragraph(escape(title), styles["subtitle"]))
    heading = _hindi_text(quiz.get("heading", ""))
    if heading:
        story.append(Paragraph(escape(heading), styles["subtitle"]))
    story.append(Spacer(1, 5 * mm))

    questions = quiz.get("questions") or []
    for i, q in enumerate(questions, 1):
        story.extend(_question_block(i, q, styles))

    if not questions:
        story.append(Paragraph("इस टेस्ट में कोई प्रश्न उपलब्ध नहीं है।", styles["q"]))

    doc.build(story, canvasmaker=NumberedCanvas)
    return path
