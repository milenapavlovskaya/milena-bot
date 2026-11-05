"""Telegram-бот: квизы по тренировкам и питанию для клиентов + статистика для админа."""
import asyncio
import csv
import html
import io
import json
import logging
import os
import random
from dataclasses import dataclass, field
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, CommandStart
from aiogram.types import (BotCommand, BotCommandScopeChat, BufferedInputFile, FSInputFile, CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message)
from dotenv import load_dotenv

import card
import db

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x}
QUESTIONS_PER_TEST = int(os.getenv("QUESTIONS_PER_TEST", "8"))

TOPICS: dict = json.loads(Path(__file__).with_name("questions.json").read_text(encoding="utf-8"))

ASSESS: dict = json.loads(Path(__file__).with_name("assessment.json").read_text(encoding="utf-8"))

dp = Dispatcher()


# ---------- состояние прохождения теста ----------

@dataclass
class Question:
    text: str
    options: list[str]
    correct: int
    explain: str


@dataclass
class Session:
    sid: int
    topic: str
    questions: list[Question]
    idx: int = 0
    score: int = 0
    mistakes: list[str] = field(default_factory=list)


sessions: dict[int, Session] = {}


def build_session(topic: str) -> Session:
    raw = TOPICS[topic]["questions"]
    picked = random.sample(raw, min(QUESTIONS_PER_TEST, len(raw)))
    questions = []
    for q in picked:
        order = list(range(len(q["options"])))
        random.shuffle(order)
        questions.append(Question(
            text=q["q"],
            options=[q["options"][i] for i in order],
            correct=order.index(q["correct"]),
            explain=q.get("explain", ""),
        ))
    return Session(sid=random.randint(1, 10**9), topic=topic, questions=questions)


# ---------- клавиатуры ----------

def topics_kb() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=ASSESS["title"], callback_data="as_start")]]
    rows += [[InlineKeyboardButton(text=t["title"], callback_data=f"topic:{key}")]
             for key, t in TOPICS.items()]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def answers_kb(s: Session) -> InlineKeyboardMarkup:
    q = s.questions[s.idx]
    letters = "ABCDEFGH"
    rows = [[InlineKeyboardButton(text=f"{letters[i]}. {opt}"[:60],
                                  callback_data=f"ans:{s.sid}:{s.idx}:{i}")]
            for i, opt in enumerate(q.options)]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def after_test_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔁 Пройти ещё тест", callback_data="menu")],
    ])


def question_text(s: Session) -> str:
    q = s.questions[s.idx]
    letters = "ABCDEFGH"
    opts = "\n".join(f"<b>{letters[i]}.</b> {html.escape(o)}" for i, o in enumerate(q.options))
    return (f"<b>Вопрос {s.idx + 1} из {len(s.questions)}</b>\n\n"
            f"{html.escape(q.text)}\n\n{opts}")


def verdict(pct: float) -> str:
    if pct >= 90:
        return "🏆 Отлично! Вы отлично разбираетесь в теме."
    if pct >= 70:
        return "💪 Хороший результат! Есть пара моментов, которые стоит подтянуть."
    if pct >= 40:
        return "🙂 Неплохо, но базу стоит повторить."
    return "📚 Есть куда расти — обратитесь к тренеру, он поможет разобраться."


# ---------- пользовательские команды ----------

def make_first_admin(user_id: int) -> bool:
    """Если админ ещё не назначен — первый, кто нажал /start, становится админом."""
    if ADMIN_IDS:
        return False
    ADMIN_IDS.add(user_id)
    env = Path(__file__).with_name(".env")
    lines = env.read_text(encoding="utf-8").splitlines() if env.exists() else []
    lines = [l for l in lines if not l.startswith("ADMIN_IDS=")] + [f"ADMIN_IDS={user_id}"]
    env.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True


@dp.message(CommandStart())
async def cmd_start(m: Message) -> None:
    if make_first_admin(m.from_user.id):
        await m.answer("👑 Вы назначены администратором бота.\n"
                       "Команды: /stats — статистика, /export — таблица результатов.")
    caption = (
        f"Привет, {html.escape(m.from_user.first_name)}! 🌸\n\n"
        "Я — бот тренера <b>Милены</b>, профессиональной гимнастки с опытом в спорте более 15 лет.\n\n"
        "✨ Начни с короткого теста о самочувствии и активности — он займёт минуту. "
        "В конце тебя ждут выводы и пробные тренировки.\n\n"
        "🧠 Ниже — тесты на знания о тренировках и питании."
    )
    try:
        await m.answer_photo(FSInputFile(Path(__file__).with_name("assets") / "welcome.jpg"),
                             caption=caption, reply_markup=topics_kb())
    except Exception:
        await m.answer(caption, reply_markup=topics_kb())


@dp.message(Command("help"))
async def cmd_help(m: Message) -> None:
    text = ("/start — выбрать тест\n"
            "/history — мои результаты\n"
            "/cancel — прервать текущий тест")
    if m.from_user.id in ADMIN_IDS:
        text += "\n\n<b>Админ:</b>\n/stats — статистика\n/leads — заявки в чат\n/export — выгрузка результатов в CSV"
    await m.answer(text)


@dp.message(Command("cancel"))
async def cmd_cancel(m: Message) -> None:
    if sessions.pop(m.from_user.id, None):
        await m.answer("Тест прерван.", reply_markup=after_test_kb())
    else:
        await m.answer("Сейчас нет активного теста. /start — начать.")


@dp.message(Command("history"))
async def cmd_history(m: Message) -> None:
    rows = db.user_history(m.from_user.id)
    if not rows:
        await m.answer("Вы ещё не проходили тесты. /start — начать.")
        return
    lines = [f"{r['created_at']} — {TOPICS.get(r['topic'], {}).get('title', r['topic'])}: "
             f"<b>{r['score']}/{r['total']}</b>" for r in rows]
    await m.answer("<b>Ваши последние результаты:</b>\n\n" + "\n".join(lines))


@dp.callback_query(F.data == "menu")
async def cb_menu(c: CallbackQuery) -> None:
    await c.message.answer("Выберите тему теста:", reply_markup=topics_kb())
    await c.answer()


@dp.callback_query(F.data.startswith("topic:"))
async def cb_topic(c: CallbackQuery) -> None:
    topic = c.data.split(":", 1)[1]
    if topic not in TOPICS:
        await c.answer("Тема не найдена", show_alert=True)
        return
    s = build_session(topic)
    sessions[c.from_user.id] = s
    await c.message.answer(f"Начинаем тест «{TOPICS[topic]['title']}» — "
                           f"{len(s.questions)} вопросов. Удачи!")
    await c.message.answer(question_text(s), reply_markup=answers_kb(s))
    await c.answer()


@dp.callback_query(F.data.startswith("ans:"))
async def cb_answer(c: CallbackQuery) -> None:
    _, sid, qidx, opt = c.data.split(":")
    s = sessions.get(c.from_user.id)
    # защита от нажатий на кнопки старых вопросов/тестов
    if not s or s.sid != int(sid) or s.idx != int(qidx):
        await c.answer("Этот вопрос уже неактуален.")
        return

    q = s.questions[s.idx]
    chosen = int(opt)
    if chosen == q.correct:
        s.score += 1
        feedback = "✅ <b>Верно!</b>"
    else:
        s.mistakes.append(q.text)
        feedback = f"❌ <b>Неверно.</b> Правильный ответ: <i>{html.escape(q.options[q.correct])}</i>"
    if q.explain:
        feedback += f"\n\n💡 {html.escape(q.explain)}"

    # убираем кнопки и показываем, что выбрал пользователь
    await c.message.edit_text(
        question_text(s) + f"\n\nВаш ответ: <b>{html.escape(q.options[chosen])}</b>\n\n{feedback}"
    )
    await c.answer()

    s.idx += 1
    if s.idx < len(s.questions):
        await c.message.answer(question_text(s), reply_markup=answers_kb(s))
        return

    # тест окончен
    sessions.pop(c.from_user.id, None)
    total = len(s.questions)
    pct = 100 * s.score / total
    u = c.from_user
    db.save_result(u.id, u.username, u.full_name, s.topic, s.score, total)
    await c.message.answer(
        f"🏁 <b>Тест завершён!</b>\n\n"
        f"Результат: <b>{s.score} из {total}</b> ({pct:.0f}%)\n\n{verdict(pct)}",
        reply_markup=after_test_kb(),
    )
    for admin_id in ADMIN_IDS:
        try:
            await c.bot.send_message(
                admin_id,
                f"📝 {html.escape(u.full_name)}"
                f"{' (@' + u.username + ')' if u.username else ''} прошёл тест "
                f"«{TOPICS[s.topic]['title']}»: <b>{s.score}/{total}</b>",
            )
        except Exception:  # админ мог не запустить бота
            logging.warning("Не удалось уведомить админа %s", admin_id)


# ---------- тест самочувствия и предложение ----------

assess_state: dict[int, dict] = {}
assess_result: dict[int, tuple[int, str]] = {}


OPT_EMOJI = {3: "🌟", 2: "🌿", 1: "🌥", 0: "🌧"}


def progress_bar(done: int, total: int) -> str:
    return "▰" * done + "▱" * (total - done)


def assess_q_text(idx: int, intro: bool = False) -> str:
    qs = ASSESS["questions"]
    q = qs[idx]
    head = f"{ASSESS['intro']}\n\n━━━━━━━━━━\n\n" if intro else ""
    return (f"{head}{q.get('emoji', '✨')} <b>Вопрос {idx + 1} из {len(qs)}</b>\n"
            f"{progress_bar(idx + 1, len(qs))}\n\n"
            f"<b>{html.escape(q['q'])}</b>\n\n"
            f"<i>Выбери вариант, который ближе всего 👇</i>")


def assess_kb(idx: int) -> InlineKeyboardMarkup:
    opts = ASSESS["questions"][idx]["options"]
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{OPT_EMOJI.get(o['score'], '•')}  {o['text']}",
                              callback_data=f"as:{idx}:{i}")]
        for i, o in enumerate(opts)])


@dp.callback_query(F.data == "as_start")
async def cb_as_start(c: CallbackQuery) -> None:
    assess_state[c.from_user.id] = {"idx": 0, "score": 0, "notes": []}
    await c.message.answer(assess_q_text(0, intro=True), reply_markup=assess_kb(0))
    await c.answer()


@dp.callback_query(F.data.startswith("as:"))
async def cb_as_answer(c: CallbackQuery) -> None:
    _, qidx, opt = c.data.split(":")
    st = assess_state.get(c.from_user.id)
    if not st or st["idx"] != int(qidx):
        await c.answer("Этот вопрос уже неактуален.")
        return
    q = ASSESS["questions"][st["idx"]]
    chosen = q["options"][int(opt)]
    st["score"] += chosen["score"]
    if chosen["score"] <= 1 and q.get("note_if_low"):
        st["notes"].append(q["note_if_low"])
    st["idx"] += 1
    total = len(ASSESS["questions"])
    if st["idx"] < total:
        await c.answer(f"{OPT_EMOJI.get(chosen['score'], '')} Записала!")
        # один «живой» экран: вопрос заменяется следующим
        await c.message.edit_text(assess_q_text(st["idx"]), reply_markup=assess_kb(st["idx"]))
        return
    await c.answer()

    # --- «анализ» результата ---
    assess_state.pop(c.from_user.id, None)
    steps = ["✨ Анализирую твои ответы...", "🌿 Оцениваю энергию и гибкость...",
             "💫 Готовлю персональные выводы..."]
    for i, step in enumerate(steps, 1):
        await c.message.edit_text(f"{step}\n\n{progress_bar(i, len(steps))}")
        await asyncio.sleep(0.9)

    level = next(l for l in ASSESS["levels"] if st["score"] >= l["min"])
    assess_result[c.from_user.id] = (st["score"], level["title"])
    max_score = 3 * total
    try:
        await c.message.delete()
    except Exception:
        pass

    name = c.from_user.first_name or ""
    caption = f"<b>{level['title']}</b>\n\n{level['text']}"
    try:
        png = card.make_result_card(name, st["score"], max_score, level["short"], level["color"])
        await c.message.answer_photo(BufferedInputFile(png, filename="result.jpg"), caption=caption)
    except Exception:
        logging.exception("Не удалось сделать карточку")
        await c.message.answer(f"{caption}\n\nТвой результат: {st['score']} из {max_score}")

    if st["notes"]:
        await asyncio.sleep(0.6)
        await c.message.answer("🔎 <b>На что обратить внимание</b>\n\n" +
                               "\n\n".join(f"▫️ {n}" for n in st["notes"]))
    await asyncio.sleep(0.6)
    await c.message.answer(ASSESS["benefits"])
    await asyncio.sleep(0.6)
    vids = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"▶️ {v['title']}", url=v["url"])] for v in ASSESS["videos"]])
    await c.message.answer(ASSESS["videos_intro"], reply_markup=vids)
    await asyncio.sleep(0.8)
    offer = ASSESS["offer"]
    try:
        await c.message.answer_photo(
            FSInputFile(Path(__file__).with_name("assets") / "welcome.jpg"),
            caption=offer["text"], reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=offer["button_yes"], callback_data="lead_yes")],
                [InlineKeyboardButton(text=offer["button_later"], callback_data="lead_later")]]))
    except Exception:  # подпись к фото ограничена 1024 символами
        await c.message.answer(offer["text"], reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=offer["button_yes"], callback_data="lead_yes")],
            [InlineKeyboardButton(text=offer["button_later"], callback_data="lead_later")]]))


@dp.callback_query(F.data == "lead_yes")
async def cb_lead_yes(c: CallbackQuery) -> None:
    u = c.from_user
    score, level = assess_result.get(u.id, (None, None))
    db.save_lead(u.id, u.username, u.full_name, score, level)
    offer = ASSESS["offer"]
    await c.message.answer(offer["after_yes"], reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=offer["button_yes"], url=offer["contact_url"])]]))
    await c.answer()
    who = html.escape(u.full_name) + (f" (@{u.username})" if u.username else "")
    for admin_id in ADMIN_IDS:
        try:
            await c.bot.send_message(
                admin_id,
                f"🔥 <b>Новая заявка в чат!</b>\n{who}\n"
                f"Результат теста: {score if score is not None else 'не проходила'}"
                f"{' — ' + level if level else ''}")
        except Exception:
            logging.warning("Не удалось уведомить админа %s", admin_id)


@dp.callback_query(F.data == "lead_later")
async def cb_lead_later(c: CallbackQuery) -> None:
    await c.message.answer(ASSESS["offer"]["after_later"])
    await c.answer()


# ---------- админ ----------

def is_admin(m: Message) -> bool:
    return m.from_user.id in ADMIN_IDS


@dp.message(Command("stats"), F.func(is_admin))
async def cmd_stats(m: Message) -> None:
    st = db.summary()
    lines = [f"<b>📊 Статистика</b>\n",
             f"Всего прохождений: <b>{st['total']}</b>",
             f"Уникальных пользователей: <b>{st['users']}</b>\n"]
    if st["by_topic"]:
        lines.append("<b>Средний результат по темам:</b>")
        for r in st["by_topic"]:
            title = TOPICS.get(r["topic"], {}).get("title", r["topic"])
            lines.append(f"{title}: {r['avg_pct']:.0f}% ({r['n']} прохожд.)")
    if st["last"]:
        lines.append("\n<b>Последние 10:</b>")
        for r in st["last"]:
            name = html.escape(r["full_name"] or "")
            if r["username"]:
                name += f" (@{r['username']})"
            lines.append(f"{r['created_at']} — {name}: {r['score']}/{r['total']}")
    await m.answer("\n".join(lines))


@dp.message(Command("leads"), F.func(is_admin))
async def cmd_leads(m: Message) -> None:
    rows = db.last_leads()
    if not rows:
        await m.answer("Заявок пока нет.")
        return
    lines = ["<b>🔥 Последние заявки:</b>\n"]
    for r in rows:
        name = html.escape(r["full_name"] or "")
        if r["username"]:
            name += f" (@{r['username']})"
        lines.append(f"{r['created_at']} — {name}: {r['level'] or 'без теста'}")
    await m.answer("\n".join(lines))


@dp.message(Command("export"), F.func(is_admin))
async def cmd_export(m: Message) -> None:
    rows = db.all_results()
    if not rows:
        await m.answer("Пока нет результатов.")
        return
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Дата", "User ID", "Username", "Имя", "Тема", "Баллы", "Всего", "%"])
    for r in rows:
        w.writerow([r["created_at"], r["user_id"], r["username"] or "", r["full_name"],
                    TOPICS.get(r["topic"], {}).get("title", r["topic"]),
                    r["score"], r["total"], round(100 * r["score"] / r["total"])])
    data = buf.getvalue().encode("utf-8-sig")  # BOM, чтобы Excel открыл кириллицу
    await m.answer_document(BufferedInputFile(data, filename="results.csv"))


@dp.message(Command("myid"))
async def cmd_myid(m: Message) -> None:
    await m.answer(f"Ваш Telegram ID: <code>{m.from_user.id}</code>")


async def setup_profile(bot: Bot) -> None:
    """Оформление профиля бота: описание, меню команд."""
    try:
        await bot.set_my_description(
            "🌸 Привет! Я бот тренера Милены — профессиональной гимнастки.\n\n"
            "Пройди короткий тест о самочувствии, узнай свой уровень энергии и гибкости "
            "и получи пробные тренировки для дома.\n\n"
            "Нажми «Начать» 👇")
        await bot.set_my_short_description(
            "Тренер Милена · энергия, гибкость, тренировки дома 🌿")
        await bot.set_my_commands([
            BotCommand(command="start", description="🌿 Главное меню и тесты"),
            BotCommand(command="history", description="📊 Мои результаты"),
            BotCommand(command="cancel", description="✖️ Прервать тест"),
            BotCommand(command="help", description="❓ Помощь"),
        ])
        for admin_id in ADMIN_IDS:
            await bot.set_my_commands([
                BotCommand(command="start", description="🌿 Главное меню и тесты"),
                BotCommand(command="leads", description="🔥 Заявки в чат"),
                BotCommand(command="stats", description="📈 Статистика"),
                BotCommand(command="export", description="📥 Выгрузка в Excel"),
                BotCommand(command="history", description="📊 Мои результаты"),
                BotCommand(command="help", description="❓ Помощь"),
            ], scope=BotCommandScopeChat(chat_id=admin_id))
    except Exception:
        logging.exception("Не удалось оформить профиль бота")
    if os.getenv("SET_AVATAR", "1") != "1":
        return
    try:  # аватар — доступен не во всех версиях Bot API
        from aiogram.types import InputProfilePhotoStatic
        await bot.set_my_profile_photo(InputProfilePhotoStatic(
            photo=FSInputFile(Path(__file__).with_name("assets") / "avatar.jpg")))
        logging.info("Аватар установлен")
    except Exception as e:
        logging.warning("Аватар не установлен автоматически: %s", e)


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    if not BOT_TOKEN:
        raise SystemExit("Укажите BOT_TOKEN в файле .env")
    db.init()
    db.init_leads()
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    await setup_profile(bot)

    base = os.getenv("WEBHOOK_BASE_URL") or os.getenv("RENDER_EXTERNAL_URL")
    if not base:  # локальный запуск
        await dp.start_polling(bot)
        return

    # режим сервера (Render): Telegram сам присылает обновления на наш адрес
    import hashlib
    from aiohttp import web
    from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

    secret = hashlib.sha256(BOT_TOKEN.encode()).hexdigest()

    async def health(_request: web.Request) -> web.Response:
        return web.Response(text="ok")

    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=secret).register(app, path="/webhook")
    setup_application(app, dp, bot=bot)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", int(os.getenv("PORT", "10000"))).start()
    await bot.set_webhook(base.rstrip("/") + "/webhook", secret_token=secret,
                          allowed_updates=dp.resolve_used_update_types())
    logging.info("Webhook установлен: %s/webhook", base.rstrip("/"))
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
