import os
import re
import sqlite3
import logging
from contextlib import closing
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

logging.basicConfig(level=logging.INFO)
TOKEN = os.environ.get('BOT_TOKEN', '').strip()
ADMIN_ID = 8481208591
BOT_USERNAME = os.environ.get('BOT_USERNAME', 'ChaosPDFBot').strip().lstrip('@')
DB_PATH = os.environ.get('DB_PATH', 'novels.db')

Keep the existing database and its table/columns compatible.

def init_db():
with closing(sqlite3.connect(DB_PATH)) as con:
con.execute('''CREATE TABLE IF NOT EXISTS novels (
id INTEGER PRIMARY KEY AUTOINCREMENT,
title TEXT NOT NULL,
file_id TEXT NOT NULL,
channels TEXT DEFAULT ''
)''')
con.commit()

def rows():
with closing(sqlite3.connect(DB_PATH)) as con:
return con.execute('SELECT id, title, file_id, channels FROM novels ORDER BY id DESC').fetchall()

def get_novel(nid):
with closing(sqlite3.connect(DB_PATH)) as con:
return con.execute('SELECT id, title, file_id, channels FROM novels WHERE id=?', (nid,)).fetchone()

def update_novel(nid, field, value):
if field not in ('title', 'file_id', 'channels'):
return
with closing(sqlite3.connect(DB_PATH)) as con:
con.execute(f'UPDATE novels SET {field}=? WHERE id=?', (value, nid))
con.commit()

def channel_entries(raw):
"""Each line: @publicchannel OR -1001234567890 | https://t.me/+invite"""
out=[]
for line in (raw or '').replace(',', '\n').splitlines():
line=line.strip()
if not line or line.startswith('#'):
continue
parts=[p.strip() for p in line.split('|', 1)]
target=parts[0]
invite=parts[1] if len(parts)>1 else ''
if target.startswith('https://t.me/') or target.startswith('http://t.me/'):
target='@'+target.rstrip('/').split('/')[-1].lstrip('@')
if target.startswith('@'):
username=target[1:]
if re.fullmatch(r'[A-Za-z0-9_]{5,}', username):
out.append({'chat': target, 'url': 'https://t.me/'+username, 'label': target})
elif re.fullmatch(r'-100\d+', target):
url=invite if invite.startswith(('https://t.me/', 'http://t.me/')) else ''
out.append({'chat': target, 'url': url, 'label': target})
return out

def pack_channels(raw):
# Preserve the admin-entered line format, including private invite links.
return '\n'.join(line.strip() for line in (raw or '').replace(',', '\n').splitlines() if line.strip())

def parse_saved_channels(raw):
return channel_entries(raw)

def is_admin(update):
return bool(update.effective_user and update.effective_user.id == ADMIN_ID)

def admin_keyboard():
return InlineKeyboardMarkup([
[InlineKeyboardButton('➕ افزودن رمان', callback_data='add')],
[InlineKeyboardButton('📚 فهرست رمان‌ها', callback_data='list')],
[InlineKeyboardButton('🗑️ حذف رمان', callback_data='delete_menu')],
[InlineKeyboardButton('✏️ ویرایش رمان', callback_data='edit_menu')],
[InlineKeyboardButton('🔗 ویرایش لینک', callback_data='links_menu')],
[InlineKeyboardButton('📢 مدیریت کانال‌ها', callback_data='channels_menu')],
])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
if context.args and context.args[0].startswith('novel_'):
try: nid=int(context.args[0][6:])
except ValueError:
await update.message.reply_text('لینک دریافت رمان معتبر نیست.'); return
await send_novel(update, context, nid)
return
if is_admin(update):
await update.message.reply_text('پنل مدیریت ربات رمان 📚', reply_markup=admin_keyboard())
else:
await update.message.reply_text('سلام! برای دریافت رمان، لینک دریافت آن را باز کن.')

async def send_novel(update, context, nid):
novel=get_novel(nid)
msg=update.effective_message
if not novel:
await msg.reply_text('این رمان پیدا نشد یا حذف شده است.'); return
, title, file_id, raw_channels=novel
channels=parse_saved_channels(raw_channels)
missing=[]
for ch in channels:
try:
member=await context.bot.get_chat_member(chat_id=ch['chat'], user_id=update.effective_user.id)
if member.status in ('left','kicked','banned'):
missing.append(ch)
except Exception as e:
logging.warning('Membership check failed for %s: %s', ch['chat'], e)
# Do not silently allow access if a required channel could not be checked.
missing.append(ch)
if missing:
buttons=[]
for ch in missing:
if ch['url']:
buttons.append([InlineKeyboardButton('عضویت در کانال '+ch['label'], url=ch['url'])])
buttons.append([InlineKeyboardButton('✅ بررسی عضویت', callback_data=f'check{nid}')])
await msg.reply_text('برای دریافت این رمان، اول در کانال‌های زیر عضو شو و بعد «بررسی عضویت» را بزن.', reply_markup=InlineKeyboardMarkup(buttons))
return
try:
await msg.reply_document(document=file_id, caption=f'📚 {title}')
except Exception:
logging.exception('Could not send novel file')
await msg.reply_text('ارسال فایل ناموفق بود. فایل PDF را از بخش ویرایش رمان دوباره ثبت کن.')

async def show_list(chat, edit=False):
novels=rows()
if not novels:
await chat.reply_text('هنوز رمانی ثبت نشده است.'); return
for nid,title,, in novels:
url=f'https://t.me/{BOT_USERNAME}?start=novel_{nid}'
kb=InlineKeyboardMarkup([
[InlineKeyboardButton('🔗 لینک دریافت رمان', url=url)],
[InlineKeyboardButton('✏️ ویرایش', callback_data=f'edit_{nid}'), InlineKeyboardButton('🗑️ حذف', callback_data=f'del_{nid}')],
[InlineKeyboardButton('🔗 ویرایش لینک‌ها/کانال‌ها', callback_data=f'links_{nid}')]
])
await chat.reply_text(f'📚 {title}\nشناسه: {nid}\nلینک دریافت: {url}', reply_markup=kb)

async def ask_text(update, context, key, prompt):
context.user_data['action']=key
await update.callback_query.message.reply_text(prompt)

async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
q=update.callback_query
await q.answer()
data=q.data or ''
if data.startswith('check_'):
try: nid=int(data.split('',1)[1])
except ValueError: return
await send_novel(update, context, nid); return
if not is_admin(update):
await q.message.reply_text('این بخش فقط برای مدیر ربات است.'); return
if data=='panel':
await q.message.reply_text('پنل مدیریت ربات رمان 📚', reply_markup=admin_keyboard())
elif data=='add':
context.user_data.clear(); context.user_data['action']='add_title'
await q.message.reply_text('اسم رمان را بفرست:')
elif data=='list':
await show_list(q.message)
elif data=='delete_menu':
novels=rows()
if not novels: await q.message.reply_text('رمانی برای حذف وجود ندارد.'); return
await q.message.reply_text('رمانی را برای حذف انتخاب کن:', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f'🗑️ {t} (#{i})',callback_data=f'del{i}')] for i,t,, in novels]))
elif data.startswith('del_'):
nid=int(data[4:]); n=get_novel(nid)
if not n: await q.message.reply_text('رمان پیدا نشد.'); return
await q.message.reply_text(f'رمان «{n[1]}» حذف شود؟ فایل اصلی تلگرام پاک نمی‌شود.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('بله، حذف شود',callback_data=f'confirmdel_{nid}'),InlineKeyboardButton('لغو',callback_data='panel')]]))
elif data.startswith('confirmdel_'):
nid=int(data[len('confirmdel_'):])
with closing(sqlite3.connect(DB_PATH)) as con:
con.execute('DELETE FROM novels WHERE id=?',(nid,)); con.commit()
await q.message.reply_text('رمان از فهرست ربات حذف شد.', reply_markup=admin_keyboard())
elif data=='edit_menu':
novels=rows()
if not novels: await q.message.reply_text('رمانی برای ویرایش وجود ندارد.'); return
await q.message.reply_text('رمان را انتخاب کن:',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f'✏️ {t} (#{i})',callback_data=f'edit_{i}')] for i,t,, in novels]))
elif data.startswith('edit_') and data[5:].isdigit():
nid=int(data[5:]); n=get_novel(nid)
if not n: await q.message.reply_text('رمان پیدا نشد.'); return
await q.message.reply_text(f'ویرایش «{n[1]}» — کدام بخش؟',reply_markup=InlineKeyboardMarkup([
[InlineKeyboardButton('عنوان',callback_data=f'field_title_{nid}')],
[InlineKeyboardButton('فایل PDF',callback_data=f'field_file_{nid}')],
[InlineKeyboardButton('کانال‌های اجباری',callback_data=f'field_channels_{nid}')],
[InlineKeyboardButton('🔗 نمایش لینک دریافت',callback_data=f'links_{nid}')],
]))
elif data.startswith('field_title_'):
nid=int(data[len('field_title_'):]); context.user_data.clear(); context.user_data.update(action='edit_title',nid=nid)
await q.message.reply_text('عنوان جدید رمان را بفرست:')
elif data.startswith('field_file_'):
nid=int(data[len('field_file_'):]); context.user_data.clear(); context.user_data.update(action='edit_file',nid=nid)
await q.message.reply_text('فایل PDF جدید را به صورت Document بفرست:')
elif data.startswith('field_channels_'):
nid=int(data[len('field_channels_'):]); context.user_data.clear(); context.user_data.update(action='edit_channels',nid=nid)
n=get_novel(nid)
await q.message.reply_text('کانال‌های اجباری را هر کدام در یک خط بفرست. برای کانال عمومی: @username\nبرای کانال خصوصی: -1001234567890 | https://t.me/+InviteCode\nبرای حذف همه کانال‌ها بنویس: بدون')
elif data=='links_menu':
novels=rows()
if not novels: await q.message.reply_text('رمانی ثبت نشده است.'); return
await q.message.reply_text('رمان را انتخاب کن تا لینک دریافت و تنظیمات کانال‌هایش را ببینی:',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f'🔗 {t} (#{i})',callback_data=f'links_{i}')] for i,t,, in novels]))
elif data.startswith('links_'):
nid=int(data[6:]); n=get_novel(nid)
if not n: await q.message.reply_text('رمان پیدا نشد.'); return
url=f'https://t.me/{BOT_USERNAME}?start=novel_{nid}'
await q.message.reply_text(f'📚 {n[1]}\n\n🔗 لینک دریافت رمان:\n{url}\n\n📢 کانال‌های ثبت‌شده:\n{n[3] or "هیچ کانالی ثبت نشده"}',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('✏️ ویرایش کانال‌ها',callback_data=f'field_channels_{nid}')],[InlineKeyboardButton('⬅️ پنل مدیریت',callback_data='panel')]]))
elif data=='channels_menu':
await q.message.reply_text('مدیریت کانال‌ها: برای دیدن و حذف کانال‌های اجباریِ یک رمان، رمان را از «ویرایش رمان» انتخاب کن و بخش «کانال‌های اجباری» را ویرایش کن. حذف کانال از اینجا به معنی حذف آن از تنظیمات رمان است، نه حذف کانال تلگرام.',reply_markup=admin_keyboard())

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
if not is_admin(update): return
action=context.user_data.get('action')
if not action: return
msg=update.effective_message
if action=='add_title':
title=(msg.text or '').strip()
if not title: await msg.reply_text('عنوان متنی بفرست:'); return
context.user_data['new_title']=title; context.user_data['action']='add_file'
await msg.reply_text('حالا فایل PDF رمان را به صورت Document بفرست:')
elif action=='add_file':
if not msg.document:
await msg.reply_text('لطفاً خود فایل PDF را به صورت Document بفرست.'); return
if msg.document.mime_type not in (None,'application/pdf') and not msg.document.file_name.lower().endswith('.pdf'):
await msg.reply_text('این فایل احتمالاً PDF نیست؛ فایل PDF را بفرست.'); return
context.user_data['new_file']=msg.document.file_id; context.user_data['action']='add_channels'
await msg.reply_text('کانال‌های اجباری را هر کدام در یک خط بفرست.\nعمومی: @username\nخصوصی: -1001234567890 | https://t.me/+InviteCode\nاگر کانال اجباری نمی‌خواهی بنویس: بدون')
elif action=='add_channels':
raw='' if (msg.text or '').strip().lower() in ('بدون','هیچ','ندارد','none','no') else pack_channels(msg.text or '')
title=context.user_data['new_title']; file_id=context.user_data['new_file']
with closing(sqlite3.connect(DB_PATH)) as con:
cur=con.execute('INSERT INTO novels(title,file_id,channels) VALUES(?,?,?)',(title,file_id,raw)); nid=cur.lastrowid; con.commit()
context.user_data.clear()
url=f'https://t.me/{BOT_USERNAME}?start=novel_{nid}'
await msg.reply_text(f'✅ رمان ثبت شد!\n📚 {title}\n🔗 لینک دریافت رمان:\n{url}\n\nاین لینک را می‌توانی در پست کانالت روی دکمه «دریافت فایل» بگذاری.',reply_markup=admin_keyboard())
elif action=='edit_title':
val=(msg.text or '').strip()
if not val: await msg.reply_text('عنوان متنی بفرست:'); return
update_novel(context.user_data['nid'],'title',val); context.user_data.clear()
await msg.reply_text('عنوان رمان ویرایش شد.',reply_markup=admin_keyboard())
elif action=='edit_file':
if not msg.document: await msg.reply_text('فایل PDF را به صورت Document بفرست:'); return
update_novel(context.user_data['nid'],'file_id',msg.document.file_id); context.user_data.clear()
await msg.reply_text('فایل رمان به‌روزرسانی شد.',reply_markup=admin_keyboard())
elif action=='edit_channels':
raw='' if (msg.text or '').strip().lower() in ('بدون','هیچ','ندارد','none','no') else pack_channels(msg.text or '')
update_novel(context.user_data['nid'],'channels',raw); context.user_data.clear()
await msg.reply_text('کانال‌های اجباری به‌روزرسانی شدند.',reply_markup=admin_keyboard())

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
if update.effective_message and is_admin(update):
await update.effective_message.reply_text('برای باز کردن پنل مدیریت /start را بفرست.')

def main():
if not TOKEN:
raise RuntimeError('BOT_TOKEN environment variable is missing')
init_db()
app=Application.builder().token(TOKEN).build()
app.add_handler(CommandHandler('start',start))
app.add_handler(CallbackQueryHandler(callback))
app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND,handle_message))
app.run_polling(drop_pending_updates=False)

if name=='main':
main()
