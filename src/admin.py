import time
import logging
from pyrogram import Client, filters, types

from config import OWNER
from database.model import (
    add_paid_quota,
    get_all_users,
    get_paid_users,
    get_user_stats,
    get_download_stats,
    reset_user_quota,
    block_user,
    unblock_user,
    delete_user,
)


# State management for admin actions
_admin_state: dict[int, dict] = {}


def is_owner(user_id: int) -> bool:
    """Check if user is an owner"""
    return user_id in OWNER


def admin_panel_command(client: Client, message: types.Message):
    """Main admin panel command - /adminpanel"""
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        message.reply_text("❌ אין לך הרשאה לפקודה זו.", quote=True)
        return
    
    # Build admin panel keyboard
    markup = types.InlineKeyboardMarkup([
        [types.InlineKeyboardButton("🏓 פינג", callback_data="admin:ping")],
        [types.InlineKeyboardButton("📈 סטטיסטיקות שרת", callback_data="admin:server_stats")],
        [types.InlineKeyboardButton("📊 סטטיסטיקות הורדות", callback_data="admin:download_stats")],
        [types.InlineKeyboardButton("👥 רשימת משתמשים", callback_data="admin:users:0")],
        [types.InlineKeyboardButton("💳 משתמשים בתשלום", callback_data="admin:paid_users:0")],
        [types.InlineKeyboardButton("➕ הוסף קרדיטים", callback_data="admin:add_credits")],
        [types.InlineKeyboardButton("🔄 אפס מכסה", callback_data="admin:reset_quota")],
        [types.InlineKeyboardButton("🚫 חסום משתמש", callback_data="admin:block_user")],
    ])
    
    message.reply_text(
        "📊 **פאנל ניהול**\n\nבחר פעולה:",
        reply_markup=markup,
        quote=True
    )


def admin_callback_handler(client: Client, callback_query: types.CallbackQuery):
    """Handle all admin panel callbacks"""
    user_id = callback_query.from_user.id
    
    if not is_owner(user_id):
        callback_query.answer("❌ אין לך הרשאה", show_alert=True)
        return
    
    data = callback_query.data
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    
    if action == "ping":
        handle_ping(client, callback_query)
    elif action == "server_stats":
        handle_server_stats(client, callback_query)
    elif action == "download_stats":
        handle_download_stats(client, callback_query)
    elif action == "users":
        page = int(parts[2]) if len(parts) > 2 else 0
        handle_users_list(client, callback_query, page)
    elif action == "paid_users":
        page = int(parts[2]) if len(parts) > 2 else 0
        handle_paid_users_list(client, callback_query, page)
    elif action == "add_credits":
        handle_add_credits_prompt(client, callback_query)
    elif action == "reset_quota":
        handle_reset_quota_prompt(client, callback_query)
    elif action == "block_user":
        handle_block_user_prompt(client, callback_query)
    elif action == "user_action":
        target_user = int(parts[2]) if len(parts) > 2 else 0
        sub_action = parts[3] if len(parts) > 3 else ""
        handle_user_action(client, callback_query, target_user, sub_action)
    elif action == "back":
        handle_back_to_menu(client, callback_query)


def handle_ping(client: Client, callback_query: types.CallbackQuery):
    """Handle ping action"""
    start_time = time.time()
    callback_query.answer()
    end_time = time.time()
    ping_ms = (end_time - start_time) * 1000
    
    callback_query.message.edit_text(
        f"🏓 **פונג**\n\nזמן תגובה: `{ping_ms:.2f}` מילישניות",
        reply_markup=types.InlineKeyboardMarkup([
            [types.InlineKeyboardButton("🔙 חזרה", callback_data="admin:back")]
        ])
    )


def handle_server_stats(client: Client, callback_query: types.CallbackQuery):
    """Handle server stats - same as /stats but inline"""
    import psutil
    
    callback_query.answer("טוען...")
    
    def safe(func, *args):
        try:
            return func(*args)
        except Exception:
            return None
    
    def sizeof_fmt(num: int, suffix="B"):
        for unit in ["", "Ki", "Mi", "Gi", "Ti", "Pi", "Ei", "Zi"]:
            if abs(num) < 1024.0:
                return "%3.1f%s%s" % (num, unit, suffix)
            num /= 1024.0
        return "%.1f%s%s" % (num, "Yi", suffix)
    
    def timeof_fmt(seconds):
        periods = [("d", 86400), ("h", 3600), ("m", 60), ("s", 1)]
        result = ""
        for period_name, period_seconds in periods:
            if seconds >= period_seconds:
                period_value, seconds = divmod(seconds, period_seconds)
                result += f"{int(period_value)}{period_name}"
        return result
    
    try:
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
        import time as time_module
        os_uptime = timeof_fmt(time_module.time() - boot_time) if boot_time else "N/A"
        
        # Cores
        try:
            p_cores = psutil.cpu_count(logical=False) or "N/A"
            t_cores = psutil.cpu_count(logical=True) or "N/A"
        except Exception:
            p_cores = t_cores = "N/A"
        
        text = f"""📈 **סטטיסטיקות שרת**

╭🖥️ **מעבד:** {cpu_str}
├💾 **זיכרון:** {mem_percent}
╰🗃️ **דיסק:** {disk_percent_str}

╭📤 **העלאה:** {sent}
╰📥 **הורדה:** {recv}

**סה״כ זיכרון:** {mem_total}
**זיכרון פנוי:** {mem_free}
**זיכרון בשימוש:** {mem_used}
**SWAP:** {swap_total} | **שימוש:** {swap_percent}

**סה״כ דיסק:** {total_str}
**בשימוש:** {used_str} | **פנוי:** {free_str}

**ליבות פיזיות:** {p_cores}
**סה״כ ליבות:** {t_cores}

⏲️ **זמן פעילות מערכת:** {os_uptime}
"""
    except Exception as e:
        text = f"❌ שגיאה בקבלת סטטיסטיקות: {e}"
    
    try:
        callback_query.message.edit_text(
            text,
            reply_markup=types.InlineKeyboardMarkup([
                [types.InlineKeyboardButton("🔄 רענן", callback_data="admin:server_stats")],
                [types.InlineKeyboardButton("🔙 חזרה", callback_data="admin:back")]
            ])
        )
    except Exception:
        callback_query.answer("אין שינויים", show_alert=False)


def handle_download_stats(client: Client, callback_query: types.CallbackQuery):
    """Handle download statistics"""
    callback_query.answer("טוען...")
    
    stats = get_download_stats()
    
    text = f"""📊 **סטטיסטיקות הורדות**

👥 **סה"כ משתמשים:** {stats['total_users']}
💳 **משתמשים בתשלום:** {stats['paid_users']}
📥 **סה"כ הורדות (חינם נותרו):** {stats['total_free_remaining']}
💰 **סה"כ קרדיטים בתשלום:** {stats['total_paid']}
📊 **נפח היום:** {stats['total_bandwidth_used'] / (1024**3):.2f} GB
📈 **נפח כל הזמנים:** {stats['all_time_bandwidth'] / (1024**3):.2f} GB
"""
    
    try:
        callback_query.message.edit_text(
            text,
            reply_markup=types.InlineKeyboardMarkup([
                [types.InlineKeyboardButton("🔄 רענן", callback_data="admin:download_stats")],
                [types.InlineKeyboardButton("🔙 חזרה", callback_data="admin:back")]
            ])
        )
    except Exception:
        callback_query.answer("אין שינויים", show_alert=False)


def handle_users_list(client: Client, callback_query: types.CallbackQuery, page: int):
    """Handle users list with pagination"""
    callback_query.answer()
    
    users, total = get_all_users(page=page, per_page=10)
    total_pages = (total + 9) // 10
    
    if not users:
        text = "‏👥 **רשימת משתמשים**\n\nאין משתמשים."
    else:
        text = f"‏👥 **רשימת משתמשים** (עמוד {page + 1}/{total_pages})\n"
        text += "━━━━━━━━━━━━━━━━━━\n\n"
        for user in users:
            status = "🚫" if user.get('is_blocked') else "✅"
            paid_badge = " 💳" if user.get('paid', 0) > 0 else ""
            # Build name display
            name = user.get('first_name') or ""
            if user.get('username'):
                name = f"{name} @{user['username']}".strip()
            name_line = f"\n   ‏👤 {name}" if name else ""
            text += f"{status} `{user['user_id']}`{paid_badge}{name_line}\n"
            text += f"   ‏🆓 חינם: {user['free']} | 💰 בתשלום: {user['paid']}\n"
            text += "──────────────────\n"
    
    # Navigation buttons
    nav_buttons = []
    if page > 0:
        nav_buttons.append(types.InlineKeyboardButton("⬅️ הקודם", callback_data=f"admin:users:{page-1}"))
    if page < total_pages - 1:
        nav_buttons.append(types.InlineKeyboardButton("➡️ הבא", callback_data=f"admin:users:{page+1}"))
    
    keyboard = []
    if nav_buttons:
        keyboard.append(nav_buttons)
    keyboard.append([types.InlineKeyboardButton("🔙 חזרה", callback_data="admin:back")])
    
    try:
        callback_query.message.edit_text(text, reply_markup=types.InlineKeyboardMarkup(keyboard))
    except Exception:
        callback_query.answer("אין שינויים", show_alert=False)


def handle_paid_users_list(client: Client, callback_query: types.CallbackQuery, page: int):
    """Handle paid users list with pagination"""
    callback_query.answer()
    
    users, total = get_paid_users(page=page, per_page=10)
    total_pages = max(1, (total + 9) // 10)
    
    if not users:
        text = "‏💳 **משתמשים בתשלום**\n\nאין משתמשים בתשלום."
    else:
        text = f"‏💳 **משתמשים בתשלום** (עמוד {page + 1}/{total_pages})\n"
        text += "━━━━━━━━━━━━━━━━━━\n\n"
        for user in users:
            name = user.get('first_name') or ""
            if user.get('username'):
                name = f"{name} @{user['username']}".strip()
            name_line = f"\n   ‏👤 {name}" if name else ""
            text += f"💰 `{user['user_id']}`{name_line}\n"
            text += f"   ‏💵 {user['paid']} קרדיטים\n"
            text += "──────────────────\n"
    
    # Navigation buttons
    nav_buttons = []
    if page > 0:
        nav_buttons.append(types.InlineKeyboardButton("⬅️ הקודם", callback_data=f"admin:paid_users:{page-1}"))
    if page < total_pages - 1:
        nav_buttons.append(types.InlineKeyboardButton("➡️ הבא", callback_data=f"admin:paid_users:{page+1}"))
    
    keyboard = []
    if nav_buttons:
        keyboard.append(nav_buttons)
    keyboard.append([types.InlineKeyboardButton("🔙 חזרה", callback_data="admin:back")])
    
    callback_query.message.edit_text(text, reply_markup=types.InlineKeyboardMarkup(keyboard))


def handle_add_credits_prompt(client: Client, callback_query: types.CallbackQuery):
    """Prompt for adding credits"""
    callback_query.answer()
    user_id = callback_query.from_user.id
    
    _admin_state[user_id] = {"action": "add_credits"}
    
    callback_query.message.edit_text(
        "➕ **הוספת קרדיטים**\n\nשלח הודעה בפורמט:\n`USER_ID כמות`\n\nלדוגמה: `123456789 50`",
        reply_markup=types.InlineKeyboardMarkup([
            [types.InlineKeyboardButton("🔙 חזרה", callback_data="admin:back")]
        ])
    )


def handle_reset_quota_prompt(client: Client, callback_query: types.CallbackQuery):
    """Prompt for resetting quota"""
    callback_query.answer()
    user_id = callback_query.from_user.id
    
    _admin_state[user_id] = {"action": "reset_quota"}
    
    callback_query.message.edit_text(
        "🔄 **איפוס מכסה**\n\nשלח את ה-User ID של המשתמש לאיפוס:",
        reply_markup=types.InlineKeyboardMarkup([
            [types.InlineKeyboardButton("🔙 חזרה", callback_data="admin:back")]
        ])
    )


def handle_block_user_prompt(client: Client, callback_query: types.CallbackQuery):
    """Prompt for blocking user"""
    callback_query.answer()
    user_id = callback_query.from_user.id
    
    _admin_state[user_id] = {"action": "block_user"}
    
    callback_query.message.edit_text(
        "🚫 **חסימת משתמש**\n\nשלח את ה-User ID של המשתמש לחסימה:",
        reply_markup=types.InlineKeyboardMarkup([
            [types.InlineKeyboardButton("🔙 חזרה", callback_data="admin:back")]
        ])
    )


def handle_user_action(client: Client, callback_query: types.CallbackQuery, target_user: int, action: str):
    """Handle specific user actions"""
    callback_query.answer()
    
    if action == "add":
        add_paid_quota(target_user, 10)
        callback_query.answer("✅ נוספו 10 קרדיטים", show_alert=True)
    elif action == "reset":
        reset_user_quota(target_user)
        callback_query.answer("✅ המכסה אופסה", show_alert=True)
    elif action == "block":
        block_user(target_user)
        callback_query.answer("✅ המשתמש נחסם", show_alert=True)
    elif action == "unblock":
        unblock_user(target_user)
        callback_query.answer("✅ המשתמש שוחרר", show_alert=True)


def handle_back_to_menu(client: Client, callback_query: types.CallbackQuery):
    """Return to main admin menu"""
    user_id = callback_query.from_user.id
    
    # Clear any pending state
    _admin_state.pop(user_id, None)
    
    try:
        callback_query.answer()
    except Exception:
        pass  # Ignore if callback expired
    
    markup = types.InlineKeyboardMarkup([
        [types.InlineKeyboardButton("🏓 פינג", callback_data="admin:ping")],
        [types.InlineKeyboardButton("📈 סטטיסטיקות שרת", callback_data="admin:server_stats")],
        [types.InlineKeyboardButton("📊 סטטיסטיקות הורדות", callback_data="admin:download_stats")],
        [types.InlineKeyboardButton("👥 רשימת משתמשים", callback_data="admin:users:0")],
        [types.InlineKeyboardButton("💳 משתמשים בתשלום", callback_data="admin:paid_users:0")],
        [types.InlineKeyboardButton("➕ הוסף קרדיטים", callback_data="admin:add_credits")],
        [types.InlineKeyboardButton("🔄 אפס מכסה", callback_data="admin:reset_quota")],
        [types.InlineKeyboardButton("🚫 חסום משתמש", callback_data="admin:block_user")],
    ])
    
    callback_query.message.edit_text(
        "📊 **פאנל ניהול**\n\nבחר פעולה:",
        reply_markup=markup
    )


def admin_text_handler(client: Client, message: types.Message):
    """Handle text input for admin actions"""
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        return
    
    if user_id not in _admin_state:
        return
    
    text = message.text.strip()
    
    # If it's a command (starts with /), clear state and let other handlers process it
    if text.startswith("/"):
        _admin_state.pop(user_id, None)
        return
    
    state = _admin_state[user_id]
    action = state.get("action")
    
    if action == "add_credits":
        try:
            parts = text.split()
            target_id = int(parts[0])
            amount = int(parts[1])
            add_paid_quota(target_id, amount)
            message.reply_text(f"✅ נוספו {amount} קרדיטים למשתמש {target_id}", quote=True)
        except (ValueError, IndexError):
            message.reply_text("❌ פורמט שגוי. השתמש: `USER_ID כמות`", quote=True)
        finally:
            _admin_state.pop(user_id, None)
    
    elif action == "reset_quota":
        try:
            target_id = int(text)
            reset_user_quota(target_id)
            message.reply_text(f"✅ המכסה אופסה למשתמש {target_id}", quote=True)
        except ValueError:
            message.reply_text("❌ User ID לא תקין", quote=True)
        finally:
            _admin_state.pop(user_id, None)
    
    elif action == "block_user":
        try:
            target_id = int(text)
            block_user(target_id)
            message.reply_text(f"✅ המשתמש {target_id} נחסם", quote=True)
        except ValueError:
            message.reply_text("❌ User ID לא תקין", quote=True)
        finally:
            _admin_state.pop(user_id, None)

