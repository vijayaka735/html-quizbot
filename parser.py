import re


def parse_questions(text):
    """Parse MCQs from TXT without forcing one fixed question format.

    The complete text before A-D options is kept as the question. This supports
    normal/direct questions, numbered statements, Assertion/Reason,
    Statement/Reason, numerical/math questions, and match-the-following.
    Correct options are marked with the existing ✅ marker.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    questions = []

    current_lines = []
    options = []
    explanation_lines = []
    in_explanation = False

    def reset():
        nonlocal current_lines, options, explanation_lines, in_explanation
        current_lines = []
        options = []
        explanation_lines = []
        in_explanation = False

    def flush():
        nonlocal current_lines, options, explanation_lines, in_explanation
        if not current_lines or len(options) < 2:
            reset()
            return

        correct = next((i for i, item in enumerate(options) if item["correct"]), None)
        if correct is None:
            reset()
            return

        questions.append({
            "question": "\n".join(current_lines).strip(),
            "options": [item["text"] for item in options],
            "answer": correct,
            "explanation": "\n".join(explanation_lines).strip(),
        })
        reset()

    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()

        if not line:
            i += 1
            continue

        ex = re.match(r"^Ex\s*:\s*(.*)$", line, re.I)
        if ex:
            in_explanation = True
            first = ex.group(1).strip()
            if first:
                explanation_lines.append(first)
            i += 1
            continue

        if in_explanation:
            # The first non-empty line after Ex: starts the next question.
            flush()
            continue

        # A-D options. Existing A) format remains fully supported; A., (A),
        # and A: are also accepted for convenience.
        m = re.match(r"^\(?([A-D])\)?(?:[\).:\-])\s*(.*)$", line, re.I)
        if m:
            letter = m.group(1).upper()
            option_text = m.group(2).strip()

            if options and letter == "A":
                flush()

            options.append({
                "text": option_text.replace("✅", "").strip(),
                "correct": "✅" in option_text,
            })
            i += 1
            continue

        if options:
            # A non-option after A-D is a new question (normally an Ex: line,
            # which is handled above). Do not silently append it to an option.
            flush()
            continue

        # Preserve every logical source line. Thus input such as:
        # कथन (A): ...
        # कारण (R): ...
        # or 1. ... / 2. ...
        # remains separated in the test page.
        current_lines.append(line)
        i += 1

    flush()
    return questions
