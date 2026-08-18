import os
import uuid
import re
from datetime import datetime, timezone

from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError

MONGODB_URI = os.getenv("MONGODB_URI", "").strip()
MONGODB_DB = os.getenv("MONGODB_DB", "quick_study_group").strip()

_client = None
_db = None


def _get_db():
    global _client, _db

    if not MONGODB_URI:
        raise RuntimeError("MONGODB_URI is not configured")

    if _db is None:
        _client = MongoClient(
            MONGODB_URI,
            serverSelectionTimeoutMS=10000,
            connectTimeoutMS=10000,
            socketTimeoutMS=20000,
            maxPoolSize=100,
            minPoolSize=5,
            retryWrites=True,
        )
        _db = _client[MONGODB_DB]
        _client.admin.command("ping")

    return _db


def _normalize_mobile(value):
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[-10:]
    return digits


def init_db():
    db = _get_db()

    # These indexes make duplicate submissions safe even when many users
    # submit at nearly the same time. Partial indexes ignore blank values.
    db.quizzes.create_index(
        [("id", ASCENDING)],
        unique=True,
        name="quiz_id_unique",
    )
    db.attempts.create_index(
        [("quiz_id", ASCENDING), ("mobile", ASCENDING)],
        unique=True,
        partialFilterExpression={"mobile": {"$type": "string", "$gt": ""}},
        name="quiz_mobile_unique",
    )
    db.attempts.create_index(
        [("quiz_id", ASCENDING), ("email", ASCENDING)],
        unique=True,
        partialFilterExpression={"email": {"$type": "string", "$gt": ""}},
        name="quiz_email_unique",
    )
    db.attempts.create_index(
        [("quiz_id", ASCENDING), ("score", DESCENDING), ("time_taken", ASCENDING), ("_id", ASCENDING)],
        name="leaderboard_index",
    )


def create_quiz(title, heading, minutes, negative, mode, questions):
    qid = "QSG-" + uuid.uuid4().hex[:6].upper()

    _get_db().quizzes.insert_one({
        "id": qid,
        "title": title,
        "heading": heading,
        "minutes": int(minutes),
        "negative": float(negative),
        "mode": mode,
        "questions": questions,
        "created_at": datetime.now(timezone.utc),
    })
    return qid


def get_quiz(qid):
    row = _get_db().quizzes.find_one({"id": qid}, {"_id": 0})
    if not row:
        return None

    return {
        "id": row["id"],
        "title": row.get("title", ""),
        "heading": row.get("heading", ""),
        "minutes": row.get("minutes", 0),
        "negative": row.get("negative", 0),
        "mode": row.get("mode", ""),
        "questions": row.get("questions", []),
    }


def update_quiz_setting(qid, key, value):
    if key not in ("minutes", "negative"):
        return

    if key == "minutes":
        value = int(value)
    else:
        value = float(value)

    _get_db().quizzes.update_one(
        {"id": qid},
        {"$set": {key: value}},
    )


def _find_first_duplicate(db, qid, mobile, email):
    clauses = []
    if mobile:
        clauses.append({"quiz_id": qid, "mobile": mobile})
    if email:
        clauses.append({"quiz_id": qid, "email": email})

    if not clauses:
        return None

    return db.attempts.find_one(
        {"$or": clauses},
        sort=[("created_at", ASCENDING), ("_id", ASCENDING)],
    )


def _duplicate_response(row):
    return {
        "ok": True,
        "duplicate": True,
        "message": "This mobile number or email has already submitted this test. The first attempt remains on the leaderboard.",
        "score": round(float(row.get("score", 0) or 0), 2),
        "correct": int(row.get("correct", 0) or 0),
        "wrong": int(row.get("wrong", 0) or 0),
        "unattempted": int(row.get("unattempted", 0) or 0),
        "percentage": float(row.get("percentage", 0) or 0),
        "first_attempt": True,
    }


def save_attempt(qid, data):
    q = get_quiz(qid)
    if not q:
        return None

    db = _get_db()
    mobile = _normalize_mobile(data.get("mobile", ""))
    email = str(data.get("email", "") or "").strip().lower()

    # Fast path: if it already exists, always keep the first attempt.
    existing = _find_first_duplicate(db, qid, mobile, email)
    if existing:
        return _duplicate_response(existing)

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

    unattempted = max(0, len(questions) - correct - wrong)
    score = correct - wrong * q["negative"]
    total = len(questions)
    percentage = round(max(0, score) / total * 100, 2) if total else 0

    document = {
        "quiz_id": qid,
        "name": str(data.get("name", "") or ""),
        "mobile": mobile,
        "email": email,
        "gender": str(data.get("gender", "") or ""),
        "category": str(data.get("category", "") or ""),
        "score": float(score),
        "correct": int(correct),
        "wrong": int(wrong),
        "unattempted": int(unattempted),
        "percentage": float(percentage),
        "time_taken": int(data.get("timeTaken", 0) or 0),
        "answers": answers,
        "created_at": datetime.now(timezone.utc),
    }

    try:
        db.attempts.insert_one(document)
    except DuplicateKeyError:
        # Handles the race where two requests with the same mobile/email
        # arrive at exactly the same time. The successful first insert wins.
        existing = _find_first_duplicate(db, qid, mobile, email)
        if existing:
            return _duplicate_response(existing)
        raise

    return {
        "ok": True,
        "duplicate": False,
        "score": round(score, 2),
        "correct": correct,
        "wrong": wrong,
        "unattempted": unattempted,
        "percentage": percentage,
        "explanations": [x.get("explanation", "") for x in questions],
    }


def leaderboard(qid):
    rows = _get_db().attempts.find(
        {"quiz_id": qid},
        {
            "_id": 1,
            "name": 1,
            "category": 1,
            "correct": 1,
            "wrong": 1,
            "score": 1,
            "percentage": 1,
            "time_taken": 1,
        },
    ).sort([
        ("score", DESCENDING),
        ("time_taken", ASCENDING),
        ("_id", ASCENDING),
    ])

    out = []
    for n, r in enumerate(rows, 1):
        out.append({
            "rank": n,
            "name": r.get("name", ""),
            "category": r.get("category", ""),
            "correct": int(r.get("correct", 0) or 0),
            "wrong": int(r.get("wrong", 0) or 0),
            "score": float(r.get("score", 0) or 0),
            "percentage": float(r.get("percentage", 0) or 0),
            "time_taken": int(r.get("time_taken", 0) or 0),
        })
    return out


def quiz_stats(qid):
    n = _get_db().attempts.count_documents({"quiz_id": qid})
    return {"attempts": n}
