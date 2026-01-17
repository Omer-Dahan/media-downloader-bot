import logging
import os
import re
import threading
import time
import typing
from io import BytesIO
from typing import Any

import psutil
import pyrogram.errors
import yt_dlp
from apscheduler.schedulers.background import BackgroundScheduler
from pyrogram import Client, enums, filters, types

from config import (
    APP_HASH,
    APP_ID,
    ARCHIVE_CHANNEL,
    AUTHORIZED_USER,
    BOT_TOKEN,
    ENABLE_ARIA2,
    ENABLE_FFMPEG,
    M3U8_SUPPORT,
    ENABLE_VIP,
    OWNER,
    PROVIDER_TOKEN,
    TOKEN_PRICE,
    BotText,
)
from database.model import (
    add_paid_quota,
    credit_account,
    get_format_settings,
    get_free_quota,
    get_paid_quota,
    get_quality_settings,
    get_subtitles_settings,
    get_title_length_settings,
    init_user,
    reset_free,
    set_user_settings,
)
from engine import direct_entrance, youtube_entrance, youtube_entrance_with_quality, get_youtube_video_info, special_download_entrance
from engine.base import cancellation_events, _resume_state_cache
from engine.generic import check_and_send_update_notification
from utils import extract_url_and_name, sizeof_fmt, timeof_fmt, is_youtube
from admin import admin_panel_command, admin_callback_handler, admin_text_handler, _admin_state

# Temporary storage for YouTube URLs (maps hash to URL)
_youtube_url_cache: dict[str, str] = {}

logging.info("Authorized users are %s", AUTHORIZED_USER)
logging.getLogger("apscheduler.executors.default").propagate = False


def create_app(name: str, workers: int = 64) -> Client:
    return Client(
        name,
        APP_ID,
        APP_HASH,
        bot_token=BOT_TOKEN,
        workers=workers,
        # max_concurrent_transmissions=max(1, WORKERS // 2),
        # https://github.com/pyrogram/pyrogram/issues/1225#issuecomment-1446595489
    )


app = create_app("main")


def report_error_to_archive(client: Client, user: types.User, url: str, error: Exception | str):
    if not ARCHIVE_CHANNEL:
        return
    
    try:
        user_display = str(user.id)
        if user:
            name = user.first_name or ""
            if user.username:
                name = f"{name} @{user.username}".strip()
            if name:
                user_display = name
        
        caption = (
            f"❌ **דיווח שגיאה**\n"
            f"👤 משתמש: {user_display}\n"
            f"🆔 {user.id}\n"
            f"🔗 קישור: {url}\n"
            f"⚠️ שגיאה: {str(error)}"
        )
        
        client.send_message(
            chat_id=ARCHIVE_CHANNEL,
            text=caption,
            disable_web_page_preview=True
        )
    except Exception as e:
        logging.error("Failed to report error to archive channel: %s", e)


# Register admin panel handlers
@app.on_message(filters.command(["adminpanel"]))
def adminpanel_handler(client: Client, message: types.Message):
    admin_panel_command(client, message)

@app.on_callback_query(filters.regex(r"^admin:"))
def admin_callback(client: Client, callback_query: types.CallbackQuery):
    admin_callback_handler(client, callback_query)


def private_use(func):
    def wrapper(client: Client, message: types.Message):
        chat_id = getattr(message.from_user, "id", None)

        # message type check
        if message.chat.type != enums.ChatType.PRIVATE and not getattr(message, "text", "").lower().startswith("/ytdl"):
            logging.debug("%s, it's annoying me...🙄️ ", message.text)
            return

        # authorized users check
        if AUTHORIZED_USER:
            users = [int(i) for i in AUTHORIZED_USER.split(",")]
        else:
            users = []

        if users and chat_id and chat_id not in users:
            message.reply_text("הבוט הזה פרטי ולא זמין עבורך.", quote=True)
            return

        return func(client, message)

    return wrapper


@app.on_message(filters.command(["start"]))
def start_handler(client: Client, message: types.Message):
    from_id = message.chat.id
    user = message.from_user
    init_user(from_id, first_name=user.first_name if user else None, username=user.username if user else None)
    logging.info("%s welcome to youtube-dl bot!", message.from_user.id)
    client.send_chat_action(from_id, enums.ChatAction.TYPING)
    # Use ReplyKeyboardRemove to clear any old keyboard from previous bot versions
    client.send_message(
        from_id,
        BotText.start,
        disable_web_page_preview=True,
        reply_markup=types.ReplyKeyboardRemove(),
    )


@app.on_message(filters.command(["help"]))
def help_handler(client: Client, message: types.Message):
    chat_id = message.chat.id
    init_user(chat_id)
    client.send_chat_action(chat_id, enums.ChatAction.TYPING)
    markup = types.InlineKeyboardMarkup(
        [[types.InlineKeyboardButton("לצ'אט איתי 💬", url="https://t.me/YD_IL")]]
    )
    client.send_message(chat_id, BotText.help, disable_web_page_preview=True, reply_markup=markup)


@app.on_message(filters.command(["about"]))
def about_handler(client: Client, message: types.Message):
    chat_id = message.chat.id
    init_user(chat_id)
    client.send_chat_action(chat_id, enums.ChatAction.TYPING)
    client.send_message(chat_id, BotText.about)


@app.on_message(filters.command(["ping"]))
def ping_handler(client: Client, message: types.Message):
    chat_id = message.chat.id
    init_user(chat_id)
    client.send_chat_action(chat_id, enums.ChatAction.TYPING)

    def send_message_and_measure_ping():
        start_time = int(round(time.time() * 1000))
        reply: types.Message | typing.Any = client.send_message(chat_id, "בודק פינג...")

        end_time = int(round(time.time() * 1000))
        ping_time = int(round(end_time - start_time))
        message_sent = True
        if message_sent:
            message.reply_text(f"פינג: {ping_time:.2f} מילישניות", quote=True)
        time.sleep(0.5)
        client.edit_message_text(chat_id=reply.chat.id, message_id=reply.id, text="בדיקת הפינג הושלמה.")
        time.sleep(1)
        client.delete_messages(chat_id=reply.chat.id, message_ids=reply.id)

    thread = threading.Thread(target=send_message_and_measure_ping)
    thread.start()


@app.on_message(filters.command(["buy"]))
def buy(client: Client, message: types.Message):
    buy_text = """😊 לפני שממשיכים,
לכל משתמש יש מכסת הורדות יומית כדי שהבוט יישאר מהיר וזמין לכולם.
רוצים להוריד יותר?
שלחו לי הודעה פרטית ואפתח לכם גישה מורחבת בתשלום קטן. 🚀💬"""
    
    markup = types.InlineKeyboardMarkup(
        [
            [types.InlineKeyboardButton("לצ'אט איתי 💬", url="https://t.me/YD_IL")],
        ]
    )
    message.reply_text(buy_text, reply_markup=markup)


@app.on_callback_query(filters.regex(r"buy.*"))
def send_invoice(client: Client, callback_query: types.CallbackQuery):
    chat_id = callback_query.message.chat.id
    data = callback_query.data
    _, count, price = data.split("-")
    price = int(float(price) * 100)
    client.send_invoice(
        chat_id,
        f"{count} קרדיטים להורדות",
        "אנא בצע תשלום דרך Stripe",
        f"{count}",
        "USD",
        [types.LabeledPrice(label="VIP", amount=price)],
        provider_token=os.getenv("PROVIDER_TOKEN"),
        protect_content=True,
        start_parameter="no-forward-placeholder",
    )


@app.on_pre_checkout_query()
def pre_checkout(client: Client, query: types.PreCheckoutQuery):
    client.answer_pre_checkout_query(query.id, ok=True)


@app.on_message(filters.successful_payment)
def successful_payment(client: Client, message: types.Message):
    who = message.chat.id
    amount = message.successful_payment.total_amount  # in cents
    quota = int(message.successful_payment.invoice_payload)
    ch = message.successful_payment.provider_payment_charge_id
    free, paid = credit_account(who, amount, quota, ch)
    if paid > 0:
        message.reply_text(f"התשלום בוצע בהצלחה! יש לך {free} קרדיטים חינמיים ו-{paid} קרדיטים בתשלום.")
    else:
        message.reply_text("משהו השתבש. אנא פנה למנהל.")
    message.delete()


@app.on_message(filters.command(["stats"]))
def stats_handler(client: Client, message: types.Message):
    chat_id = message.chat.id
    init_user(chat_id)
    client.send_chat_action(chat_id, enums.ChatAction.TYPING)

    def safe(func, *args):
        try:
            return func(*args)
        except Exception:
            return None

    cpu_usage = safe(psutil.cpu_percent)
    disk_usage = safe(psutil.disk_usage, "/")
    swap = safe(psutil.swap_memory)
    memory = safe(psutil.virtual_memory)
    net_io = safe(psutil.net_io_counters)
    boot_time = safe(psutil.boot_time)

    # CPU
    cpu_str = f"{cpu_usage}%" if cpu_usage is not None else "N/A"

    # Disk
    if disk_usage:
        total, used, free, disk_percent = disk_usage
        total_str = sizeof_fmt(total)
        used_str = sizeof_fmt(used)
        free_str = sizeof_fmt(free)
        disk_percent_str = f"{disk_percent}%"
    else:
        total_str = used_str = free_str = disk_percent_str = "N/A"

    # Memory
    if memory:
        mem_total = sizeof_fmt(memory.total)
        mem_free = sizeof_fmt(memory.available)
        mem_used = sizeof_fmt(memory.used)
        mem_percent = f"{memory.percent}%"
    else:
        mem_total = mem_free = mem_used = mem_percent = "N/A"

    # Swap
    if swap:
        swap_total = sizeof_fmt(swap.total)
        swap_percent = f"{swap.percent}%"
    else:
        swap_total = swap_percent = "N/A"

    # Net IO
    if net_io:
        sent = sizeof_fmt(net_io.bytes_sent)
        recv = sizeof_fmt(net_io.bytes_recv)
    else:
        sent = recv = "N/A"

    # Uptime
    bot_uptime = timeof_fmt(time.time() - botStartTime)
    os_uptime = timeof_fmt(time.time() - boot_time) if boot_time else "N/A"

    # Cores
    try:
        p_cores = psutil.cpu_count(logical=False) or "N/A"
        t_cores = psutil.cpu_count(logical=True) or "N/A"
    except Exception:
        p_cores = t_cores = "N/A"

    owner_stats = (
        "\n\n⌬─────「 סטטיסטיקות 」─────⌬\n\n"
        f"<b>╭🖥️ **שימוש במעבד »**</b>  __{cpu_str}__\n"
        f"<b>├💾 **שימוש בזיכרון »**</b>  __{mem_percent}__\n"
        f"<b>╰🗃️ **שימוש בדיסק »**</b>  __{disk_percent_str}__\n\n"
        f"<b>╭📤העלאה:</b> {sent}\n"
        f"<b>╰📥הורדה:</b> {recv}\n\n\n"
        f"<b>סה״כ זיכרון:</b> {mem_total}\n"
        f"<b>זיכרון פנוי:</b> {mem_free}\n"
        f"<b>זיכרון בשימוש:</b> {mem_used}\n"
        f"<b>סה״כ SWAP:</b> {swap_total} | <b>שימוש ב-SWAP:</b> {swap_percent}\n\n"
        f"<b>סה״כ שטח דיסק:</b> {total_str}\n"
        f"<b>בשימוש:</b> {used_str} | <b>פנוי:</b> {free_str}\n\n"
        f"<b>ליבות פיזיות:</b> {p_cores}\n"
        f"<b>סה״כ ליבות:</b> {t_cores}\n\n"
        f"<b>🤖זמן פעילות הבוט:</b> {bot_uptime}\n"
        f"<b>⏲️זמן פעילות המערכת:</b> {os_uptime}\n"
    )

    user_stats = (
        "\n\n⌬─────「 סטטיסטיקות 」─────⌬\n\n"
        f"<b>╭🖥️ **שימוש במעבד »**</b>  __{cpu_str}__\n"
        f"<b>├💾 **שימוש בזיכרון »**</b>  __{mem_percent}__\n"
        f"<b>╰🗃️ **שימוש בדיסק »**</b>  __{disk_percent_str}__\n\n"
        f"<b>╭📤העלאה:</b> {sent}\n"
        f"<b>╰📥הורדה:</b> {recv}\n\n\n"
        f"<b>סה״כ זיכרון:</b> {mem_total}\n"
        f"<b>זיכרון פנוי:</b> {mem_free}\n"
        f"<b>זיכרון בשימוש:</b> {mem_used}\n"
        f"<b>סה״כ שטח דיסק:</b> {total_str}\n"
        f"<b>בשימוש:</b> {used_str} | <b>פנוי:</b> {free_str}\n\n"
        f"<b>🤖זמן פעילות הבוט:</b> {bot_uptime}\n"
    )

    if message.from_user.id in OWNER:
        message.reply_text(owner_stats, quote=True)
    else:
        message.reply_text(user_stats, quote=True)


@app.on_message(filters.command(["settings"]))
def settings_handler(client: Client, message: types.Message):
    chat_id = message.chat.id
    init_user(chat_id)
    client.send_chat_action(chat_id, enums.ChatAction.TYPING)
    
    markup = _build_settings_markup(chat_id)
    client.send_message(chat_id, BotText.settings, reply_markup=markup)


@app.on_message(filters.command(["direct"]))
def direct_download(client: Client, message: types.Message):
    chat_id = message.chat.id
    init_user(chat_id)
    client.send_chat_action(chat_id, enums.ChatAction.TYPING)
    message_text = message.text
    url, new_name = extract_url_and_name(message_text)
    logging.info("Direct download using aria2/requests start %s", url)
    if url is None or not re.findall(r"^https?://", url.lower()):
        message.reply_text("שלח לי קישור תקין.", quote=True)
        return
    bot_msg = message.reply_text("בקשת הורדה ישירה התקבלה.", quote=True)
    try:
        direct_entrance(client, bot_msg, url)
    except ValueError as e:
        report_error_to_archive(client, message.from_user, url, e)
        message.reply_text(e.__str__(), quote=True)
        bot_msg.delete()
        return


@app.on_message(filters.command(["spdl"]))
def spdl_handler(client: Client, message: types.Message):
    chat_id = message.chat.id
    init_user(chat_id)
    client.send_chat_action(chat_id, enums.ChatAction.TYPING)
    message_text = message.text
    url, new_name = extract_url_and_name(message_text)
    logging.info("spdl start %s", url)
    if url is None or not re.findall(r"^https?://", url.lower()):
        message.reply_text("משהו לא בסדר 🤔.\nבדוק את הקישור ושלח שוב.", quote=True)
        return
    bot_msg = message.reply_text("בקשת הורדה מיוחדת התקבלה.", quote=True)
    try:
        special_download_entrance(client, bot_msg, url)
    except ValueError as e:
        report_error_to_archive(client, message.from_user, url, e)
        message.reply_text(e.__str__(), quote=True)
        bot_msg.delete()
        return


@app.on_message(filters.command(["ytdl"]) & filters.group)
def ytdl_handler(client: Client, message: types.Message):
    # for group only
    init_user(message.from_user.id)
    client.send_chat_action(message.chat.id, enums.ChatAction.TYPING)
    message_text = message.text
    url, new_name = extract_url_and_name(message_text)
    logging.info("ytdl start %s", url)
    if url is None or not re.findall(r"^https?://", url.lower()):
        message.reply_text("בדוק את הקישור שלך.", quote=True)
        return

    bot_msg = message.reply_text("בקשת הורדה בקבוצה התקבלה.", quote=True)
    try:
        youtube_entrance(client, bot_msg, url)
    except ValueError as e:
        report_error_to_archive(client, message.from_user, url, e)
        message.reply_text(e.__str__(), quote=True)
        bot_msg.delete()
        return


def check_link(url: str, uid: int = None):
    ytdl = yt_dlp.YoutubeDL()
    if re.findall(r"^https://www\.youtube\.com/channel/", url) or "list" in url:
        # Check if user has paid quota - only paid users can download playlists
        if uid is not None:
            paid = get_paid_quota(uid)
            if paid and paid > 5:
                return None  # Allow playlist download for paid users
        # Return special marker for playlist/channel blocked - the handler will show button
        return "PLAYLIST_BLOCKED"

    if not M3U8_SUPPORT and (re.findall(r"m3u8|\.m3u8|\.m3u$", url.lower())):
        return "קישורי m3u8 מושבתים."


@app.on_message(filters.incoming & filters.text)
@private_use
def download_handler(client: Client, message: types.Message):
    chat_id = message.from_user.id
    user = message.from_user
    init_user(chat_id, first_name=user.first_name if user else None, username=user.username if user else None)
    text = message.text
    
    # Check if admin is waiting for input
    if chat_id in _admin_state:
        admin_text_handler(client, message)
        return
    
    # Extract URL from anywhere in the message
    if not text:
        return
    
    # Find URLs anywhere in the message text
    url_match = re.search(r"https?://[^\s<>\"']+", text)
    if not url_match:
        return
    
    url = url_match.group(0)
    # Clean up trailing punctuation that might have been captured
    url = url.rstrip(".,;:!?)")
    
    logging.info("Extracted URL from message: %s", url)
    
    client.send_chat_action(chat_id, enums.ChatAction.TYPING)
    logging.info("start %s", url)

    try:
        link_check_result = check_link(url, chat_id)
        
        # Handle playlist/channel blocked for non-paid users
        if link_check_result == "PLAYLIST_BLOCKED":
            markup = types.InlineKeyboardMarkup([
                [types.InlineKeyboardButton("💬 צור קשר לגישה מורחבת", url="https://t.me/YD_IL")]
            ])
            message.reply_text(
                "🎵 **הורדת פלייליסט או ערוץ**\n\n"
                "פיצ'ר זה זמין למשתמשים עם מנוי בלבד.\n"
                "רוצה גישה? צור איתי קשר! 👇",
                reply_markup=markup,
                quote=True
            )
            return
        elif link_check_result:
            # Other error messages (like m3u8 disabled)
            message.reply_text(link_check_result, quote=True)
            return
        
        # Check if this is a YouTube link - show quality selection menu
        if is_youtube(url):
            # Generate a short hash for the URL
            import hashlib
            url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
            _youtube_url_cache[url_hash] = url
            
            # Get video info
            video_info = get_youtube_video_info(url)
            if video_info:
                title = video_info.get('title', 'Unknown')
                duration = video_info.get('duration', '0:00')
            else:
                title = 'סרטון יוטיוב'
                duration = 'לא ידוע'
            
            # Build quality selection keyboard
            markup = types.InlineKeyboardMarkup(
                [
                    [  # First row - high quality
                        types.InlineKeyboardButton("🎬 1080p HD", callback_data=f"ytq:1080:{url_hash}"),
                        types.InlineKeyboardButton("🎬 720p", callback_data=f"ytq:720:{url_hash}"),
                    ],
                    [  # Second row - lower quality
                        types.InlineKeyboardButton("🎬 480p", callback_data=f"ytq:480:{url_hash}"),
                        types.InlineKeyboardButton("🎬 360p", callback_data=f"ytq:360:{url_hash}"),
                    ],
                    [  # Third row - audio only
                        types.InlineKeyboardButton("🎵 שמע בלבד", callback_data=f"ytq:audio:{url_hash}"),
                    ],
                ]
            )
            
            # Send quality selection message
            message.reply_text(
                BotText.youtube_quality_select.format(title, duration),
                reply_markup=markup,
                quote=True
            )
            return
        
        # Non-YouTube links - check for special downloaders first (Reddit, Instagram, etc.)
        bot_msg: types.Message | Any = message.reply_text("הקישור נקלט, מתחיל לעבוד עליו 📥", quote=True)
        client.send_chat_action(chat_id, enums.ChatAction.UPLOAD_VIDEO)
        
        # Try special download handlers first (Reddit, Instagram, PixelDrain, etc.)
        try:
            special_download_entrance(client, bot_msg, url)
        except ValueError as inner_e:
            # No special handler found, fall back to yt-dlp
            if "לא נמצא מוריד" in str(inner_e):
                youtube_entrance(client, bot_msg, url)
            # Other ValueErrors are handled by the downloader itself
    except pyrogram.errors.Flood as e:
        report_error_to_archive(client, message.from_user, url, e)
        f = BytesIO()
        f.write(str(e).encode())
        f.write(b"\xd7\x94\xd7\x91\xd7\xa7\xd7\xa9\xd7\x94 \xd7\xa9\xd7\x9c\xd7\x9a \xd7\x91\xd7\x98\xd7\x99\xd7\xa4\xd7\x95\xd7\x9c. \xd7\x90\xd7\xa0\xd7\x90 \xd7\x94\xd7\x9e\xd7\xaa\xd7\x9f \xd7\x91\xd7\xa1\xd7\x91\xd7\x9c\xd7\xa0\xd7\x95\xd7\xaa.")
        f.name = "אנא המתן.txt"
        message.reply_document(f, caption=f"המתנת הצפה! אנא המתן {e} שניות...", quote=True)
        f.close()
        client.send_message(OWNER, f"המתנת הצפה! 🙁 {e} שניות....")
        time.sleep(e.value)
    except ValueError as e:
        report_error_to_archive(client, message.from_user, url, e)
        message.reply_text(e.__str__(), quote=True)
    except Exception as e:
        report_error_to_archive(client, message.from_user, url, e)
        logging.error("Download failed", exc_info=True)
        message.reply_text(f"❌ ההורדה נכשלה: {e}", quote=True)


def _build_settings_markup(chat_id):
    """Build toggle-style settings keyboard with current user settings."""
    # Get current settings
    quality = get_quality_settings(chat_id)  # returns 'high', 'medium', 'low'
    send_format = get_format_settings(chat_id)  # returns 'video', 'document', 'audio'
    subtitles_enabled = get_subtitles_settings(chat_id)  # returns True/False
    title_length = get_title_length_settings(chat_id)  # returns 100, 250, 500, 1000
    
    # Quality display mapping
    quality_display = {
        'high': '1080p',
        'medium': '720p',
        'low': '480p'
    }
    
    # Format display mapping
    format_display = {
        'video': 'וידאו',
        'document': 'קובץ',
        'audio': 'שמע'
    }
    
    # Build toggle buttons - each shows current state
    quality_btn = types.InlineKeyboardButton(
        f"🎥 איכות: {quality_display.get(quality, '1080p')}",
        callback_data="toggle_quality"
    )
    
    format_btn = types.InlineKeyboardButton(
        f"📤 שליחה: {format_display.get(send_format, 'וידאו')}",
        callback_data="toggle_format"
    )
    
    subtitles_btn = types.InlineKeyboardButton(
        f"📝 כתוביות: {'פעיל' if subtitles_enabled else 'כבוי'}",
        callback_data="toggle_subtitles"
    )
    
    title_btn = types.InlineKeyboardButton(
        f"📑 אורך כותרת: {title_length}",
        callback_data="toggle_title_len"
    )
    
    return types.InlineKeyboardMarkup(
        [
            [quality_btn],
            [format_btn],
            [subtitles_btn],
            [title_btn],
        ]
    )


@app.on_callback_query(filters.regex(r"^toggle_quality$"))
def toggle_quality_callback(client: Client, callback_query: types.CallbackQuery):
    """Toggle quality: 1080p → 720p → 480p → 1080p"""
    chat_id = callback_query.message.chat.id
    current = get_quality_settings(chat_id)
    
    # Cycle: high → medium → low → high
    cycle = {'high': 'medium', 'medium': 'low', 'low': 'high'}
    new_quality = cycle.get(current, 'high')
    
    display = {'high': '1080p', 'medium': '720p', 'low': '480p'}
    
    logging.info("Setting %s quality to %s", chat_id, new_quality)
    set_user_settings(chat_id, "quality", new_quality)
    callback_query.answer(f"✅ איכות: {display[new_quality]}")
    
    try:
        callback_query.message.edit_text(BotText.settings, reply_markup=_build_settings_markup(chat_id))
    except pyrogram.errors.MessageNotModified:
        pass


@app.on_callback_query(filters.regex(r"^toggle_format$"))
def toggle_format_callback(client: Client, callback_query: types.CallbackQuery):
    """Toggle format: וידאו ↔ קובץ"""
    chat_id = callback_query.message.chat.id
    current = get_format_settings(chat_id)
    
    # Toggle: video ↔ document
    new_format = 'document' if current == 'video' else 'video'
    display = {'video': 'וידאו', 'document': 'קובץ'}
    
    logging.info("Setting %s format to %s", chat_id, new_format)
    set_user_settings(chat_id, "format", new_format)
    callback_query.answer(f"✅ שליחה: {display[new_format]}")
    
    try:
        callback_query.message.edit_text(BotText.settings, reply_markup=_build_settings_markup(chat_id))
    except pyrogram.errors.MessageNotModified:
        pass


@app.on_callback_query(filters.regex(r"^toggle_subtitles$"))
def toggle_subtitles_callback(client: Client, callback_query: types.CallbackQuery):
    """Toggle subtitles: פעיל ↔ כבוי"""
    chat_id = callback_query.message.chat.id
    current = get_subtitles_settings(chat_id)
    
    # Toggle on/off
    new_value = 0 if current else 1
    
    logging.info("Setting %s subtitles to %s", chat_id, new_value)
    set_user_settings(chat_id, "subtitles", new_value)
    
    if new_value:
        callback_query.answer("✅ כתוביות: פעיל")
    else:
        callback_query.answer("❌ כתוביות: כבוי")
    
    try:
        callback_query.message.edit_text(BotText.settings, reply_markup=_build_settings_markup(chat_id))
    except pyrogram.errors.MessageNotModified:
        pass


@app.on_callback_query(filters.regex(r"^toggle_title_len$"))
def toggle_title_length_callback(client: Client, callback_query: types.CallbackQuery):
    """Toggle title length: 1000 → 500 → 250 → 100 → 1000"""
    chat_id = callback_query.message.chat.id
    current = get_title_length_settings(chat_id)
    
    # Cycle: 1000 → 500 → 250 → 100 → 1000
    cycle = {1000: 500, 500: 250, 250: 100, 100: 1000}
    new_length = cycle.get(current, 1000)
    
    logging.info("Setting %s title_length to %s", chat_id, new_length)
    set_user_settings(chat_id, "title_length", new_length)
    callback_query.answer(f"✅ אורך כותרת: {new_length} תווים")
    
    try:
        callback_query.message.edit_text(BotText.settings, reply_markup=_build_settings_markup(chat_id))
    except pyrogram.errors.MessageNotModified:
        pass


@app.on_callback_query(filters.regex(r"^ytq:"))
def youtube_quality_callback(client: Client, callback_query: types.CallbackQuery):
    """Handle YouTube quality selection callback."""
    chat_id = callback_query.message.chat.id
    data = callback_query.data
    
    # Parse callback data: ytq:quality:url_hash
    parts = data.split(":")
    if len(parts) != 3:
        callback_query.answer("❌ שגיאה בעיבוד הבקשה", show_alert=True)
        return
    
    _, quality, url_hash = parts
    
    # Get URL from cache
    url = _youtube_url_cache.get(url_hash)
    if not url:
        callback_query.answer("❌ הקישור פג תוקף, נא לשלוח שוב", show_alert=True)
        return
    
    # Remove from cache
    _youtube_url_cache.pop(url_hash, None)
    
    # Answer callback
    quality_names = {
        '1080': '1080p HD',
        '720': '720p',
        '480': '480p',
        '360': '360p',
        'audio': 'שמע בלבד'
    }
    if quality == 'audio':
        callback_query.answer("⏳ מתחיל להוריד שמע...")
    else:
        callback_query.answer(f"⏳ מתחיל הורדה באיכות {quality_names.get(quality, quality)}...")
    
    # Update the message to show download started
    try:
        if quality == 'audio':
            callback_query.message.edit_text("🔄 מוריד שמע...")
        else:
            callback_query.message.edit_text(f"🔄 מוריד באיכות {quality_names.get(quality, quality)}...")
    except Exception as e:
        logging.error("Failed to edit message: %s", e)
    
    # Start download with selected quality
    try:
        client.send_chat_action(chat_id, enums.ChatAction.UPLOAD_VIDEO)
        youtube_entrance_with_quality(client, callback_query.message, url, quality)
    except Exception as e:
        logging.error("Download failed", exc_info=True)
        callback_query.message.edit_text(f"❌ ההורדה נכשלה: {e}")


@app.on_callback_query(filters.regex(r"^cancel:"))
def cancel_callback(client: Client, callback_query: types.CallbackQuery):
    """Handle cancel button callback."""
    data = callback_query.data
    # data format: cancel:chat_id:message_id
    try:
        _, cid, mid = data.split(":")
    except ValueError:
        callback_query.answer("❌ שגיאה בזיהוי משימה לביטול", show_alert=True)
        return
    
    key = f"{cid}_{mid}"
    cancellation_events.add(key)
    
    callback_query.answer("🛑 מבטל...")


@app.on_callback_query(filters.regex(r"^resume:"))
def resume_callback(client: Client, callback_query: types.CallbackQuery):
    """טיפול בכפתור המשך הורדה."""
    data = callback_query.data
    
    # Parse callback data: resume:state_hash
    parts = data.split(":")
    if len(parts) != 2:
        callback_query.answer("❌ שגיאה בעיבוד הבקשה", show_alert=True)
        return
    
    _, state_hash = parts
    
    # Get resume state from cache
    resume_state = _resume_state_cache.pop(state_hash, None)
    if not resume_state:
        callback_query.answer("❌ הבקשה פגה תוקף, נא לשלוח שוב", show_alert=True)
        return
    
    url = resume_state.get("url")
    download_type = resume_state.get("download_type", "generic")
    quality = resume_state.get("quality")
    
    callback_query.answer("⏳ ממשיך הורדה...")
    
    try:
        callback_query.message.edit_text("🔄 ממשיך הורדה...")
    except Exception as e:
        logging.error("Failed to edit resume message: %s", e)
    
    try:
        chat_id = resume_state.get("chat_id")
        client.send_chat_action(chat_id, enums.ChatAction.UPLOAD_VIDEO)
        
        if download_type == "direct":
            direct_entrance(client, callback_query.message, url)
        elif download_type == "youtube":
            if quality and quality not in ['high', 'medium', 'low']:
                # Specific quality like '1080', '720', etc.
                youtube_entrance_with_quality(client, callback_query.message, url, quality)
            else:
                youtube_entrance(client, callback_query.message, url)
        else:
            # Try special handlers first, then fall back to yt-dlp
            try:
                special_download_entrance(client, callback_query.message, url)
            except ValueError as inner_e:
                if "לא נמצא מוריד" in str(inner_e):
                    youtube_entrance(client, callback_query.message, url)
    except Exception as e:
        logging.error("Resume download failed", exc_info=True)
        callback_query.message.edit_text(f"❌ המשך ההורדה נכשל: {e}")


if __name__ == "__main__":
    botStartTime = time.time()
    scheduler = BackgroundScheduler()
    scheduler.add_job(reset_free, "cron", hour=0, minute=0)
    scheduler.start()
    banner = f"""
▌ ▌         ▀▛▘     ▌       ▛▀▖              ▜            ▌
▝▞  ▞▀▖ ▌ ▌  ▌  ▌ ▌ ▛▀▖ ▞▀▖ ▌ ▌ ▞▀▖ ▌  ▌ ▛▀▖ ▐  ▞▀▖ ▝▀▖ ▞▀▌
 ▌  ▌ ▌ ▌ ▌  ▌  ▌ ▌ ▌ ▌ ▛▀  ▌ ▌ ▌ ▌ ▐▐▐  ▌ ▌ ▐  ▌ ▌ ▞▀▌ ▌ ▌
 ▘  ▝▀  ▝▀▘  ▘  ▝▀▘ ▀▀  ▝▀▘ ▀▀  ▝▀   ▘▘  ▘ ▘  ▘ ▝▀  ▝▀▘ ▝▀▘

By @BennyThink, VIP Mode: {ENABLE_VIP} 
    """
    print(banner)
    
    # Check if bot was restarted after yt-dlp update and send notification on startup
    @app.on_message(filters.command(["__startup_check__"]))
    def _dummy_startup_handler(client, message):
        pass  # Never actually called, just for registration
    
    # Use a thread to send the notification after a short delay
    def send_update_notification_on_startup():
        import time as t
        t.sleep(3)  # Wait for bot to fully connect
        try:
            check_and_send_update_notification(app)
        except Exception as e:
            logging.error("Failed to send update notification: %s", e)
    
    threading.Thread(target=send_update_notification_on_startup, daemon=True).start()
    
    app.run()
