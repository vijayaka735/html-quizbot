# Quick Study Group — TXT → HTML Quiz Bot

यह version आपके बताए हुए flow के लिए है:

- TXT file upload → MCQ parser
- Title / Heading / Time / Negative / Mode
- Unique Test ID
- Registration: Name, Mobile, Email, Gender, Category
- Declaration checkbox
- Mobile-friendly exam interface
- ⏱️ Countdown timer
- 🧭 Question Navigator
- 🟢 Answered / 🟡 Marked for Review / 🔵 Unanswered
- ⬅️ Previous
- 🔖 Mark for Review
- 🧹 Clear Response
- 💾 Save & Next
- 🎯 Submit Test
- Automatic submit when timer ends
- Negative marking
- Result Summary
- 📋 All / ✅ Correct / ❌ Incorrect / ⚪ Not Answered filters
- 📝 Your Answer
- ✅ Correct Answer
- 💡 Explanation for every question
- Owner-only `/settime`
- Owner-only `/setnegative`
- Owner-only `/leaderboard`
- **Owner-only `/html TEST_ID` अब actual `.html` document Telegram में भेजता है**

## `/html` behaviour

उदाहरण:

```text
/html QSG-1CE76A
```

Bot एक real Telegram document भेजेगा:

```text
📄 Quick_Study_Group_Final_Assessment_Portal.html
```

File standalone है: CSS/JS उसी HTML में embedded हैं। Download करके Chrome में खोल सकते हैं। Result save करने के लिए HTML Render के `PUBLIC_URL` पर API call करता है। इसलिए Render में `PUBLIC_URL` सही होना जरूरी है।

## TXT format

```text
प्रश्न यहाँ...
A) option
B) option
C) option ✅
D) option
Ex: यहाँ explanation...

दूसरा प्रश्न...
A) option
B) option ✅
C) option
D) option
Ex: दूसरा explanation...
```

Correct option के अंत में `✅` लगाएँ। Questions के बीच blank line रखें।

## Bot commands

```text
/start
/settime QSG-ABC123 20
/setnegative QSG-ABC123 0.25
/leaderboard QSG-ABC123
/html QSG-ABC123
```

`/settime` और `/setnegative` के बाद नया HTML बनाने के लिए `/html TEST_ID` फिर से दें।

## Render

Build command:

```text
pip install -r requirements.txt
```

Start command:

```text
gunicorn --bind 0.0.0.0:$PORT bot:app
```

Environment variables:

```text
BOT_TOKEN=BotFather token
OWNER_ID=आपका Telegram numeric ID
PUBLIC_URL=https://your-service.onrender.com
DB_PATH=data.db
```

`PUBLIC_URL` के बिना `/html` actual file generate नहीं करेगा, क्योंकि downloaded HTML को result submit करने के लिए API address चाहिए।

## Important

SQLite Render के ephemeral filesystem पर production में permanent leaderboard के लिए suitable नहीं है। Persistent leaderboard के लिए PostgreSQL जैसी persistent database लगाएँ।

Bot token और owner ID code में hard-code न करें। Environment variables इस्तेमाल करें।
