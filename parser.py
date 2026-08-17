import re

def parse_questions(text):
    # Supports blocks separated by blank lines.
    # Correct option is identified by trailing ✅.
    text = text.replace("\r\n", "\n").strip()
    blocks = re.split(r"\n\s*\n(?=[^\n]+)", text)
    questions = []

    current = None
    options = []

    def flush():
        nonlocal current, options
        if not current or len(options) < 2:
            current = None
            options = []
            return
        correct = next((i for i, x in enumerate(options) if x["correct"]), None)
        if correct is None:
            current = None
            options = []
            return
        questions.append({
            "question": current.strip(),
            "options": [x["text"] for x in options],
            "answer": correct,
            "explanation": current_explanation.strip()
        })
        current = None
        options = []

    # A more tolerant line parser.
    current_explanation = ""
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue

        if re.match(r"^Ex\s*:", line, re.I):
            current_explanation = re.sub(r"^Ex\s*:\s*", "", line, flags=re.I)
            i += 1
            continue

        m = re.match(r"^([A-D])\)\s*(.*)$", line)
        if m:
            options.append({
                "text": m.group(2).replace("✅", "").strip(),
                "correct": "✅" in m.group(2)
            })
            i += 1
            continue

        # Start a new question if we already have a complete option set.
        if options and not re.match(r"^[A-D]\)", line):
            flush()
            current_explanation = ""

        if current is None:
            current = line
        else:
            current += " " + line
        i += 1

    flush()
    return questions
