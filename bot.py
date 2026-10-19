import os
import re
import sqlite3
import logging
from contextlib import closing

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

TOKEN = os.environ.get("BOT_TOKEN", "").strip()
ADMIN_ID = 8481208591
BOT_USERNAME = os.environ.get(
    "BOT_USERNAME", "ChaosPDFBot"
).strip().lstrip("@")
DB_PATH = os.environ.get("DB_PATH", "novels.db")


# پایگاه داده و ساختار قبلی آن حفظ می‌شود.
def init_db():
    with closing(sqlite3.connect(DB_PATH)) as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS novels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                file_id TEXT NOT NULL,
                channels TEXT DEFAULT ''
            )
        """)
        con.commit()


def rows():
    with closing(sqlite3.connect(DB_PATH)) as con:
        return con.execute(
            "SELECT id, title, file_id, channels "
            "FROM novels ORDER BY id DESC"
        ).fetchall()


def get_novel(nid):
    with closing(sqlite3.connect(DB_PATH)) as con:
        return con.execute(
            "SELECT id, title, file_id, channels "
            "FROM novels WHERE id=?",
            (nid,),
        ).fetchone()


def update_novel(nid, field, value):
    if field not in ("title", "file_id", "channels"):
        return

    with closing(sqlite3.connect(DB_PATH)) as con:
        con.execute(
            f"UPDATE novels SET {field}=? WHERE id=?",
            (value, nid),
        )
        con.commit()


def channel_entries(raw):
    """کانال عمومی: @username
    کانال خصوصی: -1001234567890 | https://t.me/+InviteCode
    """
    result = []

    for line in (raw or "").replace(",", "\n").splitlines():
        line = line.strip()

        if not line or line.startswith("#"):
            continue

        parts = [part.strip() for part in line.split("|", 1)]
        target = parts[0]
        invite = parts[1] if len(parts) > 1 else ""

        if target.startswith(("https://t.me/", "http://t.me/")):
            path = target.rstrip("/").split("/")[-1]

            if path.startswith("+") or path.startswith("joinchat/"):
                continue

            target = "@" + path.lstrip("@")

        if target.startswith("@"):
            username = target[1:]

            if re.fullmatch(r"[A-Za-z0-9_]{5,}", username):
                result.append({
                    "chat": target,
                    "url": f"https://t.me/{username}",
                    "label": "اول" if len(result) == 0 else ("دوم" if len(result) == 1 else str(len(result) + 1)),
                })

        elif re.fullmatch(r"-100\d+", target):
            url = (
                invite
                if invite.startswith(
                    ("https://t.me/", "http://t.me/")
                )
                else ""
            )

            result.append({
                "chat": target,
                "url": url,
                "label": "اول" if len(result) == 0 else ("دوم" if len(result) == 1 else str(len(result) + 1)),
            })

    return result


def pack_channels(raw):
    return "\n".join(
        line.strip()
        for line in (raw or "").replace(",", "\n").splitlines()
        if line.strip()
    )


def parse_saved_channels(raw):
    return channel_entries(raw)


def is_admin(update):
    return bool(
        update.effective_user
        and update.effective_user.id == ADMIN_ID
    )


def admin_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ افزودن رمان", callback_data="add")],
        [InlineKeyboardButton("📚 فهرست رمان‌ها", callback_data="list")],
        [InlineKeyboardButton("🗑️ حذف رمان", callback_data="delete_menu")],
        [InlineKeyboardButton("✏️ ویرایش رمان", callback_data="edit_menu")],
        [InlineKeyboardButton("🔗 ویرایش لینک", callback_data="links_menu")],
        [InlineKeyboardButton("📢 مدیریت کانال‌ها", callback_data="channels_menu")],
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args and context.args[0].startswith("novel_"):
        try:
            nid = int(context.args[0][6:])
        except ValueError:
            await update.effective_message.reply_text(
                "لینک دریافت رمان معتبر نیست."
            )
            return

        await send_novel(update, context, nid)
        return

    if is_admin(update):
        await update.effective_message.reply_text(
            "پنل مدیریت ربات رمان 📚",
            reply_markup=admin_keyboard(),
        )
    else:
        await update.effective_message.reply_text(
            "سلام! برای دریافت رمان، لینک دریافت آن را باز کن."
        )


async def send_novel(update, context, nid):
    novel = get_novel(nid)
    msg = update.effective_message

    if not novel:
        await msg.reply_text("این رمان پیدا نشد یا حذف شده است.")
        return

    _, title, file_id, raw_channels = novel
    channels = parse_saved_channels(raw_channels)
    missing = []

        for channel in channels:
        try:
            member = await context.bot.get_chat_member(
                chat_id=channel["chat"],
                user_id=update.effective_user.id,
            )

            status = member.status

            if status in ("left", "kicked"):
                missing.append(channel)

            elif status == "restricted":
                if not getattr(member, "is_member", False):
                    missing.append(channel)

            elif status not in ("creator", "administrator", "member"):
                logging.warning(
                    "Unknown membership status for channel %s: %s",
                    channel["chat"],
                    status,
                )
                missing.append(channel)

        except Exception as exc:
            logging.exception(
                "Membership check failed for channel %s. "
                "User ID: %s. Error: %s",
                channel["chat"],
                update.effective_user.id,
                exc,
            )
            # در صورت بروز خطا، رفتار قبلی حفظ می‌شود.
            missing.append(channel)

    if missing:
        buttons = []

        for channel in missing:
            if channel["url"]:
                buttons.append([
                    InlineKeyboardButton(
                        "📢 عضویت در کانال " + channel["label"],
                        url=channel["url"],
                    )
                ])

        buttons.append([
            InlineKeyboardButton(
                "✅ بررسی عضویت",
                callback_data=f"check_{nid}",
            )
        ])

        await msg.reply_text(
            "برای دریافت این رمان، اول در کانال‌های زیر عضو شو "
            "و بعد «بررسی عضویت» را بزن.",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return

    try:
        await msg.reply_document(
            document=file_id,
            caption=f"📚 {title}",
        )
    except Exception:
        logging.exception("Could not send novel file")
        await msg.reply_text(
            "ارسال فایل ناموفق بود. فایل PDF را از بخش "
            "ویرایش رمان دوباره ثبت کن."
        )


async def show_list(chat):
    novels = rows()

    if not novels:
        await chat.reply_text("هنوز رمانی ثبت نشده است.")
        return

    for nid, title, file_id, channels in novels:
        url = f"https://t.me/{BOT_USERNAME}?start=novel_{nid}"

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔗 لینک دریافت رمان",
                    url=url,
                )
            ],
            [
                InlineKeyboardButton(
                    "✏️ ویرایش",
                    callback_data=f"edit_{nid}",
                ),
                InlineKeyboardButton(
                    "🗑️ حذف",
                    callback_data=f"del_{nid}",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🔗 ویرایش لینک‌ها/کانال‌ها",
                    callback_data=f"links_{nid}",
                )
            ],
        ])

        await chat.reply_text(
            f"📚 {title}\n"
            f"شناسه: {nid}\n"
            f"لینک دریافت:\n{url}",
            reply_markup=keyboard,
        )


async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""

    # بررسی عضویت برای کاربران عادی هم مجاز است.
    if data.startswith("check_"):
        try:
            nid = int(data[len("check_"):])
        except ValueError:
            await query.message.reply_text("شناسه رمان معتبر نیست.")
            return

        await send_novel(update, context, nid)
        return

    if not is_admin(update):
        await query.message.reply_text(
            "این بخش فقط برای مدیر ربات است."
        )
        return

    if data == "panel":
        await query.message.reply_text(
            "پنل مدیریت ربات رمان 📚",
            reply_markup=admin_keyboard(),
        )

    elif data == "add":
        context.user_data.clear()
        context.user_data["action"] = "add_title"
        await query.message.reply_text("اسم رمان را بفرست:")

    elif data == "list":
        await show_list(query.message)

    elif data == "delete_menu":
        novels = rows()

        if not novels:
            await query.message.reply_text(
                "رمانی برای حذف وجود ندارد."
            )
            return

        keyboard = [
            [
                InlineKeyboardButton(
                    f"🗑️ {title} (#{nid})",
                    callback_data=f"del_{nid}",
                )
            ]
            for nid, title, _, _ in novels
        ]

        await query.message.reply_text(
            "رمانی را برای حذف انتخاب کن:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif data.startswith("confirmdel_"):
        try:
            nid = int(data[len("confirmdel_"):])
        except ValueError:
            return

        with closing(sqlite3.connect(DB_PATH)) as con:
            con.execute(
                "DELETE FROM novels WHERE id=?",
                (nid,),
            )
            con.commit()

        await query.message.reply_text(
            "رمان از فهرست ربات حذف شد. فایل اصلی تلگرام پاک نمی‌شود.",
            reply_markup=admin_keyboard(),
        )

    elif data.startswith("del_"):
        try:
            nid = int(data[len("del_"):])
        except ValueError:
            return

        novel = get_novel(nid)

        if not novel:
            await query.message.reply_text("رمان پیدا نشد.")
            return

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "بله، حذف شود",
                    callback_data=f"confirmdel_{nid}",
                ),
                InlineKeyboardButton(
                    "لغو",
                    callback_data="panel",
                ),
            ]
        ])

        await query.message.reply_text(
            f"رمان «{novel[1]}» حذف شود؟ "
            "فایل اصلی تلگرام پاک نمی‌شود.",
            reply_markup=keyboard,
        )

    elif data == "edit_menu":
        novels = rows()

        if not novels:
            await query.message.reply_text(
                "رمانی برای ویرایش وجود ندارد."
            )
            return

        keyboard = [
            [
                InlineKeyboardButton(
                    f"✏️ {title} (#{nid})",
                    callback_data=f"edit_{nid}",
                )
            ]
            for nid, title, _, _ in novels
        ]

        await query.message.reply_text(
            "رمان را انتخاب کن:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif data.startswith("edit_") and data[len("edit_"):].isdigit():
        nid = int(data[len("edit_"):])
        novel = get_novel(nid)

        if not novel:
            await query.message.reply_text("رمان پیدا نشد.")
            return

        await query.message.reply_text(
            f"ویرایش «{novel[1]}» — کدام بخش؟",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "عنوان",
                        callback_data=f"field_title_{nid}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "فایل PDF",
                        callback_data=f"field_file_{nid}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "کانال‌های اجباری",
                        callback_data=f"field_channels_{nid}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🔗 نمایش لینک دریافت",
                        callback_data=f"links_{nid}",
                    )
                ],
            ]),
        )

    elif data.startswith("field_title_"):
        nid = int(data[len("field_title_"):])
        context.user_data.clear()
        context.user_data.update(
            action="edit_title",
            nid=nid,
        )
        await query.message.reply_text(
            "عنوان جدید رمان را بفرست:"
        )

    elif data.startswith("field_file_"):
        nid = int(data[len("field_file_"):])
        context.user_data.clear()
        context.user_data.update(
            action="edit_file",
            nid=nid,
        )
        await query.message.reply_text(
            "فایل PDF جدید را به صورت Document بفرست:"
        )

    elif data.startswith("field_channels_"):
        nid = int(data[len("field_channels_"):])

        context.user_data.clear()
        context.user_data.update(
            action="edit_channels",
            nid=nid,
        )

        await query.message.reply_text(
            "کانال‌های اجباری را هر کدام در یک خط بفرست.\n"
            "کانال عمومی: @username\n"
            "کانال خصوصی: -1001234567890 | https://t.me/+InviteCode\n"
            "برای حذف همه کانال‌ها بنویس: بدون"
        )

    elif data == "links_menu":
        novels = rows()

        if not novels:
            await query.message.reply_text("رمانی ثبت نشده است.")
            return

        keyboard = [
            [
                InlineKeyboardButton(
                    f"🔗 {title} (#{nid})",
                    callback_data=f"links_{nid}",
                )
            ]
            for nid, title, _, _ in novels
        ]

        await query.message.reply_text(
            "رمان را انتخاب کن تا لینک دریافت و تنظیمات کانال‌هایش را ببینی:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif data.startswith("links_"):
        try:
            nid = int(data[len("links_"):])
        except ValueError:
            return

        novel = get_novel(nid)

        if not novel:
            await query.message.reply_text("رمان پیدا نشد.")
            return

        url = f"https://t.me/{BOT_USERNAME}?start=novel_{nid}"

        await query.message.reply_text(
            f"📚 {novel[1]}\n\n"
            f"🔗 لینک دریافت رمان:\n{url}\n\n"
            f"📢 کانال‌های ثبت‌شده:\n"
            f"{novel[3] or 'هیچ کانالی ثبت نشده'}",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "✏️ ویرایش کانال‌ها",
                        callback_data=f"field_channels_{nid}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "⬅️ پنل مدیریت",
                        callback_data="panel",
                    )
                ],
            ]),
        )

    elif data == "channels_menu":
        await query.message.reply_text(
            "برای مدیریت کانال‌های اجباری، وارد بخش «ویرایش رمان» "
            "شو و رمان موردنظر را انتخاب کن. سپس «کانال‌های اجباری» "
            "را ویرایش کن. این کار فقط تنظیمات رمان را تغییر می‌دهد، "
            "نه خود کانال تلگرام را.",
            reply_markup=admin_keyboard(),
        )


async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not is_admin(update):
        return

    action = context.user_data.get("action")

    if not action:
        return

    message = update.effective_message

    if action == "add_title":
        title = (message.text or "").strip()

        if not title:
            await message.reply_text("عنوان متنی بفرست:")
            return

        context.user_data["new_title"] = title
        context.user_data["action"] = "add_file"

        await message.reply_text(
            "حالا فایل PDF رمان را به صورت Document بفرست:"
        )

    elif action == "add_file":
        if not message.document:
            await message.reply_text(
                "لطفاً خود فایل PDF را به صورت Document بفرست."
            )
            return

        document = message.document
        filename = (document.file_name or "").lower()

        if (
            document.mime_type != "application/pdf"
            and not filename.endswith(".pdf")
        ):
            await message.reply_text(
                "این فایل احتمالاً PDF نیست؛ فایل PDF را بفرست."
            )
            return

        context.user_data["new_file"] = document.file_id
        context.user_data["action"] = "add_channels"

        await message.reply_text(
            "کانال‌های اجباری را هر کدام در یک خط بفرست.\n"
            "عمومی: @username\n"
            "خصوصی: -1001234567890 | https://t.me/+InviteCode\n"
            "اگر کانال اجباری نمی‌خواهی بنویس: بدون"
        )

    elif action == "add_channels":
        raw_text = (message.text or "").strip()

        raw = (
            ""
            if raw_text.lower() in (
                "بدون", "هیچ", "ندارد", "none", "no"
            )
            else pack_channels(raw_text)
        )

        title = context.user_data["new_title"]
        file_id = context.user_data["new_file"]

        with closing(sqlite3.connect(DB_PATH)) as con:
            cursor = con.execute(
                "INSERT INTO novels(title, file_id, channels) "
                "VALUES (?, ?, ?)",
                (title, file_id, raw),
            )
            nid = cursor.lastrowid
            con.commit()

        context.user_data.clear()
        url = f"https://t.me/{BOT_USERNAME}?start=novel_{nid}"

        await message.reply_text(
            f"✅ رمان ثبت شد!\n"
            f"📚 {title}\n"
            f"🔗 لینک دریافت رمان:\n{url}\n\n"
            "این لینک را می‌توانی در پست کانالت قرار بدهی.",
            reply_markup=admin_keyboard(),
        )

    elif action == "edit_title":
        value = (message.text or "").strip()

        if not value:
            await message.reply_text("عنوان متنی بفرست:")
            return

        update_novel(
            context.user_data["nid"],
            "title",
            value,
        )
        context.user_data.clear()

        await message.reply_text(
            "عنوان رمان ویرایش شد.",
            reply_markup=admin_keyboard(),
        )

    elif action == "edit_file":
        if not message.document:
            await message.reply_text(
                "فایل PDF را به صورت Document بفرست:"
            )
            return

        document = message.document
        filename = (document.file_name or "").lower()

        if (
            document.mime_type != "application/pdf"
            and not filename.endswith(".pdf")
        ):
            await message.reply_text(
                "لطفاً فایل PDF را بفرست."
            )
            return

        update_novel(
            context.user_data["nid"],
            "file_id",
            document.file_id,
        )
        context.user_data.clear()

        await message.reply_text(
            "فایل رمان به‌روزرسانی شد.",
            reply_markup=admin_keyboard(),
        )

    elif action == "edit_channels":
        raw_text = (message.text or "").strip()

        raw = (
            ""
            if raw_text.lower() in (
                "بدون", "هیچ", "ندارد", "none", "no"
            )
            else pack_channels(raw_text)
        )

        update_novel(
            context.user_data["nid"],
            "channels",
            raw,
        )
        context.user_data.clear()

        await message.reply_text(
            "کانال‌های اجباری به‌روزرسانی شد.",
            reply_markup=admin_keyboard(),
        )

    else:
        context.user_data.clear()
        await message.reply_text(
            "عملیات نامعتبر بود؛ دوباره از پنل مدیریت شروع کن.",
            reply_markup=admin_keyboard(),
        )


async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_admin(update):
        await update.effective_message.reply_text(
            "از دکمه‌های پنل مدیریت استفاده کن.",
            reply_markup=admin_keyboard(),
        )


def main():
    if not TOKEN:
        raise RuntimeError("متغیر BOT_TOKEN در تنظیمات محیطی تعریف نشده است.")

    init_db()
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", start))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.COMMAND, unknown_command))
    app.add_handler(
        MessageHandler(filters.TEXT | filters.Document.ALL, handle_message)
    )

    logging.info("ChaosPDFBot is starting...")
    app.run_polling()


if __name__ == "__main__":
    main()

            
