#!/usr/bin/env python3
import base64
import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request
import urllib.error

from dotenv import load_dotenv
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, "bot.env"))

TOKEN = os.environ.get("BOT_TOKEN", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash").strip()

TZ = timezone(timedelta(hours=8))  # Иркутск, UTC+8
STATE_FILE = os.path.join(BASE_DIR, "state.json")
WEBAPP_URL = os.environ.get("WEBAPP_URL", "").strip()
API_PORT = int(os.environ.get("API_PORT", "8080") or 0)

ADMINS = {
    int(x) for x in re.split(r"[,\s]+", os.environ.get("ADMINS", ""))
    if x.lstrip("-").isdigit()
}
HERE = BASE_DIR

# Понедельник верхней недели
DEFAULT_UPPER_MONDAY = "2026-11-09"

PAIRS = {
    1: ("8:15", "9:45"),
    2: ("9:55", "11:25"),
    3: ("12:05", "13:35"),
    4: ("13:45", "15:15"),
    5: ("15:25", "16:55"),
    6: ("17:05", "18:35"),
}

SUBJECTS = {
    "oht": ("🦆", "Охрана труда и бережливое производство", "Плюснина О.М."),
    "pdis": ("🦆", "Проектирование и дизайн информационных систем", "Сафонова Т.В."),
    "chm": ("🦆", "Численные методы", "Клеймёнов В.Ф."),
    "rkis": ("🦆", "Разработка кода информационных систем", "Сафонова Т.В."),
    "web": ("🦆", "Проектирование и разработка веб-приложений", "Сенотрусова Т.А."),
    "hist": ("🦆", "История", "Михалёва Г.С."),
    "razg": ("🦆", "Внеурочное мероприятие «Разговоры о важном»", "Сенотрусова Т.А."),
    "ya": ("🦆", "Иностранный язык в профессиональной деятельности", ""),
    "arh": ("🦆", "Архитектура аппаратных средств", "Моисеева А.Д."),
    "ks": ("🦆", "Компьютерные сети", "Шкилёва В.Е."),
    "fiz": ("🦆", "Физическая культура", ""),
}

MARKS = {
    "oht": "🟡", "pdis": "🟣", "chm": "🔵", "rkis": "🟢",
    "web": "🟠", "hist": "🟤", "razg": "⚪", "ya": "🔴",
    "arh": "🔷", "ks": "🟦", "fiz": "🟩",
}

ROD = (1, "Родионова И.П.", "21-35")
BUH = (2, "Бухарова Н.А.", "21-17")

# (пара, неделя: u верхняя / l нижняя / b каждая, предмет, аудитория или список подгрупп)
DAYS = {
    0: [
        (1, "l", "oht", "21-36"), (2, "l", "pdis", "21-39"),
        (3, "l", "chm", "21-31"), (4, "l", "rkis", "22-213"),
    ],
    1: [
        (1, "l", "ya", [BUH]), (2, "b", "web", "21-33"),
        (3, "u", "pdis", "21-33"), (3, "l", "hist", "21-41"),
        (4, "u", "razg", "21-33"),
    ],
    2: [
        (3, "l", "chm", "21-34"), (4, "l", "rkis", "22-214"),
        (5, "u", "pdis", "22-214"), (5, "l", "arh", "21-39"),
        (6, "u", "arh", "21-39"), (6, "l", "pdis", "21-39"),
    ],
    3: [
        (1, "u", "rkis", "21-39"), (2, "u", "rkis", "21-39"),
        (3, "u", "web", "21-33"), (4, "b", "ks", "21-33"),
        (5, "l", "web", "21-33"),
    ],
    4: [
        (2, "u", "hist", "21-41"), (3, "u", "oht", "21-36"),
        (3, "l", "ya", [ROD, BUH]), (4, "u", "chm", "21-47"),
        (4, "l", "rkis", "21-39"), (5, "u", "arh", "21-39"),
        (5, "l", "fiz", "–"),
    ],
    5: [
        (2, "l", "ya", [ROD]), (3, "l", "ks", "21-46"),
        (4, "l", "web", "21-33"), (5, "l", "fiz", "–"),
    ],
}

DAY_NAMES = [
    "Понедельник", "Вторник", "Среда", "Четверг",
    "Пятница", "Суббота", "Воскресенье"
]

API = "https://api.telegram.org/bot%s/%s"

_rows = [
    ["Сегодня", "Завтра", "Замены"],
    ["Эта неделя", "Следующая неделя"],
    ["Верхняя неделя", "Нижняя неделя"],
    ["Подгруппа 1", "Подгруппа 2", "Обе подгруппы"],
]

if WEBAPP_URL:
    _rows.insert(0, [{
        "text": "🦆 Открыть расписание",
        "web_app": {"url": WEBAPP_URL + "?v=2"}
    }])

KEYBOARD = {"keyboard": _rows, "resize_keyboard": True}

HELP = (
    "🦆 <b>Расписание мИСПР-24-2</b>\n\n"
    "Кнопки внизу показывают пары на сегодня, завтра и на любую неделю.\n\n"
    "/today — сегодня\n"
    "/tomorrow — завтра\n"
    "/week — эта неделя\n"
    "/next — следующая неделя\n"
    "/upper и /lower — верхняя и нижняя недели\n"
    "/sub 1, /sub 2 или /sub 0 — подгруппа\n"
    "/setweek верхняя или /setweek нижняя — настройка недели\n"
    "/repl — замены\n"
    "/myid — узнать свой ID\n\n"
    "Замены: отправьте фото листа с заменами."
)

REPL_PROMPT = """На фото лист замен в расписании колледжа. Сегодня {today} (Иркутск).
Найди строки, которые относятся к группе мИСПР-24-2
(может быть написано МИСПР-24-2, мИСПР 24-2, ИСПР-24-2 и т.п.).
Другие группы игнорируй.

Верни ТОЛЬКО JSON без пояснений и без markdown:
{"date": "YYYY-MM-DD или null", "group_found": true или false,
 "rows": [{"pair": номер пары 1-6 или null, "was": "что стояло по расписанию",
 "now": "что будет вместо этого", "teacher": "преподаватель",
 "room": "аудитория", "note": "подгруппа или другая пометка"}]}

Правила:
- date: дата, на которую действуют замены.
- Если года нет, возьми ближайший к сегодняшней дате.
- Если пара отменена, поставь now = "" и note = "отмена".
- Переписывай текст как на фото, ничего не выдумывай.
- Нечитаемые или отсутствующие данные оставляй пустыми.
- Если замен для группы нет, верни group_found = false и пустой rows.
"""


# ---------- Telegram ----------

def call(method, **params):
    data = urllib.parse.urlencode({
        k: json.dumps(v) if isinstance(v, (dict, list)) else v
        for k, v in params.items()
    }).encode()

    req = urllib.request.Request(API % (TOKEN, method), data=data)

    with urllib.request.urlopen(req, timeout=70) as response:
        result = json.load(response)

    if not result.get("ok"):
        raise RuntimeError(str(result))

    return result


def send(chat_id, text, keyboard=True):
    params = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }

    if keyboard:
        params["reply_markup"] = KEYBOARD

    call("sendMessage", **params)


# ---------- Состояние и недели ----------

def monday_of(d):
    return d - timedelta(days=d.weekday())


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(st):
    tmp = STATE_FILE + ".tmp"

    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False)

    os.replace(tmp, STATE_FILE)


def upper_anchor(st):
    return date.fromisoformat(
        st.get("upper_monday", DEFAULT_UPPER_MONDAY)
    )


def week_of(d, st):
    n = (monday_of(d) - monday_of(upper_anchor(st))).days // 7
    return "u" if n % 2 == 0 else "l"


def week_name(w):
    return "верхняя" if w == "u" else "нижняя"


# ---------- Форматирование расписания ----------

def lessons(weekday, week, sub):
    out = []

    for p, w, key, extra in DAYS.get(weekday, []):
        if w not in ("b", week):
            continue

        if isinstance(extra, list):
            groups = [g for g in extra if not sub or g[0] == sub]

            if not groups:
                continue

            out.append((p, key, None, groups, w))
        else:
            out.append((p, key, extra, None, w))

    return sorted(out, key=lambda x: x[0])


def format_day(d, st, sub):
    w = week_of(d, st)
    head = "<b>%s, %s</b> · %s неделя" % (
        DAY_NAMES[d.weekday()],
        d.strftime("%d.%m"),
        week_name(w)
    )

    ls = lessons(d.weekday(), w, sub)

    if not ls:
        result = head + "\n\n🦆 Занятий нет, утка отдыхает."
    else:
        blocks = []

        for p, key, room, groups, wk in ls:
            duck, title, teacher = SUBJECTS[key]
            t0, t1 = PAIRS[p]

            lines = [
                "%s %s <b>%s</b>" % (duck, MARKS[key], escape(title)),
                "   %d пара · %s–%s" % (p, t0, t1)
            ]

            if groups:
                for sg, tname, r in groups:
                    lines.append(
                        "   подгруппа %d · %s · ауд. %s"
                        % (sg, escape(tname), r)
                    )
            else:
                where = "вне аудитории" if room == "–" else "ауд. " + room
                lines.append(
                    "   " + " · ".join(
                        x for x in (escape(teacher), where) if x
                    )
                )

            if wk == "b":
                lines.append("   каждую неделю")

            blocks.append("\n".join(lines))

        result = head + "\n\n" + "\n\n".join(blocks)

    if st.get("repl", {}).get(d.isoformat(), {}).get("rows"):
        result += "\n\n⚠️ На этот день есть замены. Смотрите /repl"

    return result


def format_week(week, sub):
    out = ["<b>%s неделя</b>" % week_name(week).capitalize()]

    for wd in range(6):
        ls = lessons(wd, week, sub)
        block = ["", "<b>%s</b>" % DAY_NAMES[wd]]

        if not ls:
            block.append("— занятий нет")

        for p, key, room, groups, wk in ls:
            duck, title, teacher = SUBJECTS[key]
            t0 = PAIRS[p][0]

            if groups:
                room_text = ", ".join(
                    "п/г %d: %s" % (g[0], g[2]) for g in groups
                )
            else:
                room_text = "вне ауд." if room == "–" else room

            block.append(
                "%s%s %d) %s %s · %s"
                % (duck, MARKS[key], p, t0, escape(title), room_text)
            )

        out.append("\n".join(block))

    return "\n".join(out)


# ---------- Замены ----------

def parse_repl(text):
    a, b = text.find("{"), text.rfind("}")

    if a < 0 or b < a:
        raise ValueError("В ответе Gemini нет JSON")

    data = json.loads(text[a:b + 1])

    day = data.get("date")

    try:
        day = date.fromisoformat(str(day)).isoformat()
    except (ValueError, TypeError):
        day = None

    rows = []

    for item in data.get("rows") or []:
        if not isinstance(item, dict):
            continue

        pair = item.get("pair")

        if not isinstance(pair, int) or pair not in PAIRS:
            pair = None

        row = {"pair": pair}

        for key in ("was", "now", "teacher", "room", "note"):
            row[key] = str(item.get(key) or "").strip()[:200]

        if row["was"] or row["now"] or row["note"]:
            rows.append(row)

    return {
        "date": day,
        "found": bool(data.get("group_found", bool(rows))),
        "rows": rows
    }


def improve_image(img):
    image = Image.open(BytesIO(img))
    image = ImageOps.exif_transpose(image)
    image = image.convert("RGB")

    width, height = image.size

    # Увеличиваем маленькие фотографии
    if width < 1800:
        scale = min(2, 1800 / width)
        image = image.resize(
            (int(width * scale), int(height * scale)),
            Image.Resampling.LANCZOS
        )

    # Не допускаем чрезмерно большие изображения
    image.thumbnail((3000, 3000), Image.Resampling.LANCZOS)

    image = ImageOps.autocontrast(image)
    image = ImageEnhance.Contrast(image).enhance(1.25)
    image = ImageEnhance.Sharpness(image).enhance(1.5)
    image = image.filter(ImageFilter.UnsharpMask(
        radius=2,
        percent=120,
        threshold=3
    ))

    output = BytesIO()
    image.save(output, format="JPEG", quality=94, optimize=True)

    return output.getvalue()


def recognize(img, mime, today):
    if not GEMINI_API_KEY:
        raise ValueError("Не задан GEMINI_API_KEY")

    img = improve_image(img)
    mime = "image/jpeg"

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        + GEMINI_MODEL
        + ":generateContent"
    )

    prompt = REPL_PROMPT.replace("{today}", today.isoformat())

    prompt += """

Дополнительные правила:
- Внимательно изучи всю таблицу.
- Найди только группу мИСПР-24-2.
- Учитывай все строки и столбцы.
- Проверяй номера пар, фамилии и аудитории.
- Не путай похожие буквы и цифры.
- Если текст невозможно прочитать, оставь поле пустым.
- Не придумывай информацию.
- Верни только корректный JSON.
"""

    payload = {
        "contents": [{
            "role": "user",
            "parts": [
                {
                    "inline_data": {
                        "mime_type": mime,
                        "data": base64.b64encode(img).decode("ascii")
                    }
                },
                {"text": prompt}
            ]
        }],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": 4000,
            "responseMimeType": "application/json"
        }
    }

    req_data = json.dumps(payload).encode("utf-8")

    for attempt in range(3):
        req = urllib.request.Request(
            url,
            data=req_data,
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": GEMINI_API_KEY
            },
            method="POST"
        )

        try:
            print("Отправка фото в Gemini. Попытка %d из 3..." % (attempt + 1))

            with urllib.request.urlopen(req, timeout=360) as response:
                result = json.loads(response.read().decode("utf-8"))

            candidates = result.get("candidates", [])

            if not candidates:
                raise ValueError("Gemini не вернул результат")

            parts = candidates[0].get("content", {}).get("parts", [])

            answer = "".join(
                part.get("text", "")
                for part in parts
                if part.get("text")
            )

            if not answer:
                raise ValueError("Gemini вернул пустой ответ")

            return parse_repl(answer)

        except urllib.error.HTTPError as e:
            error_text = e.read().decode("utf-8", errors="replace")
            print("Gemini API error:", e.code, error_text)

            if e.code not in (429, 500, 502, 503, 504):
                raise RuntimeError("Ошибка Gemini API: HTTP %s" % e.code)

        except (TimeoutError, urllib.error.URLError) as e:
            print("Ошибка соединения с Gemini:", e)

        except Exception as e:
            print("Ошибка распознавания:", e)
            raise

        if attempt < 2:
            wait = 5 * (attempt + 1)
            print("Повторная попытка через %d секунд..." % wait)
            time.sleep(wait)

    raise RuntimeError(
        "Gemini не ответил после трёх попыток. "
        "Попробуйте отправить фотографию позже."
    )


def prune_repl(st):
    keep = (datetime.now(TZ).date() - timedelta(days=1)).isoformat()

    repl = st.setdefault("repl", {})

    for key in list(repl):
        if key < keep:
            del repl[key]

    return repl


def format_repl_day(iso, entry):
    d = date.fromisoformat(iso)

    head = "<b>Замены · %s, %s</b>" % (
        DAY_NAMES[d.weekday()],
        d.strftime("%d.%m")
    )

    rows = entry.get("rows", [])

    if not rows:
        return head + "\n\nДля группы замен нет."

    blocks = []

    for r in sorted(rows, key=lambda x: x.get("pair") or 99):
        p = r.get("pair")

        when = (
            "%d пара · %s–%s" % (p, PAIRS[p][0], PAIRS[p][1])
            if p in PAIRS else "пара не указана"
        )

        was = escape(r.get("was", ""))
        new = escape(r.get("now", ""))

        if new:
            line = ("<s>%s</s> → " % was if was else "")
            line += "<b>%s</b>" % new
        else:
            line = ("<s>%s</s> " % was if was else "")
            line += "<b>отмена</b>"

        room = r.get("room", "")

        extra = " · ".join(
            x for x in (
                escape(r.get("teacher", "")),
                "ауд. " + escape(room) if room else "",
                escape(r.get("note", "")) if new else ""
            ) if x
        )

        blocks.append(
            "🔄 %s\n   %s%s"
            % (when, line, "\n   " + extra if extra else "")
        )

    return head + "\n\n" + "\n\n".join(blocks)


def format_repl_all(st):
    today = datetime.now(TZ).date().isoformat()
    repl = prune_repl(st)
    days = sorted(k for k in repl if k >= today)

    if not days:
        return "Замен нет. Если они есть, пришлите фото листа с заменами."

    return "\n\n".join(format_repl_day(k, repl[k]) for k in days)


def tg_download(file_id):
    info = call("getFile", file_id=file_id)["result"]

    url = "https://api.telegram.org/file/bot%s/%s" % (
        TOKEN, info["file_path"]
    )

    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read(), info["file_path"].lower()


_last_group = {"id": None}


def handle_photo(m):
    chat_id = m["chat"]["id"]
    uid = (m.get("from") or {}).get("id", chat_id)

    if ADMINS and uid not in ADMINS:
        return send(
            chat_id,
            "Загружать замены могут только выбранные люди. "
            "Ваш id: <code>%s</code>" % uid
        )

    if not GEMINI_API_KEY:
        return send(
            chat_id,
            "Для распознавания фото задайте GEMINI_API_KEY "
            "в настройках бота."
        )

    if m.get("photo"):
        file_id = m["photo"][-1]["file_id"]
    else:
        file_id = m["document"]["file_id"]

    mg = m.get("media_group_id")

    if not mg or mg != _last_group["id"]:
        send(chat_id, "Читаю фото через Gemini…", keyboard=False)

    _last_group["id"] = mg

    try:
        img, path = tg_download(file_id)

        if len(img) > 4_900_000:
            return send(
                chat_id,
                "Файл слишком большой. Отправьте его как обычное фото."
            )

        if path.endswith(".png"):
            mime = "image/png"
        elif path.endswith(".webp"):
            mime = "image/webp"
        else:
            mime = "image/jpeg"

        result = recognize(img, mime, datetime.now(TZ).date())

    except Exception as e:
        print("Ошибка распознавания:", e)
        return send(
            chat_id,
            "Не получилось прочитать фото. "
            "Попробуйте ещё раз или снимите лист ровнее и крупнее."
        )

    if not result["found"] or not result["rows"]:
        return send(
            chat_id,
            "Для мИСПР-24-2 на этом фото замен не нашёл. Ничего не менял."
        )

    guessed = result["date"] is None

    iso = result["date"] or (
        datetime.now(TZ).date() + timedelta(days=1)
    ).isoformat()

    st = load_state()
    repl = prune_repl(st)
    old = repl.get(iso)

    if old and mg and old.get("mg") == mg:
        seen = {
            (r["pair"], r["was"], r["now"])
            for r in old["rows"]
        }

        rows = old["rows"] + [
            r for r in result["rows"]
            if (r["pair"], r["was"], r["now"]) not in seen
        ]
    else:
        rows = result["rows"]

    repl[iso] = {
        "rows": rows,
        "mg": mg,
        "updated": datetime.now(TZ).isoformat(timespec="minutes")
    }

    save_state(st)

    text = format_repl_day(iso, repl[iso])

    if guessed:
        text += (
            "\n\n⚠️ Дату на фото не разобрал, поставил завтрашнюю. "
            "Если дата неверная, отправьте фото ещё раз."
        )

    text += "\n\nСохранил! Замены уже видны во вкладке «Замены»."

    send(chat_id, text)


# ---------- Веб-сервер для Mini App ----------

class Api(BaseHTTPRequestHandler):
    def _out(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._out(204, b"", "text/plain")

    def do_GET(self):
        path = self.path.split("?")[0]

        if path in ("/api/replacements", "/api/replacements.json"):
            st = load_state()
            repl = prune_repl(st)

            body = json.dumps(
                {"days": repl},
                ensure_ascii=False
            ).encode()

            return self._out(200, body, "application/json; charset=utf-8")

        if path in ("/", "/index.html"):
            try:
                with open(os.path.join(HERE, "index.html"), "rb") as f:
                    return self._out(
                        200, f.read(), "text/html; charset=utf-8"
                    )
            except OSError:
                pass

        self._out(404, b"not found", "text/plain")

    def log_message(self, *args):
        pass


def start_api():
    server = ThreadingHTTPServer(("0.0.0.0", API_PORT), Api)

    threading.Thread(
        target=server.serve_forever,
        daemon=True
    ).start()

    print("Веб-сервер запущен на порту", API_PORT)


# ---------- Команды ----------

def handle(chat_id, text):
    st = load_state()
    users = st.setdefault("users", {})

    sub = users.get(str(chat_id), {}).get("sub", 0)
    now = datetime.now(TZ).date()

    t = text.strip()
    low = t.lower()
    cmd, _, arg = t.partition(" ")
    cmd = cmd.split("@")[0].lower()
    arg = arg.strip().lower()

    if cmd in ("/start", "/help"):
        w = week_of(now, st)
        return send(
            chat_id,
            HELP + "\n\nСейчас у бота: <b>%s неделя</b>." % week_name(w)
        )

    if cmd == "/today" or low == "сегодня":
        return send(chat_id, format_day(now, st, sub))

    if cmd == "/tomorrow" or low == "завтра":
        return send(chat_id, format_day(now + timedelta(days=1), st, sub))

    if cmd == "/myid":
        return send(chat_id, "Ваш id: <code>%s</code>" % chat_id)

    if cmd == "/repl" or low == "замены":
        return send(chat_id, format_repl_all(st))

    if cmd == "/clearrepl":
        if ADMINS and chat_id not in ADMINS:
            return send(chat_id, "Это могут только выбранные люди.")

        repl = prune_repl(st)

        if arg == "all":
            repl.clear()
        elif arg in repl:
            del repl[arg]
        else:
            return send(
                chat_id,
                "Напишите /clearrepl all или /clearrepl ГГГГ-ММ-ДД"
            )

        save_state(st)
        return send(chat_id, "Замены удалены.")

    if cmd == "/week" or low == "эта неделя":
        return send(chat_id, format_week(week_of(now, st), sub))

    if cmd == "/next" or low == "следующая неделя":
        return send(
            chat_id,
            format_week(week_of(now + timedelta(days=7), st), sub)
        )

    if cmd == "/upper" or low == "верхняя неделя":
        return send(chat_id, format_week("u", sub))

    if cmd == "/lower" or low == "нижняя неделя":
        return send(chat_id, format_week("l", sub))

    if cmd == "/setweek":
        if arg.startswith("верх"):
            want = "u"
        elif arg.startswith("ниж"):
            want = "l"
        else:
            return send(
                chat_id,
                "Напишите: /setweek верхняя или /setweek нижняя"
            )

        mon = monday_of(now)

        st["upper_monday"] = (
            mon if want == "u" else mon - timedelta(days=7)
        ).isoformat()

        save_state(st)

        return send(
            chat_id,
            "Готово. Текущая неделя: <b>%s</b>." % week_name(want)
        )

    new_sub = None

    if cmd == "/sub" and arg in ("0", "1", "2"):
        new_sub = int(arg)

    elif low in ("подгруппа 1", "подгруппа 2", "обе подгруппы"):
        new_sub = {
            "подгруппа 1": 1,
            "подгруппа 2": 2,
            "обе подгруппы": 0
        }[low]

    if new_sub is not None:
        users[str(chat_id)] = {"sub": new_sub}
        save_state(st)

        label = (
            "обе подгруппы"
            if new_sub == 0
            else "подгруппа %d" % new_sub
        )

        return send(chat_id, "Запомнил: %s." % label)

    send(chat_id, "Не понял. Нажмите кнопку внизу или отправьте /help.")


def main():
    if not TOKEN:
        raise SystemExit("Не задан BOT_TOKEN")

    if WEBAPP_URL:
        try:
            call(
                "setChatMenuButton",
                menu_button={
                    "type": "web_app",
                    "text": "Расписание",
                    "web_app": {"url": WEBAPP_URL + "?v=2"}
                }
            )
        except Exception as e:
            print("Не удалось поставить кнопку меню:", e)
    else:
        print("WEBAPP_URL не задан: мини-приложение не подключено.")

    if API_PORT:
        start_api()
    else:
        print("API_PORT не задан: веб-сервер выключен.")

    if not GEMINI_API_KEY:
        print("GEMINI_API_KEY не задан: распознавание фото выключено.")
    else:
        print("Gemini подключен. Модель:", GEMINI_MODEL)

    print("Бот запущен. Остановить: Ctrl+C")

    offset = 0

    while True:
        try:
            result = call(
                "getUpdates",
                offset=offset,
                timeout=50,
                allowed_updates=["message"]
            )

            for update in result.get("result", []):
                offset = update["update_id"] + 1
                message = update.get("message") or {}

                try:
                    if (
                        message.get("photo")
                        or (message.get("document") or {})
                        .get("mime_type", "").startswith("image/")
                    ):
                        handle_photo(message)

                    elif message.get("text"):
                        handle(message["chat"]["id"], message["text"])

                except Exception as e:
                    print("Ошибка обработки:", e)

        except KeyboardInterrupt:
            break

        except Exception as e:
            print("Ошибка сети:", e)
            time.sleep(5)


if __name__ == "__main__":
    main()
