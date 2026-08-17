import os
import sqlite3
import uuid
import json
from datetime import datetime

DB_PATH = os.getenv("DB_PATH", "data.db")

def conn():
    return sqlite3.connect(DB_PATH)

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
    if not row: return None
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
    questions = q["questions"]
    answers = data.get("answers", [])
    correct = wrong = 0
    for i, a in enumerate(answers):
        if a is None or a == "":
            continue
        try: idx = int(a)
        except: continue
        if i < len(questions):
            if idx == questions[i]["answer"]: correct += 1
            else: wrong += 1
    unattempted = max(0, len(questions)-correct-wrong)
    score = correct - wrong*q["negative"]
    total = len(questions)
    percentage = round(max(0, score)/total*100, 2) if total else 0
    c = conn()
    c.execute("""INSERT INTO attempts(
        quiz_id,name,mobile,email,gender,category,score,correct,wrong,
        unattempted,percentage,time_taken,answers,created_at
    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
    (qid, data.get("name",""), data.get("mobile",""), data.get("email",""),
     data.get("gender",""), data.get("category",""), score, correct, wrong,
     unattempted, percentage, int(data.get("timeTaken",0)),
     json.dumps(answers), datetime.utcnow().isoformat()))
    c.commit(); c.close()
    return {
        "score": round(score, 2), "correct": correct, "wrong": wrong,
        "unattempted": unattempted, "percentage": percentage,
        "explanations": [x["explanation"] for x in questions]
    }

def leaderboard(qid):
    c = conn()
    rows = c.execute("""SELECT name,category,score,percentage,time_taken
                        FROM attempts WHERE quiz_id=?
                        ORDER BY score DESC, time_taken ASC""", (qid,)).fetchall()
    c.close()
    out=[]
    for n,r in enumerate(rows,1):
        out.append({"rank":n,"name":r[0],"category":r[1],"score":r[2],
                    "percentage":r[3],"time_taken":r[4]})
    return out

def quiz_stats(qid):
    c=conn()
    n=c.execute("SELECT COUNT(*) FROM attempts WHERE quiz_id=?", (qid,)).fetchone()[0]
    c.close()
    return {"attempts":n}
