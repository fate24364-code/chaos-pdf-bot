import os
import sqlite3
import logging
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_ID = 8481208591

logging.basicConfig(level=logging.INFO)

db = sqlite3.connect("novels.db", check_same_thread=False)
db.execute("""
CREATE TABLE IF NOT EXISTS novels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    file_id TEXT NOT NULL,
    channels TEXT DEFAULT ''
)
""")
db.commit()


def is_admin(user_id):
    return user_id == ADMIN_ID


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args and context.args[0].startswith("novel_"):
        novel_id = context.args[0].replace("novel_", "", 1)
        await send_novel(update, context, novel_id)
        return

    keyboard = [
        [InlineKeyboardButton("📚 فهرست رمان‌ها", callback_data="list")]
    ]

    if is_admin(update.effective_user.id):
        keyboard.append([
            InlineKeyboardButton("⚙️ پنل مدیریت", callback_data="admin")
        ])

    await update.message.reply_text(
        "سلام! 📚\nبه ربات دریافت فایل رمان خوش اومدی.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def send_novel(update, context, novel_id):
    row = db.execute(
        "SELECT id, title, file_id, channels FROM novels WHERE id=?",
        (novel_id,),
    ).fetchone()

    if not row:
        if update.callback_query:
            await update.callback_query.answer("رمان پیدا نشد.", show_alert=True)
        else:
            await update.effective_message.reply_text("رمان پیدا نشد.")
        return

    _, title, file_id, channels_text = row
    channels = [c.strip() for c in channels_text.split(",") if c.strip()]

    if channels:
        buttons = [
            [InlineKeyboardButton("📢 عضویت در کانال", url=channel_url(c))]
            for c in channels
        ]
        buttons.append([
            InlineKeyboardButton(
                "✅ عضو شدم؛ بررسی کن",
                callback_data=f"check_{novel_id}",
            )
        ])

        text = f"برای دریافت «{title}» اول در کانال‌های زیر عضو شو."
        if update.callback_query:
            await update.callback_query.message.reply_text(
                text, reply_markup=InlineKeyboardMarkup(buttons)
            )
        else:
            await update.effective_message.reply_text(
                text, reply_markup=InlineKeyboardMarkup(buttons)
            )
    else:
        await context.bot.send_document(
            chat_id=update.effective_chat.id,
            document=file_id,
            caption=f"📚 {title}",
        )


def channel_url(channel):
    if channel.startswith("@"):
        return "https://t.me/" + channel[1:]
    return "https://t.me/" + channel


async def check_membership(update, context):
    query = update.callback_query
    await query.answer()

    novel_id = query.data.replace("check_", "", 1)
    row = db.execute(
        "SELECT title, file_id, channels FROM novels WHERE id=?",
        (novel_id,),
    ).fetchone()

    if not row:
        await query.message.reply_text("رمان پیدا نشد.")
        return

    title, file_id, channels_text = row
    channels = [c.strip() for c in channels_text.split(",") if c.strip()]

    for channel in channels:
        try:
            member = await context.bot.get_chat_member(
                chat_id=channel,
                user_id=query.from_user.id,
            )
            if member.status in ("left", "kicked"):
                await query.message.reply_text(
                    f"هنوز عضو {channel} نشدی؛ بعد از عضویت دوباره بررسی کن."
                )
                return
        except Exception:
            await query.message.reply_text(
                "بررسی عضویت انجام نشد. مدیر باید ربات را در کانال‌ها ادمین کند."
            )
            return

    await context.bot.send_document(
        chat_id=query.message.chat_id,
        document=file_id,
        caption=f"📚 {title}",
    )


async def show_list(update, context):
    query = update.callback_query
    await query.answer()

    rows = db.execute("SELECT id, title FROM novels ORDER BY id DESC").fetchall()
    if not rows:
        await query.message.reply_text("هنوز رمانی اضافه نشده.")
        return

    buttons = [
        [InlineKeyboardButton(title, callback_data=f"novel_{novel_id}")]
        for novel_id, title in rows
    ]
    await query.message.reply_text(
        "📚 رمان موردنظرت رو انتخاب کن:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def admin_panel(update, context):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        await query.message.reply_text("اجازه دسترسی نداری.")
        return

    buttons = [
        [InlineKeyboardButton("➕ افزودن رمان", callback_data="add")],
        [InlineKeyboardButton("📚 فهرست رمان‌ها", callback_data="list")],
    ]
    await query.message.reply_text(
        "⚙️ پنل مدیریت",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def add_novel(update, context):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        await query.message.reply_text("اجازه دسترسی نداری.")
        return

    context.user_data["adding_novel"] = "title"
    await query.message.reply_text(
        "اسم رمان رو بفرست. بعد فایل PDF و کانال‌های اجباری رو می‌گیریم."
    )


async def handle_admin_message(update, context):
    if not is_admin(update.effective_user.id):
        return

    stage = context.user_data.get("adding_novel")

    if stage == "title":
        context.user_data["novel_title"] = update.message.text
        context.user_data["adding_novel"] = "pdf"
        await update.message.reply_text("حالا فایل PDF رمان رو به‌صورت فایل بفرست.")
        return

    if stage == "pdf" and update.message.document:
        document = update.message.document
        if document.mime_type != "application/pdf":
            await update.message.reply_text("لطفاً فایل PDF بفرست.")
            return

        context.user_data["novel_file_id"] = document.file_id
        context.user_data["adding_novel"] = "channels"
        await update.message.reply_text(
            "حالا شناسهٔ کانال‌های اجباری رو بفرست؛ هر کانال در یک خط.\n"
            "مثال:\n@channel_one\n@channel_two\n\n"
            "اگر عضویت اجباری نمی‌خوای، بنویس: ندارد"
        )
        return

    if stage == "channels":
        channels_text = update.message.text.strip()
        if channels_text == "ندارد":
            channels_text = ""

        channels = [
            line.strip() for line in channels_text.splitlines()
            if line.strip()
        ]

        db.execute(
            "INSERT INTO novels (title, file_id, channels) VALUES (?, ?, ?)",
            (
                context.user_data["novel_title"],
                context.user_data["novel_file_id"],
                ",".join(channels),
            ),
        )
        db.commit()
        context.user_data.clear()
        await update.message.reply_text("✅ رمان ذخیره شد!")
        return


async def buttons(update, context):
    query = update.callback_query

    if query.data == "list":
        await show_list(update, context)
    elif query.data == "admin":
        await admin_panel(update, context)
    elif query.data == "add":
        await add_novel(update, context)
    elif query.data.startswith("check_"):
        await check_membership(update, context)
    elif query.data.startswith("novel_"):
        await send_novel(update, context, query.data.replace("novel_", "", 1))


def main():
    if not TOKEN:
        raise RuntimeError("متغیر محرمانه BOT_TOKEN تنظیم نشده است.")

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(MessageHandler(filters.ALL, handle_admin_message))
    app.run_polling()


if __name__ == "__main__":
    main()
