import os
import asyncio
import logging
import tempfile
from threading import Thread

from flask import Flask, request, jsonify, render_template
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, filters
)

from db import init_db, create_quiz, get_quiz, save_attempt, leaderboard, quiz_stats
from parser import parse_questions

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")
PORT = int(os.getenv("PORT", "10000"))

app = Flask(__name__, template_folder="templates", static_folder="static")
init_db()
pending = {}

@app.after_request
def add_cors_headers(response):
    # Needed when a downloaded HTML file is opened locally and submits to Render.
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    return response

@app.get("/")
def home():
    return "Quick Study Group Test Bot is running."

@app.get("/health")
def health():
    return jsonify({"ok": True})

@app.get("/test/<quiz_id>")
def test_page(quiz_id):
    quiz = get_quiz(quiz_id)
    if not quiz:
        return "Test not found", 404
    return render_template("test.html", quiz=quiz, public_url=PUBLIC_URL)

@app.post("/api/attempt/<quiz_id>")
def submit_attempt(quiz_id):
    quiz = get_quiz(quiz_id)
    if not quiz:
        return jsonify({"error": "Test not found"}), 404
    if request.method == "OPTIONS":
        return ("", 204)
    data = request.get_json(force=True)
    result = save_attempt(quiz_id, data)
    return jsonify(result)

@app.route("/api/attempt/<quiz_id>", methods=["OPTIONS"])
def submit_attempt_options(quiz_id):
    return ("", 204)

@app.get("/api/leaderboard/<quiz_id>")
def leaderboard_api(quiz_id):
    return jsonify({"rows": leaderboard(quiz_id), "stats": quiz_stats(quiz_id)})

def start_web():
    app.run(host="0.0.0.0", port=PORT, use_reloader=False)

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Quick Study Group Test Bot\n\n"
        "📄 TXT file भेजें। Format:\n\n"
        "Question...\n"
        "A) option\n"
        "B) option ✅\n"
        "C) option\n"
        "D) option\n"
        "Ex: explanation...\n\n"
        "Bot Title, Heading, Time, Negative और Mode लेकर test बनाएगा।\n"
        "फिर /html TEST_ID देने पर actual .html file Telegram में भेजेगा।"
    )

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.document:
        return
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("⛔ केवल Owner TXT file upload कर सकता है।")
        return
    doc = update.message.document
    if not doc.file_name.lower().endswith(".txt"):
        await update.message.reply_text("❌ केवल .txt file भेजें।")
        return

    f = await doc.get_file()
    path = f"/tmp/{doc.file_unique_id}.txt"
    await f.download_to_drive(path)
    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
        text = fh.read()
    questions = parse_questions(text)

    if not questions:
        await update.message.reply_text("❌ Questions नहीं मिले। TXT format check करें।")
        return

    pending[update.effective_user.id] = {"questions": questions}
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

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid != OWNER_ID or uid not in pending:
        return
    text = update.message.text
    vals = {}
    for line in text.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            vals[k.strip().lower()] = v.strip()

    required = ["title", "heading", "time", "negative", "mode"]
    if not all(k in vals for k in required):
        await update.message.reply_text("❌ सभी fields दें:\nTitle, Heading, Time, Negative, Mode")
        return

    try:
        minutes = int(float(vals["time"]))
        negative = float(vals["negative"])
        if minutes <= 0 or negative < 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Time/Negative सही number में दें।")
        return

    data = pending.pop(uid)
    quiz_id = create_quiz(
        title=vals["title"], heading=vals["heading"], minutes=minutes,
        negative=negative, mode=vals["mode"], questions=data["questions"]
    )
    link = f"{PUBLIC_URL}/test/{quiz_id}" if PUBLIC_URL else f"/test/{quiz_id}"
    await update.message.reply_text(
        "✅ HTML Generated\n\n"
        f"🆔 Test ID: {quiz_id}\n"
        f"📚 Questions: {len(data['questions'])}\n"
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

async def settime_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    if len(context.args) != 2:
        await update.message.reply_text("Usage: /settime TEST_ID 20")
        return
    from db import update_quiz_setting
    try:
        minutes = int(float(context.args[1]))
        if minutes <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Time positive number में दें।")
        return
    update_quiz_setting(context.args[0], "minutes", minutes)
    await update.message.reply_text("✅ Timer updated.")

async def setnegative_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    if len(context.args) != 2:
        await update.message.reply_text("Usage: /setnegative TEST_ID 0.25")
        return
    from db import update_quiz_setting
    try:
        negative = float(context.args[1])
        if negative < 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Negative marking 0 या positive number में दें।")
        return
    update_quiz_setting(context.args[0], "negative", negative)
    await update.message.reply_text("✅ Negative marking updated.")

async def leaderboard_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /leaderboard TEST_ID")
        return
    qid = context.args[0]
    q = get_quiz(qid)
    if not q:
        await update.message.reply_text("❌ Test नहीं मिला।")
        return
    rows = leaderboard(qid)
    stats = quiz_stats(qid)
    if not rows:
        await update.message.reply_text("अभी कोई attempt नहीं हुआ।")
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
        lines.append(f"{r['rank']} | {r['name']} | {r['score']} | {r['percentage']}%")
    await update.message.reply_text("\n".join(lines))

async def html_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate and send a real standalone .html document in Telegram."""
    if update.effective_user.id != OWNER_ID:
        return
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /html TEST_ID")
        return

    q = get_quiz(context.args[0])
    if not q:
        await update.message.reply_text("❌ Test नहीं मिला।")
        return
    if not PUBLIC_URL:
        await update.message.reply_text("❌ Render में PUBLIC_URL environment variable set करें, फिर /html दोबारा दें।")
        return

    try:
        with app.app_context():
            html = render_template("test.html", quiz=q, public_url=PUBLIC_URL)

        filename = "Quick_Study_Group_Final_Assessment_Portal.html"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False, encoding="utf-8") as fh:
            fh.write(html)
            file_path = fh.name

        caption = (
            "✅ HTML File Generated\n\n"
            f"🆔 Test ID: {q['id']}\n"
            f"📚 Questions: {len(q['questions'])}\n"
            f"⏱️ Time: {q['minutes']} minutes\n"
            f"❌ Negative: {q['negative']}\n"
            f"🎯 Mode: {q['mode']}\n\n"
            "📥 नीचे actual HTML file है। Download करके Chrome में खोल सकते हैं।"
        )
        try:
            with open(file_path, "rb") as fh:
                await update.message.reply_document(
                    document=fh,
                    filename=filename,
                    caption=caption
                )
        finally:
            try:
                os.remove(file_path)
            except OSError:
                pass
    except Exception:
        log.exception("HTML generation failed")
        await update.message.reply_text("❌ HTML file generate नहीं हो पाई। Render logs check करें।")

def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable missing")

    Thread(target=start_web, daemon=True).start()

    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start_cmd))
    application.add_handler(CommandHandler("settime", settime_cmd))
    application.add_handler(CommandHandler("setnegative", setnegative_cmd))
    application.add_handler(CommandHandler("leaderboard", leaderboard_cmd))
    application.add_handler(CommandHandler("html", html_cmd))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    log.info("Bot starting...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
