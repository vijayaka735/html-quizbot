import os
import sqlite3
import uuid
import json
import re
from datetime import datetime

DB_PATH = os.getenv("DB_PATH", "data.db")


def conn():
    return sqlite3.connect(DB_PATH, timeout=30)


def _normalize_mobile(value):
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[-10:]
    return digits


def _clean_duplicates(c):
    """Keep the first attempt for each non-empty mobile/email per quiz.

    Older database versions allowed duplicate submissions. This cleanup makes
    the new first-attempt-only rule apply to existing data too.
    """
    rows = c.execute(
        """SELECT id, quiz_id, mobile, email
           FROM attempts
           ORDER BY id ASC"""
    ).fetchall()

    seen_mobile = set()
    seen_email = set()
    delete_ids = []

    for row_id, quiz_id, mobile, email in rows:
        mobile_norm = _normalize_mobile(mobile)
        mobile_key = (quiz_id, mobile_norm) if mobile_norm else None
        email_key = (quiz_id, (email or "").strip().lower()) if (email or "").strip() else None

        duplicate = (
            (mobile_key is not None and mobile_key in seen_mobile)
            or (email_key is not None and email_key in seen_email)
        )

        if duplicate:
            delete_ids.append(row_id)
            continue

        if mobile_key is not None:
            seen_mobile.add(mobile_key)
        if email_key is not None:
            seen_email.add(email_key)

    if delete_ids:
        c.executemany("DELETE FROM attempts WHERE id=?", [(x,) for x in delete_ids])


def init_db():
    c = conn()
    c.execute("""CREATE TABLE IF NOT EXISTS quizzes(
        id TEXT PRIMARY KEY, title TEXT, heading TEXT, minutes INTEGER,
        negative REAL, mode TEXT, questions TEXT, created_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS attempts(
        id INTEGER PRIMARY KEY AUTOINCREMENT, quiz_id TEXT, name TEXT,
        mobile TEXT, email TEXT, gender TEXT, category TEXT,
        score REAL, correct INTEGER, wrong INTEGER, unattempted INTEGER,
        percentage REAL, time_taken INTEGER, answers TEXT, created_at TEXT
    )""")
    _clean_duplicates(c)
    c.commit()
    c.close()


def create_quiz(title, heading, minutes, negative, mode, questions):
    qid = "QSG-" + uuid.uuid4().hex[:6].upper()
    c = conn()
    c.execute("INSERT INTO quizzes VALUES(?,?,?,?,?,?,?,?)",
              (qid, title, heading, minutes, negative, mode,
               json.dumps(questions, ensure_ascii=False), datetime.utcnow().isoformat()))
    c.commit(); c.close()
    return qid


def get_quiz(qid):
    c = conn()
    row = c.execute("SELECT * FROM quizzes WHERE id=?", (qid,)).fetchone()
    c.close()
    if not row:
        return None
    return {
        "id": row[0], "title": row[1], "heading": row[2], "minutes": row[3],
        "negative": row[4], "mode": row[5], "questions": json.loads(row[6])
    }


def update_quiz_setting(qid, key, value):
    if key not in ("minutes", "negative"):
        return
    c = conn()
    c.execute(f"UPDATE quizzes SET {key}=? WHERE id=?", (value, qid))
    c.commit(); c.close()


def save_attempt(qid, data):
    q = get_quiz(qid)
    if not q:
        return None

    # A participant gets only one leaderboard entry per quiz. The first
    # submission wins when either the mobile number OR email matches.
    mobile = _normalize_mobile(data.get("mobile", ""))
    email = str(data.get("email", "") or "").strip().lower()

    c = conn()
    c.execute("BEGIN IMMEDIATE")

    duplicate_row = None
    if mobile or email:
        conditions = []
        params = [qid]
        if mobile:
            conditions.append("mobile=?")
            params.append(mobile)
        if email:
            conditions.append("LOWER(email)=?")
            params.append(email)

        duplicate_row = c.execute(
            f"""SELECT id,name,mobile,email,gender,category,score,correct,wrong,
                       unattempted,percentage,time_taken
                FROM attempts
                WHERE quiz_id=? AND ({' OR '.join(conditions)})
                ORDER BY id ASC
                LIMIT 1""",
            params,
        ).fetchone()

    if duplicate_row:
        c.commit()
        c.close()
        return {
            "ok": True,
            "duplicate": True,
            "message": "This mobile number or email has already submitted this test. The first attempt remains on the leaderboard.",
            "score": round(float(duplicate_row[6] or 0), 2),
            "correct": int(duplicate_row[7] or 0),
            "wrong": int(duplicate_row[8] or 0),
            "unattempted": int(duplicate_row[9] or 0),
            "percentage": float(duplicate_row[10] or 0),
            "first_attempt": True,
        }

    questions = q["questions"]
    answers = data.get("answers", [])
    correct = wrong = 0
    for i, a in enumerate(answers):
        if a is None or a == "":
            continue
        try:
            idx = int(a)
        except Exception:
            continue
        if i < len(questions):
            if idx == questions[i]["answer"]:
                correct += 1
            else:
                wrong += 1

    unattempted = max(0, len(questions)-correct-wrong)
    score = correct - wrong*q["negative"]
    total = len(questions)
    percentage = round(max(0, score)/total*100, 2) if total else 0

    c.execute("""INSERT INTO attempts(
        quiz_id,name,mobile,email,gender,category,score,correct,wrong,
        unattempted,percentage,time_taken,answers,created_at
    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
    (qid, data.get("name",""), mobile, email,
     data.get("gender",""), data.get("category",""), score, correct, wrong,
     unattempted, percentage, int(data.get("timeTaken",0)),
     json.dumps(answers), datetime.utcnow().isoformat()))
    c.commit(); c.close()
    return {
        "ok": True,
        "duplicate": False,
        "score": round(score, 2), "correct": correct, "wrong": wrong,
        "unattempted": unattempted, "percentage": percentage,
        "explanations": [x["explanation"] for x in questions]
    }


def leaderboard(qid):
    c = conn()
    rows = c.execute("""SELECT name,category,correct,wrong,score,percentage,time_taken
                        FROM attempts WHERE quiz_id=?
                        ORDER BY score DESC, time_taken ASC, id ASC""", (qid,)).fetchall()
    c.close()
    out=[]
    for n,r in enumerate(rows,1):
        out.append({"rank":n,"name":r[0],"category":r[1],"correct":r[2],"wrong":r[3],
                    "score":r[4],"percentage":r[5],"time_taken":r[6]})
    return out


def quiz_stats(qid):
    c=conn()
    n=c.execute("SELECT COUNT(*) FROM attempts WHERE quiz_id=?", (qid,)).fetchone()[0]
    c.close()
    return {"attempts":n}
