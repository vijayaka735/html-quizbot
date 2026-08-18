import os
import asyncio
import logging
import tempfile
import json
from threading import Thread

from flask import Flask, request, jsonify, render_template
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from db import (
    init_db,
    create_quiz,
    get_quiz,
    save_attempt,
    leaderboard,
    quiz_stats,
)
from parser import parse_questions


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

log = logging.getLogger(__name__)


# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "")

try:
    OWNER_ID = int(os.getenv("OWNER_ID", "0"))
except ValueError:
    OWNER_ID = 0

# Render automatically provides RENDER_EXTERNAL_URL.
# PUBLIC_URL can still be manually set if desired.
PUBLIC_URL = (
    os.getenv("PUBLIC_URL")
    or os.getenv("RENDER_EXTERNAL_URL")
    or ""
).strip().rstrip("/")

try:
    PORT = int(os.getenv("PORT", "10000"))
except ValueError:
    PORT = 10000


# =========================================================
# FLASK
# =========================================================

app = Flask(
    __name__,
    template_folder="templates",
    static_folder="static",
)

init_db()

pending = {}


# =========================================================
# HELPERS
# =========================================================

def get_public_url():
    """
    Returns the public URL of the Render service.

    Priority:
    1. PUBLIC_URL
    2. RENDER_EXTERNAL_URL
    3. Request host, when available
    """
    url = (
        os.getenv("PUBLIC_URL")
        or os.getenv("RENDER_EXTERNAL_URL")
        or ""
    ).strip().rstrip("/")

    if url:
        return url

    try:
        if request:
            return request.url_root.rstrip("/")
    except Exception:
        pass

    return ""


def get_test_url(quiz_id):
    base = get_public_url()

    if not base:
        return f"/test/{quiz_id}"

    return f"{base}/test/{quiz_id}"


# =========================================================
# CORS
# =========================================================

@app.after_request
def add_cors_headers(response):
    """
    Allows downloaded HTML files opened from Chrome/file://
    to communicate with the Render API.
    """
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = (
        "Content-Type, Authorization"
    )
    response.headers["Access-Control-Allow-Methods"] = (
        "GET, POST, OPTIONS"
    )
    response.headers["Access-Control-Max-Age"] = "86400"

    return response


# =========================================================
# BASIC ROUTES
# =========================================================

@app.get("/")
def home():
    return "Quick Study Group Test Bot is running."


@app.get("/health")
def health():
    return jsonify({
        "ok": True,
        "service": "Quick Study Group Test Bot",
    })


# =========================================================
# TEST PAGE
# =========================================================

@app.get("/test/<quiz_id>")
def test_page(quiz_id):
    quiz = get_quiz(quiz_id)

    if not quiz:
        return "Test not found", 404

    public_url = get_public_url()

    if not public_url:
        public_url = request.url_root.rstrip("/")

    return render_template(
        "test.html",
        quiz=quiz,
        public_url=public_url,
    )


# =========================================================
# SUBMIT API
# =========================================================

@app.route(
    "/api/attempt/<quiz_id>",
    methods=["POST", "OPTIONS"],
)
def submit_attempt(quiz_id):

    # Handle browser preflight request.
    if request.method == "OPTIONS":
        return ("", 204)

    quiz = get_quiz(quiz_id)

    if not quiz:
        return jsonify({
            "ok": False,
            "error": "Test not found",
        }), 404

    try:
        # Normal JSON request.
        if request.is_json:
            data = request.get_json(silent=True)

        # sendBeacon / text/plain fallback.
        else:
            raw = request.get_data(
                as_text=True
            )

            if not raw:
                data = {}

            else:
                try:
                    data = json.loads(raw)
                except Exception:
                    return jsonify({
                        "ok": False,
                        "error": "Invalid JSON payload",
                    }), 400

        if not isinstance(data, dict):
            return jsonify({
                "ok": False,
                "error": "Invalid payload",
            }), 400

        # Basic validation.
        if "answers" not in data:
            return jsonify({
                "ok": False,
                "error": "Answers are missing",
            }), 400

        result = save_attempt(
            quiz_id,
            data,
        )

        if result is None:
            return jsonify({
                "ok": False,
                "error": "Could not save attempt",
            }), 500

        # Make sure the response is JSON.
        if isinstance(result, dict):
            result.setdefault("ok", True)

        return jsonify(result)

    except Exception as e:
        log.exception(
            "Attempt submission failed for quiz %s",
            quiz_id,
        )

        return jsonify({
            "ok": False,
            "error": str(e),
        }), 500


# =========================================================
# LEADERBOARD API
# =========================================================

@app.get("/api/leaderboard/<quiz_id>")
def leaderboard_api(quiz_id):
    quiz = get_quiz(quiz_id)

    if not quiz:
        return jsonify({
            "error": "Test not found"
        }), 404

    return jsonify({
        "rows": leaderboard(quiz_id),
        "stats": quiz_stats(quiz_id),
    })


# =========================================================
# WEB SERVER
# =========================================================

def start_web():
    log.info(
        "Starting Flask server on port %s",
        PORT,
    )

    if PUBLIC_URL:
        log.info(
            "Public URL: %s",
            PUBLIC_URL,
        )
    else:
        log.warning(
            "PUBLIC_URL / RENDER_EXTERNAL_URL not found."
        )

    app.run(
        host="0.0.0.0",
        port=PORT,
        use_reloader=False,
    )


# =========================================================
# TELEGRAM /START
# =========================================================

async def start_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    await update.message.reply_text(
        "👋 Quick Study Group Test Bot\n\n"
        "📄 TXT file भेजें। Format:\n\n"
        "Question...\n"
        "A) option\n"
        "B) option ✅\n"
        "C) option\n"
        "D) option\n"
        "Ex: explanation...\n\n"
        "Bot Title, Heading, Time, Negative और Mode लेकर "
        "test बनाएगा।\n"
        "फिर /html TEST_ID देने पर actual .html file "
        "Telegram में भेजेगा।"
    )


# =========================================================
# TXT FILE HANDLER
# =========================================================

async def handle_document(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not update.message.document:
        return

    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text(
            "⛔ केवल Owner TXT file upload कर सकता है।"
        )
        return

    doc = update.message.document

    if not doc.file_name.lower().endswith(".txt"):
        await update.message.reply_text(
            "❌ केवल .txt file भेजें।"
        )
        return

    try:
        f = await doc.get_file()

        path = (
            f"/tmp/"
            f"{doc.file_unique_id}.txt"
        )

        await f.download_to_drive(path)

        with open(
            path,
            "r",
            encoding="utf-8",
            errors="ignore",
        ) as fh:
            text = fh.read()

        questions = parse_questions(text)

        try:
            os.remove(path)
        except OSError:
            pass

        if not questions:
            await update.message.reply_text(
                "❌ Questions नहीं मिले। "
                "TXT format check करें।"
            )
            return

        pending[update.effective_user.id] = {
            "questions": questions
        }

        await update.message.reply_text(
            f"✅ {len(questions)} questions मिले।\n\n"
            "अब यह format में details भेजें:\n\n"
            "Title: Bihar Police Practice Set\n"
            "Heading: Science | ध्वनि\n"
            "Time: 20\n"
            "Negative: 0.25\n"
            "Mode: Exam\n\n"
            "Time minutes में दें।"
        )

    except Exception:
        log.exception(
            "TXT processing failed"
        )

        await update.message.reply_text(
            "❌ TXT file process नहीं हो पाई।"
        )


# =========================================================
# TEXT HANDLER
# =========================================================

async def handle_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    uid = update.effective_user.id

    if uid != OWNER_ID:
        return

    if uid not in pending:
        return

    text = update.message.text

    vals = {}

    for line in text.splitlines():

        if ":" in line:
            k, v = line.split(":", 1)

            vals[
                k.strip().lower()
            ] = v.strip()

    required = [
        "title",
        "heading",
        "time",
        "negative",
        "mode",
    ]

    if not all(
        k in vals
        for k in required
    ):
        await update.message.reply_text(
            "❌ सभी fields दें:\n"
            "Title, Heading, Time, Negative, Mode"
        )
        return

    try:
        minutes = int(
            float(vals["time"])
        )

        negative = float(
            vals["negative"]
        )

        if minutes <= 0:
            raise ValueError

        if negative < 0:
            raise ValueError

    except ValueError:
        await update.message.reply_text(
            "❌ Time/Negative सही number में दें।"
        )
        return

    try:

        data = pending.pop(uid)

        quiz_id = create_quiz(
            title=vals["title"],
            heading=vals["heading"],
            minutes=minutes,
            negative=negative,
            mode=vals["mode"],
            questions=data["questions"],
        )

        link = get_test_url(
            quiz_id
        )

        await update.message.reply_text(
            "✅ HTML Generated\n\n"
            f"🆔 Test ID: {quiz_id}\n"
            f"📚 Questions: "
            f"{len(data['questions'])}\n"
            f"⏱️ Time: {minutes} minutes\n"
            f"❌ Negative: {negative}\n"
            f"🎯 Mode: {vals['mode']}\n\n"
            f"🔗 Test:\n{link}\n\n"
            "Owner commands:\n"
            f"/settime {quiz_id} 30\n"
            f"/setnegative {quiz_id} 0.25\n"
            f"/leaderboard {quiz_id}\n"
            f"/html {quiz_id}"
        )

    except Exception:
        log.exception(
            "Quiz creation failed"
        )

        await update.message.reply_text(
            "❌ Quiz create नहीं हो पाया। "
            "Render logs check करें।"
        )


# =========================================================
# SET TIME
# =========================================================

async def settime_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if update.effective_user.id != OWNER_ID:
        return

    if len(context.args) != 2:
        await update.message.reply_text(
            "Usage: /settime TEST_ID 20"
        )
        return

    from db import update_quiz_setting

    try:

        minutes = int(
            float(context.args[1])
        )

        if minutes <= 0:
            raise ValueError

    except ValueError:
        await update.message.reply_text(
            "❌ Timer positive number में दें।"
        )
        return

    update_quiz_setting(
        context.args[0],
        "minutes",
        minutes,
    )

    await update.message.reply_text(
        "✅ Timer updated."
    )


# =========================================================
# SET NEGATIVE
# =========================================================

async def setnegative_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if update.effective_user.id != OWNER_ID:
        return

    if len(context.args) != 2:
        await update.message.reply_text(
            "Usage: /setnegative TEST_ID 0.25"
        )
        return

    from db import update_quiz_setting

    try:

        negative = float(
            context.args[1]
        )

        if negative < 0:
            raise ValueError

    except ValueError:
        await update.message.reply_text(
            "❌ Negative marking 0 या "
            "positive number में दें।"
        )
        return

    update_quiz_setting(
        context.args[0],
        "negative",
        negative,
    )

    await update.message.reply_text(
        "✅ Negative marking updated."
    )


# =========================================================
# LEADERBOARD
# =========================================================

async def leaderboard_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if update.effective_user.id != OWNER_ID:
        return

    if len(context.args) != 1:
        await update.message.reply_text(
            "Usage: /leaderboard TEST_ID"
        )
        return

    qid = context.args[0]

    q = get_quiz(qid)

    if not q:
        await update.message.reply_text(
            "❌ Test नहीं मिला।"
        )
        return

    rows = leaderboard(qid)
    stats = quiz_stats(qid)

    if not rows:
        await update.message.reply_text(
            "अभी कोई attempt नहीं हुआ।"
        )
        return

    lines = [
        "🏆 LEADERBOARD",
        f"Test: {q['title']}",
        f"Total Attempts: {stats['attempts']}",
        "",
        "Rank | Name | Score | %",
        "--------------------------",
    ]

    for r in rows[:50]:

        lines.append(
            f"{r['rank']} | "
            f"{r['name']} | "
            f"{r['score']} | "
            f"{r['percentage']}%"
        )

    await update.message.reply_text(
        "\n".join(lines)
    )


# =========================================================
# GENERATE HTML
# =========================================================

async def html_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if update.effective_user.id != OWNER_ID:
        return

    if len(context.args) != 1:
        await update.message.reply_text(
            "Usage: /html TEST_ID"
        )
        return

    q = get_quiz(
        context.args[0]
    )

    if not q:
        await update.message.reply_text(
            "❌ Test नहीं मिला।"
        )
        return

    public_url = get_public_url()

    if not public_url:
        await update.message.reply_text(
            "❌ Render public URL नहीं मिला।\n\n"
            "Render Environment में PUBLIC_URL "
            "set करें या RENDER_EXTERNAL_URL उपलब्ध "
            "होना चाहिए।"
        )
        return

    try:

        with app.app_context():

            html = render_template(
                "test.html",
                quiz=q,
                public_url=public_url,
            )

        filename = (
            "Quick_Study_Group_Final_Assessment_Portal.html"
        )

        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".html",
            delete=False,
            encoding="utf-8",
        ) as fh:

            fh.write(html)
            file_path = fh.name

        caption = (
            "✅ HTML File Generated\n\n"
            f"🆔 Test ID: {q['id']}\n"
            f"📚 Questions: {len(q['questions'])}\n"
            f"⏱️ Time: {q['minutes']} minutes\n"
            f"❌ Negative: {q['negative']}\n"
            f"🎯 Mode: {q['mode']}\n\n"
            "📥 नीचे actual HTML file है। "
            "Download करके Chrome में खोल सकते हैं।"
        )

        try:

            with open(
                file_path,
                "rb",
            ) as fh:

                await update.message.reply_document(
                    document=fh,
                    filename=filename,
                    caption=caption,
                )

        finally:

            try:
                os.remove(file_path)
            except OSError:
                pass

    except Exception:

        log.exception(
            "HTML generation failed"
        )

        await update.message.reply_text(
            "❌ HTML file generate नहीं हो पाई। "
            "Render logs check करें।"
        )


# =========================================================
# MAIN
# =========================================================

def main():

    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN environment variable missing"
        )

    log.info(
        "PUBLIC_URL = %s",
        PUBLIC_URL or "(automatic/request based)",
    )

    Thread(
        target=start_web,
        daemon=True,
    ).start()

    application = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler(
            "start",
            start_cmd,
        )
    )

    application.add_handler(
        CommandHandler(
            "settime",
            settime_cmd,
        )
    )

    application.add_handler(
        CommandHandler(
            "setnegative",
            setnegative_cmd,
        )
    )

    application.add_handler(
        CommandHandler(
            "leaderboard",
            leaderboard_cmd,
        )
    )

    application.add_handler(
        CommandHandler(
            "html",
            html_cmd,
        )
    )

    application.add_handler(
        MessageHandler(
            filters.Document.ALL,
            handle_document,
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_text,
        )
    )

    log.info(
        "Bot starting..."
    )

    application.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
