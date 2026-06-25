import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes
)
import sqlite3
from datetime import datetime

TOKEN = os.environ.get("BOT_TOKEN")

def init_db():
    conn = sqlite3.connect("salon.db")
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            name TEXT,
            service TEXT,
            date TEXT,
            time TEXT
        )
    """)
    conn.commit()
    conn.close()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("✂️ Հերթ գրանցել", callback_data="book")],
        [InlineKeyboardButton("📋 Իմ հերթերը", callback_data="my_bookings")],
    ]
    await update.message.reply_text(
        "Բարի գալուստ Rich Barbershop! 💇\nԸնտրեք գործողություն:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "book":
        keyboard = [
            [InlineKeyboardButton("Տղամարդու սանրվածք", callback_data="srv_men")],
            [InlineKeyboardButton("Կանացի սանրվածք", callback_data="srv_women")],
            [InlineKeyboardButton("Մորուքի խնամք", callback_data="srv_beard")],
        ]
        await query.edit_message_text(
            "Ընտրեք ծառայությունը:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data.startswith("srv_"):
        context.user_data["service"] = query.data
        keyboard = [
            [InlineKeyboardButton("10:00", callback_data="time_10")],
            [InlineKeyboardButton("12:00", callback_data="time_12")],
            [InlineKeyboardButton("14:00", callback_data="time_14")],
            [InlineKeyboardButton("16:00", callback_data="time_16")],
        ]
        await query.edit_message_text(
            "Ընտրեք ժամը (այսօր):",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data.startswith("time_"):
        time = query.data.split("_")[1] + ":00"
        service = context.user_data.get("service", "")
        user = query.from_user

        conn = sqlite3.connect("salon.db")
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO bookings (user_id, name, service, date, time) VALUES (?, ?, ?, ?, ?)",
            (user.id, user.first_name, service,
             datetime.now().strftime("%Y-%m-%d"), time)
        )
        conn.commit()
        conn.close()

        await query.edit_message_text(
            f"✅ Հերթը գրանցված է!\n🕐 Ժամ՝ {time}\nՍպասում ենք ձեզ! 😊"
        )

    elif query.data == "my_bookings":
        conn = sqlite3.connect("salon.db")
        cur = conn.cursor()
        cur.execute(
            "SELECT service, date, time FROM bookings WHERE user_id = ?",
            (query.from_user.id,)
        )
        rows = cur.fetchall()
        conn.close()

        if rows:
            text = "📋 Ձեր հերթերը:\n\n"
            for s, d, t in rows:
                text += f"• {d} ժ. {t}\n"
        else:
            text = "Դուք դեռ հերթ չունեք։"
        await query.edit_message_text(text)

def main():
    init_db()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.run_polling()

if __name__ == "__main__":
    main()
