import os
import sqlite3
from datetime import datetime, timedelta

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    ConversationHandler,
    filters,
)

# ===== ԿԱՐԳԱՎՈՐՈՒՄՆԵՐ =====
TOKEN = os.environ.get("BOT_TOKEN")        # token-ը Termux-ում export-ով ենք դնում
BARBER_ID = 6313339628                     
OPEN_HOUR = 10                             # բացման ժամ
CLOSE_HOUR = 23                            # փակման ժամ (վերջին գրառումը 22:00)
DAYS_AHEAD = 7                             # քանի օր առաջ ցույց տալ
TZ_OFFSET = 4                              # Երևան UTC+4
CONFIRM_TIMEOUT_MIN = 120                  # վարսավիրի հաստատման ժամկետ (րոպե)
BARBER_REMINDER_MIN = 15                   # վարսավիրին հիշեցում հաճախորդից առաջ (րոպե)

# Զրույցի փուլերը
ASK_NAME, ASK_PHONE = range(2)

WEEKDAYS = ["Երկ", "Երք", "Չրք", "Հնգ", "Ուր", "Շբթ", "Կիր"]
MONTHS = ["", "հնվ", "փտ", "մրտ", "ապր", "մյս", "հնս",
          "հլս", "օգս", "սպտ", "հկտ", "նյմ", "դկտ"]


# ===== ՏՎՅԱԼՆԵՐԻ ԲԱԶԱ =====
def db():
    return sqlite3.connect("salon.db")


def init_db():
    conn = db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS clients (
            user_id INTEGER PRIMARY KEY,
            name TEXT,
            phone TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            name TEXT,
            phone TEXT,
            date TEXT,
            time TEXT,
            status TEXT
        )
    """)
    # (4) փակ օրեր (արձակուրդ / հանգստյան)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS closed_days (
            date TEXT PRIMARY KEY
        )
    """)
    conn.commit()
    conn.close()


def get_client(user_id):
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT name, phone FROM clients WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row


def save_client(user_id, name, phone):
    conn = db()
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO clients (user_id, name, phone) VALUES (?, ?, ?)",
        (user_id, name, phone),
    )
    conn.commit()
    conn.close()


def now_local():
    return datetime.utcnow() + timedelta(hours=TZ_OFFSET)


# ===== ՕԳՆԱԿԱՆ =====
def taken_times(date_str):
    conn = db()
    cur = conn.cursor()
    cur.execute(
        "SELECT time FROM bookings WHERE date = ? AND status IN ('pending','confirmed')",
        (date_str,),
    )
    rows = cur.fetchall()
    conn.close()
    return {r[0] for r in rows}


def already_booked_today(user_id, date_str):
    conn = db()
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM bookings WHERE user_id = ? AND date = ? "
        "AND status IN ('pending','confirmed')",
        (user_id, date_str),
    )
    row = cur.fetchone()
    conn.close()
    return row is not None


def is_closed(date_str):
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM closed_days WHERE date = ?", (date_str,))
    row = cur.fetchone()
    conn.close()
    return row is not None


def fmt_date_label(d):
    return f"{WEEKDAYS[d.weekday()]} {d.day} {MONTHS[d.month]}"


# ===== /start =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    client = get_client(user.id)

    if client is None:
        await update.message.reply_text(
            "Բարի գալուստ Rich Barbershop! 💇‍♂️\n\n"
            "Գրանցվելու համար նախ ասեք Ձեր անունը:"
        )
        return ASK_NAME
    else:
        await show_main_menu(update, context)
        return ConversationHandler.END


async def ask_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text.strip()
    kb = ReplyKeyboardMarkup(
        [[KeyboardButton("📱 Ուղարկել իմ համարը", request_contact=True)]],
        resize_keyboard=True, one_time_keyboard=True,
    )
    await update.message.reply_text(
        f"Շնորհակալ եմ, {context.user_data['name']}!\n\n"
        "Հիմա ուղարկեք Ձեր հեռախոսահամարը (կոճակով կամ ձեռքով գրեք):",
        reply_markup=kb,
    )
    return ASK_PHONE


async def ask_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.contact:
        phone = update.message.contact.phone_number
    else:
        phone = update.message.text.strip()
    user = update.effective_user
    save_client(user.id, context.user_data["name"], phone)
    await update.message.reply_text("Գրանցումն ավարտված է! ✅",
                                    reply_markup=ReplyKeyboardRemove())
    await show_main_menu(update, context)
    return ConversationHandler.END


# ===== ԳԼԽԱՎՈՐ ՄԵՆՅՈՒ =====
async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    buttons = [
        [InlineKeyboardButton("✂️ Հերթ գրանցել", callback_data="new_booking")],
        [InlineKeyboardButton("📋 Իմ գրառումները", callback_data="my_bookings")],
    ]
    markup = InlineKeyboardMarkup(buttons)
    text = "Ընտրեք գործողություն:"
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=markup)
    else:
        await update.message.reply_text(text, reply_markup=markup)


# ===== ՕՐԱՑՈՒՅՑ =====
async def show_calendar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = now_local().date()
    buttons = []
    for i in range(DAYS_AHEAD):
        d = today + timedelta(days=i)
        date_str = d.isoformat()
        if is_closed(date_str):
            continue  # (4) փակ օրը չենք ցույց տալիս
        label = fmt_date_label(d)
        if i == 0:
            label = "Այսօր " + label
        elif i == 1:
            label = "Վաղը " + label
        buttons.append([InlineKeyboardButton(label, callback_data=f"day_{date_str}")])

    buttons.append([InlineKeyboardButton("⬅️ Մենյու", callback_data="menu")])
    markup = InlineKeyboardMarkup(buttons)
    text = "📅 Ընտրեք օրը:"
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=markup)
    else:
        await update.message.reply_text(text, reply_markup=markup)


async def show_times(update, context, date_str):
    taken = taken_times(date_str)
    today = now_local()
    sel_date = datetime.fromisoformat(date_str).date()

    buttons, row = [], []
    for hour in range(OPEN_HOUR, CLOSE_HOUR):
        t = f"{hour:02d}:00"
        if sel_date == today.date() and hour <= today.hour:
            continue
        if t in taken:
            continue
        row.append(InlineKeyboardButton(t, callback_data=f"time_{date_str}_{t}"))
        if len(row) == 3:
            buttons.append(row); row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("⬅️ Հետ", callback_data="back_cal")])

    query = update.callback_query
    if len(buttons) == 1:
        await query.edit_message_text(
            f"😔 {fmt_date_label(sel_date)} — ազատ ժամ չկա:",
            reply_markup=InlineKeyboardMarkup(buttons))
    else:
        await query.edit_message_text(
            f"🕐 {fmt_date_label(sel_date)} — ընտրեք ժամը:",
            reply_markup=InlineKeyboardMarkup(buttons))


# ===== ԿՈՃԱԿՆԵՐ =====
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "menu":
        await show_main_menu(update, context)
    elif data == "new_booking":
        await show_calendar(update, context)
    elif data == "my_bookings":
        await show_my_bookings(update, context)
    elif data.startswith("day_"):
        await show_times(update, context, data[4:])
    elif data == "back_cal":
        await show_calendar(update, context)
    elif data.startswith("time_"):
        await make_booking(update, context, data)
    elif data.startswith("ok_"):
        await handle_barber_decision(update, context, data[3:], approve=True)
    elif data.startswith("no_"):
        await handle_barber_decision(update, context, data[3:], approve=False)
    elif data.startswith("cancel_"):
        await cancel_booking(update, context, data[7:])


# ===== ԳՐԱՆՑՈՒՄ =====
async def make_booking(update, context, data):
    query = update.callback_query
    _, date_str, t = data.split("_")
    user = query.from_user

    if already_booked_today(user.id, date_str):
        await query.edit_message_text(
            "⚠️ Դուք արդեն գրանցում ունեք այդ օրվա համար։\n"
            "Մեկ օրում կարող եք գրանցվել միայն մեկ անգամ։")
        return
    if t in taken_times(date_str):
        await query.edit_message_text(
            "😔 Ներեցեք, այս ժամն արդեն զբաղված է։ Ընտրեք ուրիշ ժամ։")
        return

    client = get_client(user.id)
    name = client[0] if client else user.first_name
    phone = client[1] if client else "—"

    conn = db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO bookings (user_id, name, phone, date, time, status) "
        "VALUES (?,?,?,?,?,'pending')",
        (user.id, name, phone, date_str, t))
    booking_id = cur.lastrowid
    conn.commit()
    conn.close()

    sel_date = datetime.fromisoformat(date_str).date()
    await query.edit_message_text(
        f"⏳ Ձեր հայտն ուղարկվեց վարսավիրին հաստատման։\n\n"
        f"📅 {fmt_date_label(sel_date)}\n🕐 {t}\n\nՍպասեք հաստատմանը 🙏")

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Հաստատել", callback_data=f"ok_{booking_id}"),
        InlineKeyboardButton("❌ Մերժել", callback_data=f"no_{booking_id}"),
    ]])
    await context.bot.send_message(
        chat_id=BARBER_ID,
        text=(f"🔔 Նոր հայտ\n\n👤 {name}\n📱 {phone}\n"
              f"📅 {fmt_date_label(sel_date)}\n🕐 {t}"),
        reply_markup=kb)

    # (5) հաստատման ժամկետ — եթե վարսավիրը չհաստատի, ավտոմատ չեղարկում
    context.job_queue.run_once(
        auto_expire, CONFIRM_TIMEOUT_MIN * 60,
        data={"booking_id": booking_id},
        name=f"expire_{booking_id}")


# (5) ավտոմատ ժամկետանց
async def auto_expire(context: ContextTypes.DEFAULT_TYPE):
    booking_id = context.job.data["booking_id"]
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT user_id, status FROM bookings WHERE id = ?", (booking_id,))
    row = cur.fetchone()
    if row and row[1] == "pending":
        cur.execute("UPDATE bookings SET status='expired' WHERE id=?", (booking_id,))
        conn.commit()
        await context.bot.send_message(
            chat_id=row[0],
            text="⌛ Ձեր հայտը ժամկետանց եղավ (վարսավիրը չհասցրեց պատասխանել)։\n"
                 "Կարող եք նորից փորձել՝ /start")
        await context.bot.send_message(
            chat_id=BARBER_ID,
            text=f"⌛ Հայտ #{booking_id}-ը ավտոմատ չեղարկվեց (ժամկետանց)։")
    conn.close()


# ===== ՎԱՐՍԱՎԻՐԻ ՈՐՈՇՈՒՄ =====
async def handle_barber_decision(update, context, booking_id, approve):
    query = update.callback_query
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT user_id,name,phone,date,time,status FROM bookings WHERE id=?",
                (booking_id,))
    row = cur.fetchone()
    if not row:
        await query.edit_message_text("Այս հայտն այլևս չկա։"); conn.close(); return
    user_id, name, phone, date_str, t, status = row
    if status != "pending":
        await query.edit_message_text("Այս հայտն արդեն մշակված է։"); conn.close(); return

    sel_date = datetime.fromisoformat(date_str).date()

    if approve:
        cur.execute("UPDATE bookings SET status='confirmed' WHERE id=?", (booking_id,))
        conn.commit(); conn.close()
        await query.edit_message_text(
            f"✅ Հաստատված\n\n👤 {name}\n📱 {phone}\n"
            f"📅 {fmt_date_label(sel_date)}\n🕐 {t}")
        await context.bot.send_message(
            chat_id=user_id,
            text=(f"🎉 Ձեր գրառումը հաստատվեց!\n\n"
                  f"📅 {fmt_date_label(sel_date)}\n🕐 {t}\n\nՍպասում ենք Ձեզ! 💈"))
        schedule_reminders(context, booking_id, user_id, name, phone, sel_date, t)
    else:
        cur.execute("UPDATE bookings SET status='rejected' WHERE id=?", (booking_id,))
        conn.commit(); conn.close()
        await query.edit_message_text(
            f"❌ Մերժված\n\n👤 {name}\n📅 {fmt_date_label(sel_date)}\n🕐 {t}")
        await context.bot.send_message(
            chat_id=user_id,
            text=(f"😔 Ցավոք, Ձեր գրառումը մերժվեց:\n"
                  f"📅 {fmt_date_label(sel_date)}\n🕐 {t}\n\nԸնտրեք ուրիշ ժամ՝ /start"))


# ===== (1) ՀԱՃԱԽՈՐԴԻ ԳՐԱՌՈՒՄՆԵՐ + ՉԵՂԱՐԿՈՒՄ =====
async def show_my_bookings(update, context):
    query = update.callback_query
    user_id = query.from_user.id
    today_str = now_local().date().isoformat()

    conn = db()
    cur = conn.cursor()
    cur.execute(
        "SELECT id,date,time,status FROM bookings "
        "WHERE user_id=? AND date>=? AND status IN ('pending','confirmed') "
        "ORDER BY date,time", (user_id, today_str))
    rows = cur.fetchall()
    conn.close()

    if not rows:
        await query.edit_message_text(
            "Դուք ակտիվ գրառում չունեք։",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("⬅️ Մենյու", callback_data="menu")]]))
        return

    buttons = []
    for bid, date_str, t, status in rows:
        d = datetime.fromisoformat(date_str).date()
        mark = "✅" if status == "confirmed" else "⏳"
        buttons.append([InlineKeyboardButton(
            f"{mark} {fmt_date_label(d)} {t}  ❌ չեղարկել",
            callback_data=f"cancel_{bid}")])
    buttons.append([InlineKeyboardButton("⬅️ Մենյու", callback_data="menu")])

    await query.edit_message_text(
        "📋 Ձեր գրառումները (սեղմեք չեղարկելու համար):",
        reply_markup=InlineKeyboardMarkup(buttons))


async def cancel_booking(update, context, booking_id):
    query = update.callback_query
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT user_id,name,date,time,status FROM bookings WHERE id=?",
                (booking_id,))
    row = cur.fetchone()
    if not row or row[4] not in ("pending", "confirmed"):
        await query.edit_message_text("Այս գրառումն այլևս ակտիվ չէ։"); conn.close(); return

    user_id, name, date_str, t, status = row
    cur.execute("UPDATE bookings SET status='cancelled' WHERE id=?", (booking_id,))
    conn.commit(); conn.close()

    sel_date = datetime.fromisoformat(date_str).date()
    await query.edit_message_text(
        f"✅ Չեղարկված է:\n📅 {fmt_date_label(sel_date)}\n🕐 {t}\n\n"
        "Ժամը նորից ազատ է: /start նոր գրառման համար:")
    # (1) վարսավիրին ծանուցում
    await context.bot.send_message(
        chat_id=BARBER_ID,
        text=(f"🚫 Հաճախորդը չեղարկեց գրառումը\n\n"
              f"👤 {name}\n📅 {fmt_date_label(sel_date)}\n🕐 {t}"))


# ===== ՀԻՇԵՑՈՒՄՆԵՐ =====
def schedule_reminders(context, booking_id, user_id, name, phone, sel_date, t):
    hour, minute = map(int, t.split(":"))
    appt = datetime(sel_date.year, sel_date.month, sel_date.day, hour, minute)
    now = now_local().replace(tzinfo=None)

    # հաճախորդին՝ 20 և 10 րոպե առաջ
    for mins in (20, 10):
        delay = (appt - timedelta(minutes=mins) - now).total_seconds()
        if delay > 0:
            context.job_queue.run_once(
                send_client_reminder, delay,
                data={"user_id": user_id, "time": t, "mins": mins},
                name=f"rem_{booking_id}_{mins}")

    # (6) վարսավիրին՝ 15 րոպե առաջ
    delay = (appt - timedelta(minutes=BARBER_REMINDER_MIN) - now).total_seconds()
    if delay > 0:
        context.job_queue.run_once(
            send_barber_reminder, delay,
            data={"name": name, "phone": phone, "time": t,
                  "mins": BARBER_REMINDER_MIN},
            name=f"brem_{booking_id}")


async def send_client_reminder(context: ContextTypes.DEFAULT_TYPE):
    d = context.job.data
    await context.bot.send_message(
        chat_id=d["user_id"],
        text=f"⏰ Հիշեցում! Ձեր հերթը {d['time']}-ին է, մնաց {d['mins']} րոպե: 💈")


# (6) վարսավիրի հիշեցում
async def send_barber_reminder(context: ContextTypes.DEFAULT_TYPE):
    d = context.job.data
    await context.bot.send_message(
        chat_id=BARBER_ID,
        text=(f"⏰ Հաջորդ հաճախորդը {d['mins']} րոպեից:\n\n"
              f"👤 {d['name']}\n📱 {d['phone']}\n🕐 {d['time']}"))


# ===== (3) ՀԻՇԵՑՈՒՄՆԵՐԻ ՎԵՐԱԿԱՆԳՆՈՒՄ ԳՈՐԾԱՐԿՄԱՆ ՊԱՀԻՆ =====
async def restore_reminders(app: Application):
    conn = db()
    cur = conn.cursor()
    today_str = now_local().date().isoformat()
    cur.execute(
        "SELECT id,user_id,name,phone,date,time FROM bookings "
        "WHERE status='confirmed' AND date>=?", (today_str,))
    rows = cur.fetchall()
    conn.close()

    class FakeCtx:
        job_queue = app.job_queue

    count = 0
    for bid, user_id, name, phone, date_str, t in rows:
        sel_date = datetime.fromisoformat(date_str).date()
        schedule_reminders(FakeCtx, bid, user_id, name, phone, sel_date, t)
        count += 1
    if count:
        print(f"Վերականգնվեց {count} գրառման հիշեցում")


# ===== (2) ՎԱՐՍԱՎԻՐԻ ՎԱՀԱՆԱԿ =====
def is_barber(update):
    return update.effective_user.id == BARBER_ID


async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_barber(update):
        return
    date_str = now_local().date().isoformat()
    await send_day_schedule(update, date_str, "Այսօրվա")


async def cmd_week(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_barber(update):
        return
    today = now_local().date()
    conn = db()
    cur = conn.cursor()
    lines = ["📋 Շաբաթվա գրառումներ:\n"]
    total = 0
    for i in range(DAYS_AHEAD):
        d = today + timedelta(days=i)
        cur.execute(
            "SELECT time,name,phone FROM bookings "
            "WHERE date=? AND status='confirmed' ORDER BY time",
            (d.isoformat(),))
        day_rows = cur.fetchall()
        if day_rows:
            lines.append(f"\n📅 {fmt_date_label(d)}")
            for t, name, phone in day_rows:
                lines.append(f"  🕐 {t} — {name} ({phone})")
                total += 1
    conn.close()
    if total == 0:
        lines.append("\nԱռաջիկա շաբաթում գրառում չկա:")
    await update.message.reply_text("\n".join(lines))


async def send_day_schedule(update, date_str, label):
    conn = db()
    cur = conn.cursor()
    cur.execute(
        "SELECT time,name,phone FROM bookings "
        "WHERE date=? AND status='confirmed' ORDER BY time", (date_str,))
    rows = cur.fetchall()
    conn.close()
    d = datetime.fromisoformat(date_str).date()
    if not rows:
        await update.message.reply_text(f"📋 {label} ({fmt_date_label(d)}) գրառում չկա:")
        return
    lines = [f"📋 {label} գրառումներ ({fmt_date_label(d)}):\n"]
    for t, name, phone in rows:
        lines.append(f"🕐 {t} — {name} ({phone})")
    await update.message.reply_text("\n".join(lines))


# ===== (4) ՕՐԵՐ ՓԱԿԵԼ / ԲԱՑԵԼ (վարսավիր) =====
async def cmd_close(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_barber(update):
        return
    if not context.args:
        await update.message.reply_text(
            "Օրը փակելու համար գրեք ամսաթիվը:\n"
            "Օրինակ՝ /close 2026-06-30")
        return
    date_str = context.args[0]
    try:
        datetime.fromisoformat(date_str)
    except ValueError:
        await update.message.reply_text("❌ Սխալ ձևաչափ: Օրինակ՝ /close 2026-06-30")
        return
    conn = db()
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO closed_days (date) VALUES (?)", (date_str,))
    conn.commit(); conn.close()
    d = datetime.fromisoformat(date_str).date()
    await update.message.reply_text(f"🔒 {fmt_date_label(d)} օրը փակ է գրառման համար:")


async def cmd_open(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_barber(update):
        return
    if not context.args:
        await update.message.reply_text("Օրինակ՝ /open 2026-06-30")
        return
    date_str = context.args[0]
    conn = db()
    cur = conn.cursor()
    cur.execute("DELETE FROM closed_days WHERE date=?", (date_str,))
    conn.commit(); conn.close()
    try:
        d = datetime.fromisoformat(date_str).date()
        await update.message.reply_text(f"🔓 {fmt_date_label(d)} օրը նորից բաց է:")
    except ValueError:
        await update.message.reply_text("❌ Սխալ ձևաչափ:")


async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_barber(update):
        return
    await update.message.reply_text(
        "🛠 Վարսավիրի հրամաններ:\n\n"
        "/today — այսօրվա գրառումները\n"
        "/week — շաբաթվա գրառումները\n"
        "/close 2026-06-30 — փակել օրը\n"
        "/open 2026-06-30 — բացել օրը")


# ===== ՉԵՂԱՐԿՈՒՄ (զրույց) =====
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Չեղարկված է: /start նորից սկսելու համար:",
                                    reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


# ===== ԳՈՐԾԱՐԿՈՒՄ =====
def main():
    init_db()
    app = Application.builder().token(TOKEN).post_init(restore_reminders).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_name)],
            ASK_PHONE: [MessageHandler(
                (filters.TEXT & ~filters.COMMAND) | filters.CONTACT, ask_phone)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv)
    # վարսավիրի հրամաններ
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("week", cmd_week))
    app.add_handler(CommandHandler("close", cmd_close))
    app.add_handler(CommandHandler("open", cmd_open))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CallbackQueryHandler(button_handler))

    app.run_polling()


if __name__ == "__main__":
    main()
