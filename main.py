import warnings
warnings.filterwarnings("ignore", category=UserWarning, message='Field "model_custom_emoji_id" has conflict with protected namespace "model_"')

import asyncio
import logging
import sys
import random
import re
import sqlite3
from datetime import datetime
import aiohttp
import hashlib
import math
import string
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, html, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, LinkPreviewOptions
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

import config

# --- Настройка логирования ---
logging.basicConfig(level=logging.INFO, stream=sys.stdout, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Фейковая казна ---
class FakeTreasury:
    def __init__(self):
        self.usdt = random.randint(590, 780)
        self.last_update = datetime.now()
    
    def get(self):
        now = datetime.now()
        if (now - self.last_update).total_seconds() >= 300:
            self.usdt = random.randint(590, 780)
            self.last_update = now
        return self.usdt

fake_treasury = FakeTreasury()

# --- Бесплатный розыгрыш (Fast Game) ---
class FastGame:
    def __init__(self, game_id: int, creator_id: int, prize: float):
        self.game_id = game_id
        self.creator_id = creator_id
        self.prize = prize
        self.players = []
        self.status = "waiting"
        self.winner_id = None
        self.created_at = datetime.now()
    
    def add_player(self, user_id: int) -> bool:
        if user_id in self.players:
            return False
        if len(self.players) >= 6:
            return False
        self.players.append(user_id)
        return True
    
    def is_full(self) -> bool:
        return len(self.players) >= 6
    
    def get_players_count(self) -> int:
        return len(self.players)
    
    def get_players_list(self) -> list:
        return self.players.copy()

fast_games = {}
fast_game_counter = 0

# --- Состояния FSM ---
class DepositState(StatesGroup):
    entering_amount = State()

class WithdrawState(StatesGroup):
    entering_amount = State()
    choosing_method = State()

class AdminState(StatesGroup):
    waiting_for_mailing = State()

class CheckState(StatesGroup):
    entering_amount = State()
    entering_uses = State()

class PrivacyState(StatesGroup):
    entering_nickname = State()

class MinesState(StatesGroup):
    playing = State()

class TowerState(StatesGroup):
    playing = State()

class FastGameState(StatesGroup):
    waiting_for_players = State()

class PlayingState(StatesGroup):
    dice = State()
    custom = State()
    old = State()
    strategy = State()

# --- API Клиенты ---
class CryptoPay:
    def __init__(self, token):
        self.token = token
        self.api_url = "https://pay.crypt.bot/api/"

    async def create_invoice(self, amount):
        if amount is None or math.isnan(amount) or amount <= 0:
            return None, None
        async with aiohttp.ClientSession() as session:
            headers = {"Crypto-Pay-API-Token": self.token}
            payload = {
                "asset": "USDT",
                "amount": str(amount),
                "description": "Deposit",
                "paid_btn_name": "callback",
                "paid_btn_url": "https://t.me/spins"
            }
            async with session.post(f"{self.api_url}createInvoice", json=payload, headers=headers) as resp:
                data = await resp.json()
                if data.get("ok"):
                    return data["result"]["pay_url"], data["result"]["invoice_id"]
                return None, None

    async def get_invoice(self, invoice_id):
        async with aiohttp.ClientSession() as session:
            headers = {"Crypto-Pay-API-Token": self.token}
            params = {"invoice_ids": str(invoice_id)}
            async with session.get(f"{self.api_url}getInvoices", params=params, headers=headers) as resp:
                data = await resp.json()
                if data.get("ok") and data["result"]["items"]:
                    return data["result"]["items"][0]
                return None

    async def transfer(self, user_id, amount, asset="USDT"):
        if amount is None or math.isnan(amount) or amount <= 0:
            return False, "Invalid amount"
        async with aiohttp.ClientSession() as session:
            headers = {"Crypto-Pay-API-Token": self.token}
            spend_id = hashlib.md5(f"{user_id}_{amount}_{datetime.now()}".encode()).hexdigest()
            payload = {
                "user_id": int(user_id),
                "asset": asset,
                "amount": str(amount),
                "spend_id": spend_id
            }
            async with session.post(f"{self.api_url}transfer", json=payload, headers=headers) as resp:
                data = await resp.json()
                if data.get("ok"):
                    return True, data["result"]
                return False, data.get("error", {}).get("name", "Unknown error")

    async def create_check(self, amount, asset="USDT", pin_to_user_id=None):
        if amount is None or math.isnan(amount) or amount <= 0:
            return None
        async with aiohttp.ClientSession() as session:
            headers = {"Crypto-Pay-API-Token": self.token}
            payload = {
                "asset": asset,
                "amount": str(amount)
            }
            if pin_to_user_id:
                payload["pin_to_user_id"] = pin_to_user_id
            async with session.post(f"{self.api_url}createCheck", json=payload, headers=headers) as resp:
                data = await resp.json()
                if data.get("ok"):
                    return data["result"]["bot_check_url"]
                return None

crypto_pay = CryptoPay(config.CRYPTO_PAY_TOKEN)

# --- База данных ---
class Database:
    def __init__(self, db_name="users.db"):
        self.conn = sqlite3.connect(db_name)
        self.cursor = self.conn.cursor()
        self.create_table()

    def create_table(self):
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                reg_date TEXT,
                player_num INTEGER,
                lang TEXT DEFAULT 'ru',
                balance REAL DEFAULT 0.0,
                privacy_type TEXT DEFAULT 'username',
                nickname TEXT,
                total_bets INTEGER DEFAULT 0,
                total_turnover REAL DEFAULT 0.0,
                total_deposits REAL DEFAULT 0.0,
                total_withdrawals REAL DEFAULT 0.0,
                current_bet REAL DEFAULT 0.2,
                referrer_id INTEGER,
                ref_balance REAL DEFAULT 0.0,
                total_ref_earned REAL DEFAULT 0.0,
                rank_id INTEGER DEFAULT 0,
                mines_count INTEGER DEFAULT 3,
                tower_bombs INTEGER DEFAULT 1
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS processed_invoices (
                invoice_id TEXT PRIMARY KEY,
                user_id INTEGER,
                amount REAL,
                method TEXT,
                date TEXT
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS checks (
                check_id TEXT PRIMARY KEY,
                creator_id INTEGER,
                amount REAL,
                uses_left INTEGER,
                max_uses INTEGER,
                created_at TEXT,
                is_active INTEGER DEFAULT 1
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS check_activations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                check_id TEXT,
                user_id INTEGER,
                activated_at TEXT,
                FOREIGN KEY (check_id) REFERENCES checks (check_id)
            )
        """)
        self.cursor.execute("PRAGMA table_info(users)")
        columns = [column[1] for column in self.cursor.fetchall()]
        for col, dtype in [("balance", "REAL DEFAULT 0.0"), ("privacy_type", "TEXT DEFAULT 'username'"), 
                           ("nickname", "TEXT"), ("total_bets", "INTEGER DEFAULT 0"), 
                           ("total_turnover", "REAL DEFAULT 0.0"), ("total_deposits", "REAL DEFAULT 0.0"),
                           ("total_withdrawals", "REAL DEFAULT 0.0"), ("current_bet", "REAL DEFAULT 0.2"),
                           ("referrer_id", "INTEGER"), ("ref_balance", "REAL DEFAULT 0.0"),
                           ("total_ref_earned", "REAL DEFAULT 0.0"), ("rank_id", "INTEGER DEFAULT 0"),
                           ("mines_count", "INTEGER DEFAULT 3"), ("tower_bombs", "INTEGER DEFAULT 1")]:
            if col not in columns:
                self.cursor.execute(f"ALTER TABLE users ADD COLUMN {col} {dtype}")
        self.conn.commit()

    def create_check(self, creator_id, amount, max_uses):
        check_id = ''.join(random.choices(string.ascii_letters + string.digits, k=12))
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.cursor.execute(
            "INSERT INTO checks (check_id, creator_id, amount, uses_left, max_uses, created_at, is_active) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (check_id, creator_id, amount, max_uses, max_uses, created_at, 1)
        )
        self.conn.commit()
        return check_id

    def get_check(self, check_id):
        self.cursor.execute("SELECT * FROM checks WHERE check_id = ? AND is_active = 1 AND uses_left > 0", (check_id,))
        return self.cursor.fetchone()

    def activate_check(self, check_id, user_id):
        self.cursor.execute("SELECT 1 FROM check_activations WHERE check_id = ? AND user_id = ?", (check_id, user_id))
        if self.cursor.fetchone():
            return False, "already_used"
        self.cursor.execute("SELECT amount, uses_left FROM checks WHERE check_id = ? AND is_active = 1 AND uses_left > 0", (check_id,))
        row = self.cursor.fetchone()
        if not row:
            return False, "not_found"
        amount, uses_left = row
        self.cursor.execute("UPDATE checks SET uses_left = uses_left - 1 WHERE check_id = ?", (check_id,))
        activated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.cursor.execute(
            "INSERT INTO check_activations (check_id, user_id, activated_at) VALUES (?, ?, ?)",
            (check_id, user_id, activated_at)
        )
        self.conn.commit()
        self.add_balance(user_id, amount)
        return True, amount

    def get_my_checks(self, creator_id):
        self.cursor.execute("SELECT check_id, amount, uses_left, max_uses, created_at FROM checks WHERE creator_id = ? AND is_active = 1", (creator_id,))
        return self.cursor.fetchall()

    def deactivate_check(self, check_id, creator_id):
        self.cursor.execute("UPDATE checks SET is_active = 0 WHERE check_id = ? AND creator_id = ?", (check_id, creator_id))
        self.conn.commit()
        return self.cursor.rowcount > 0

    def is_invoice_processed(self, invoice_id):
        self.cursor.execute("SELECT 1 FROM processed_invoices WHERE invoice_id = ?", (invoice_id,))
        return self.cursor.fetchone() is not None

    def mark_invoice_processed(self, invoice_id, user_id, amount, method):
        date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.cursor.execute(
            "INSERT INTO processed_invoices (invoice_id, user_id, amount, method, date) VALUES (?, ?, ?, ?, ?)",
            (invoice_id, user_id, amount, method, date)
        )
        self.conn.commit()

    def register_user(self, user_id, username, referrer_id=None):
        self.cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
        if not self.cursor.fetchone():
            self.cursor.execute("SELECT COUNT(*) FROM users")
            count = self.cursor.fetchone()[0]
            player_num = count + 1
            reg_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.cursor.execute(
                "INSERT INTO users (user_id, username, reg_date, player_num, balance, total_bets, total_turnover, total_deposits, total_withdrawals, current_bet, referrer_id, ref_balance, total_ref_earned, rank_id, mines_count, tower_bombs) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (user_id, username, reg_date, player_num, 0.0, 0, 0.0, 0.0, 0.0, 0.2, referrer_id, 0.0, 0.0, 0, 3, 1)
            )
            self.conn.commit()
            return True
        return False

    def get_user_data(self, user_id):
        self.cursor.execute("SELECT reg_date, player_num, lang, balance, privacy_type, nickname, username, total_bets, total_turnover, total_deposits, total_withdrawals, current_bet, referrer_id, ref_balance, total_ref_earned, rank_id, mines_count, tower_bombs FROM users WHERE user_id = ?", (user_id,))
        return self.cursor.fetchone()

    def add_ref_balance(self, user_id, amount):
        self.cursor.execute("UPDATE users SET ref_balance = ref_balance + ?, total_ref_earned = total_ref_earned + ? WHERE user_id = ?", (amount, amount, user_id))
        self.conn.commit()

    def claim_ref_balance(self, user_id):
        self.cursor.execute("SELECT ref_balance FROM users WHERE user_id = ?", (user_id,))
        row = self.cursor.fetchone()
        if not row:
            return 0
        balance = row[0]
        if balance >= 1.0:
            self.cursor.execute("UPDATE users SET ref_balance = 0 WHERE user_id = ? AND ref_balance = ?", (user_id, balance))
            if self.cursor.rowcount > 0:
                self.cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (balance, user_id))
                self.conn.commit()
                return balance
        return 0

    def get_ref_stats(self, user_id):
        self.cursor.execute("SELECT COUNT(*) FROM users WHERE referrer_id = ?", (user_id,))
        return self.cursor.fetchone()[0]

    def set_bet(self, user_id, amount):
        if amount is None or math.isnan(amount) or amount < 0:
            amount = 0
        self.cursor.execute("UPDATE users SET current_bet = ? WHERE user_id = ?", (amount, user_id))
        self.conn.commit()

    def add_balance(self, user_id, amount, is_deposit=False, is_withdraw=False, is_bet=False):
        if amount is None or math.isnan(amount) or amount == 0:
            return False
        if is_bet or is_withdraw:
            self.cursor.execute(
                "UPDATE users SET balance = balance + ? WHERE user_id = ? AND balance >= ?",
                (amount, user_id, abs(amount))
            )
        else:
            self.cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        if self.cursor.rowcount == 0:
            return False
        if is_deposit:
            self.cursor.execute("UPDATE users SET total_deposits = total_deposits + ? WHERE user_id = ?", (amount, user_id))
        if is_withdraw:
            self.cursor.execute("UPDATE users SET total_withdrawals = total_withdrawals + ? WHERE user_id = ?", (abs(amount), user_id))
        if is_bet:
            self.cursor.execute("UPDATE users SET total_bets = total_bets + 1, total_turnover = total_turnover + ? WHERE user_id = ?", (abs(amount), user_id))
            self.cursor.execute("SELECT total_turnover FROM users WHERE user_id = ?", (user_id,))
            turnover_row = self.cursor.fetchone()
            if turnover_row:
                turnover = turnover_row[0]
                new_rank = int(turnover // 1000)
                self.cursor.execute("UPDATE users SET rank_id = ? WHERE user_id = ?", (new_rank, user_id))
        self.conn.commit()
        return True

    def set_lang(self, user_id, lang):
        self.cursor.execute("UPDATE users SET lang = ? WHERE user_id = ?", (lang, user_id))
        self.conn.commit()

    def set_privacy(self, user_id, privacy_type):
        self.cursor.execute("UPDATE users SET privacy_type = ? WHERE user_id = ?", (privacy_type, user_id))
        self.conn.commit()

    def set_nickname(self, user_id, nickname):
        self.cursor.execute("UPDATE users SET nickname = ? WHERE user_id = ?", (nickname, user_id))
        self.conn.commit()
    
    def set_mines_count(self, user_id, count):
        self.cursor.execute("UPDATE users SET mines_count = ? WHERE user_id = ?", (count, user_id))
        self.conn.commit()
    
    def set_tower_bombs(self, user_id, count):
        self.cursor.execute("UPDATE users SET tower_bombs = ? WHERE user_id = ?", (count, user_id))
        self.conn.commit()

db = Database()
user_navigation = {}
dp = Dispatcher()

# --- Глобальные настройки ---
RANKS = ["🌑 None", "🥉 Bronze", "🥈 Silver", "🥇 Gold", "💎 Platinum", "🏆 Diamond", "👑 Master", "🔥 Grandmaster", "✨ Legend", "🌌 Immortal"]
BOT_USERNAME = "@spins"

async def update_bot_username(bot: Bot):
    global BOT_USERNAME
    me = await bot.get_me()
    BOT_USERNAME = f"@{me.username}"

def get_lang(user_id: int) -> str:
    data = db.get_user_data(user_id)
    return data[2] if data else "ru"

def get_text(user_id: int, key: str) -> str:
    lang = get_lang(user_id)
    text = config.TEXTS[lang].get(key, "")
    if isinstance(text, str):
        text = text.replace("@spins", BOT_USERNAME).replace("spins", BOT_USERNAME.replace("@", ""))
    return text

def get_btn(user_id: int, key: str) -> str:
    lang = get_lang(user_id)
    text = config.TEXTS[lang]["buttons"].get(key, "")
    if isinstance(text, str):
        text = text.replace("@spins", BOT_USERNAME).replace("spins", BOT_USERNAME.replace("@", ""))
    return text

def get_user_display_name(user_id: int, first_name: str = "Игрок") -> str:
    data = db.get_user_data(user_id)
    if not data:
        return first_name
    reg_date, player_num, lang, balance, privacy_type, nickname, username, *rest = data
    if username:
        return f"@{username}"
    return first_name

def get_main_keyboard(user_id: int):
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=get_btn(user_id, "play"), callback_data="play"),
        InlineKeyboardButton(text=get_btn(user_id, "chats"), callback_data="chats")
    )
    builder.row(
        InlineKeyboardButton(text=get_btn(user_id, "profile"), callback_data="profile"),
        InlineKeyboardButton(text=get_btn(user_id, "referral"), callback_data="referral")
    )
    builder.row(
        InlineKeyboardButton(text=get_btn(user_id, "language"), callback_data="language"),
        InlineKeyboardButton(text=get_btn(user_id, "fast_game"), callback_data="fast_menu")
    )
    builder.row(
        InlineKeyboardButton(text=get_btn(user_id, "checks"), callback_data="checks_menu"),
        InlineKeyboardButton(text=get_btn(user_id, "own_casino"), url=config.OWN_CASINO_LINK)
    )
    return builder.as_markup()

def get_back_button(previous_menu: str):
    return InlineKeyboardButton(text="⬅️ Назад", callback_data=f"back:{previous_menu}")

async def send_alert(bot: Bot, user_id: int, amount: float, type: str):
    if amount < 50:
        return
    try:
        user_name = get_user_display_name(user_id)
        if type == "deposit":
            text = f"💰 <b>Крупное пополнение!</b>\n\n👤 Игрок: {user_name}\n💵 Сумма: <b>{amount:.2f} USDT</b>"
        elif type == "withdraw":
            text = f"📥 <b>Крупный вывод!</b>\n\n👤 Игрок: {user_name}\n💵 Сумма: <b>{amount:.2f} USDT</b>"
        elif type == "win":
            text = f"🎉 <b>Огромная победа!</b>\n\n👤 Игрок: {user_name}\n💵 Выигрыш: <b>{amount:.2f} USDT</b>"
        else:
            return
        await bot.send_message(chat_id=config.ALERTS_CHANNEL, text=text)
    except Exception as e:
        logger.error(f"Error sending alert: {e}")

# ==================== КОМАНДЫ ====================

@dp.message(Command("help"))
async def help_command(message: Message):
    help_text = """
🎮 <b>Доступные команды:</b>

• <code>/start</code> - Главное меню
• <code>/help</code> - Эта справка
• <code>/reserve</code> - Резервы казино (USDT)
• <code>/5</code> - Быстрая игра "Всё кроме 6"
• <code>/fast [сумма]</code> - Создать БЕСПЛАТНЫЙ розыгрыш (работает в чатах)

<b>🎁 Что такое /fast?</b>
• Вы указываете приз (от 0.01 USDT) - он списывается с вас
• Другие участники присоединяются БЕСПЛАТНО
• Когда наберется 6 участников - бот кидает кубик
• Победитель забирает ВЕСЬ приз!

<b>📝 Текстовые команды для игр:</b>
• <code>куб чет</code> / <code>куб нечет</code> - Чет/Нечет
• <code>куб меньше</code> / <code>куб больше</code> - 1-3 или 4-6
• <code>куб 1</code> (или 2,3,4,5,6) - Ставка на число
• <code>куб 1,2</code> - Ставка на несколько чисел
• <code>куб 7</code> - Сумма двух кубиков
• <code>произведение</code> - Произведение двух кубиков
• <code>мины</code> / <code>башня</code> - Режимы игры
• <code>игры</code> / <code>играть</code> - Меню игр
• <code>балик</code> / <code>б</code> - Показать баланс (USDT)
• <code>вб</code> - Ва-банк (вся сумма)

<b>💰 Переводы:</b>
• <code>дать 5</code> (ответом на сообщение) - Передать USDT

<b>🎲 Ставки:</b>
• Напишите <code>5$</code> - изменить ставку (в USDT)
    """
    await message.answer(help_text, parse_mode=ParseMode.HTML)

# ==================== АДМИН ПАНЕЛЬ (ОГРАНИЧЕННЫЙ ДОСТУП) ====================

def is_limited_admin(user_id: int) -> bool:
    """Проверка, имеет ли пользователь ограниченные права админа"""
    return user_id in config.ADMINS_LIMITED

def is_full_admin(user_id: int) -> bool:
    """Проверка, имеет ли пользователь полные права админа"""
    return user_id in config.ADMINS

@dp.message(Command("admin"))
async def admin_command(message: Message, state: FSMContext):
    """Админ панель (доступна только админам из ADMINS_LIMITED)"""
    user_id = message.from_user.id
    
    # Проверяем права
    if not is_limited_admin(user_id) and not is_full_admin(user_id):
        return await message.answer("❌ У вас нет доступа к этой команде!", parse_mode=ParseMode.HTML)
    
    await state.clear()
    
    # Получаем статистику
    db.cursor.execute("SELECT COUNT(*) FROM users")
    total_users = db.cursor.fetchone()[0]
    
    db.cursor.execute("SELECT SUM(total_deposits) FROM users")
    total_deposits = db.cursor.fetchone()[0] or 0
    
    db.cursor.execute("SELECT SUM(total_withdrawals) FROM users")
    total_withdrawals = db.cursor.fetchone()[0] or 0
    
    db.cursor.execute("SELECT SUM(total_turnover) FROM users")
    total_turnover = db.cursor.fetchone()[0] or 0
    
    db.cursor.execute("SELECT SUM(total_bets) FROM users")
    total_bets = db.cursor.fetchone()[0] or 0
    
    # Статистика за сегодня
    today = datetime.now().strftime("%Y-%m-%d")
    db.cursor.execute("SELECT COUNT(*) FROM users WHERE reg_date LIKE ?", (f"{today}%",))
    new_users_today = db.cursor.fetchone()[0]
    
    text = f"👑 <b>Админ панель</b>\n\n"
    text += f"📊 <b>Общая статистика:</b>\n"
    text += f"• 👥 Всего пользователей: <b>{total_users}</b>\n"
    text += f"• 📈 Новых сегодня: <b>{new_users_today}</b>\n"
    text += f"• 💰 Общий депозит: <b>{total_deposits:.2f} USDT</b>\n"
    text += f"• 📤 Общий вывод: <b>{total_withdrawals:.2f} USDT</b>\n"
    text += f"• 📊 Общий оборот: <b>{total_turnover:.2f} USDT</b>\n"
    text += f"• 🎮 Всего ставок: <b>{total_bets}</b>\n"
    
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats"),
        InlineKeyboardButton(text="📨 Рассылка", callback_data="admin_mailing")
    )
    builder.row(InlineKeyboardButton(text="🔒 Выйти", callback_data="admin_exit"))
    
    await message.answer(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data == "admin_stats")
async def admin_stats_callback(callback: CallbackQuery, state: FSMContext):
    """Подробная статистика для админа"""
    user_id = callback.from_user.id
    
    if not is_limited_admin(user_id) and not is_full_admin(user_id):
        return await callback.answer("❌ Нет доступа!", show_alert=True)
    
    # Подробная статистика
    db.cursor.execute("SELECT COUNT(*) FROM users")
    total_users = db.cursor.fetchone()[0]
    
    # За последние 7 дней
    week_ago = (datetime.now() - datetime.timedelta(days=7)).strftime("%Y-%m-%d")
    db.cursor.execute("SELECT COUNT(*) FROM users WHERE reg_date >= ?", (week_ago,))
    new_users_week = db.cursor.fetchone()[0]
    
    # За последние 30 дней
    month_ago = (datetime.now() - datetime.timedelta(days=30)).strftime("%Y-%m-%d")
    db.cursor.execute("SELECT COUNT(*) FROM users WHERE reg_date >= ?", (month_ago,))
    new_users_month = db.cursor.fetchone()[0]
    
    # Топ 10 по обороту
    db.cursor.execute("SELECT user_id, total_turnover FROM users ORDER BY total_turnover DESC LIMIT 10")
    top_turnover = db.cursor.fetchall()
    
    # Топ 10 по депозитам
    db.cursor.execute("SELECT user_id, total_deposits FROM users ORDER BY total_deposits DESC LIMIT 10")
    top_deposits = db.cursor.fetchall()
    
    text = f"📊 <b>Расширенная статистика</b>\n\n"
    text += f"👥 <b>Пользователи:</b>\n"
    text += f"• Всего: <b>{total_users}</b>\n"
    text += f"• За 7 дней: <b>{new_users_week}</b>\n"
    text += f"• За 30 дней: <b>{new_users_month}</b>\n\n"
    
    text += f"🏆 <b>Топ 10 по обороту:</b>\n"
    for i, (user_id, turnover) in enumerate(top_turnover[:5], 1):
        user_name = get_user_display_name(user_id)
        text += f"{i}. {user_name} — <b>{turnover:.2f} USDT</b>\n"
    
    text += f"\n💎 <b>Топ 10 по депозитам:</b>\n"
    for i, (user_id, deposits) in enumerate(top_deposits[:5], 1):
        user_name = get_user_display_name(user_id)
        text += f"{i}. {user_name} — <b>{deposits:.2f} USDT</b>\n"
    
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back"))
    builder.row(InlineKeyboardButton(text="🔒 Выйти", callback_data="admin_exit"))
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data == "admin_mailing")
async def admin_mailing_callback(callback: CallbackQuery, state: FSMContext):
    """Начало рассылки"""
    user_id = callback.from_user.id
    
    if not is_limited_admin(user_id) and not is_full_admin(user_id):
        return await callback.answer("❌ Нет доступа!", show_alert=True)
    
    await state.set_state(AdminState.waiting_for_mailing)
    
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="❌ Отменить", callback_data="admin_cancel_mailing"))
    
    await callback.message.edit_text(
        "📨 <b>Рассылка</b>\n\n"
        "Отправьте сообщение, которое хотите разослать всем пользователям.\n\n"
        "Поддерживаются: текст, фото, видео, документы.\n\n"
        "⚠️ <b>Внимание!</b> Рассылка придет ВСЕМ пользователям бота!",
        reply_markup=builder.as_markup(),
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data == "admin_cancel_mailing")
async def admin_cancel_mailing_callback(callback: CallbackQuery, state: FSMContext):
    """Отмена рассылки"""
    await state.clear()
    await admin_command(callback.message, state)

@dp.message(AdminState.waiting_for_mailing)
async def process_mailing(message: Message, state: FSMContext):
    """Обработка отправки рассылки"""
    user_id = message.from_user.id
    
    if not is_limited_admin(user_id) and not is_full_admin(user_id):
        await state.clear()
        return await message.answer("❌ Нет доступа!")
    
    # Получаем всех пользователей
    db.cursor.execute("SELECT user_id FROM users")
    users = db.cursor.fetchall()
    
    if not users:
        await state.clear()
        return await message.answer("❌ Нет пользователей для рассылки!")
    
    # Отправляем подтверждение
    confirm_text = f"📨 <b>Подтверждение рассылки</b>\n\n"
    confirm_text += f"Сообщение будет отправлено <b>{len(users)}</b> пользователям.\n\n"
    confirm_text += f"<b>Текст сообщения:</b>\n{message.text or 'Медиафайл с подписью'}\n\n"
    confirm_text += f"<b>Медиа:</b> {'✅ есть' if message.photo or message.video or message.document else '❌ нет'}\n\n"
    confirm_text += f"Начать рассылку?"
    
    # Сохраняем сообщение в state
    await state.update_data(mailing_message=message)
    
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Да, отправить", callback_data="admin_confirm_mailing"),
        InlineKeyboardButton(text="❌ Отменить", callback_data="admin_cancel_mailing")
    )
    
    await message.answer(confirm_text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data == "admin_confirm_mailing")
async def admin_confirm_mailing_callback(callback: CallbackQuery, state: FSMContext):
    """Подтверждение и отправка рассылки"""
    user_id = callback.from_user.id
    
    if not is_limited_admin(user_id) and not is_full_admin(user_id):
        return await callback.answer("❌ Нет доступа!", show_alert=True)
    
    data = await state.get_data()
    mailing_message = data.get("mailing_message")
    
    if not mailing_message:
        await callback.answer("❌ Ошибка: сообщение не найдено!", show_alert=True)
        await state.clear()
        return
    
    # Получаем всех пользователей
    db.cursor.execute("SELECT user_id FROM users")
    users = db.cursor.fetchall()
    
    await callback.message.edit_text("📨 <b>Рассылка начата...</b>\n\n0 / " + str(len(users)), parse_mode=ParseMode.HTML)
    
    success = 0
    fail = 0
    
    for i, (user_id,) in enumerate(users, 1):
        try:
            if mailing_message.text:
                await callback.bot.send_message(user_id, mailing_message.text, parse_mode=ParseMode.HTML)
            elif mailing_message.photo:
                await callback.bot.send_photo(user_id, mailing_message.photo[-1].file_id, caption=mailing_message.caption, parse_mode=ParseMode.HTML)
            elif mailing_message.video:
                await callback.bot.send_video(user_id, mailing_message.video.file_id, caption=mailing_message.caption, parse_mode=ParseMode.HTML)
            elif mailing_message.document:
                await callback.bot.send_document(user_id, mailing_message.document.file_id, caption=mailing_message.caption, parse_mode=ParseMode.HTML)
            success += 1
        except Exception as e:
            fail += 1
            logger.error(f"Failed to send to {user_id}: {e}")
        
        # Обновляем статус каждые 50 сообщений
        if i % 50 == 0:
            await callback.message.edit_text(f"📨 <b>Рассылка...</b>\n\n✅ Успешно: {success}\n❌ Ошибок: {fail}\n📊 Прогресс: {i}/{len(users)}", parse_mode=ParseMode.HTML)
    
    # Финальный отчет
    await callback.message.edit_text(
        f"📨 <b>Рассылка завершена!</b>\n\n"
        f"✅ Успешно: <b>{success}</b>\n"
        f"❌ Ошибок: <b>{fail}</b>\n"
        f"📊 Всего: <b>{len(users)}</b>",
        parse_mode=ParseMode.HTML
    )
    
    await state.clear()
    
    # Возвращаемся в админ панель
    await admin_command(callback.message, state)

@dp.callback_query(F.data == "admin_back")
async def admin_back_callback(callback: CallbackQuery, state: FSMContext):
    """Возврат в главную админ панель"""
    await admin_command(callback.message, state)

@dp.callback_query(F.data == "admin_exit")
async def admin_exit_callback(callback: CallbackQuery, state: FSMContext):
    """Выход из админ панели"""
    await state.clear()
    await callback.message.delete()
    await callback.answer("Выход из админ панели")

@dp.message(Command("reserve"))
async def reserve_command_handler(message: Message):
    current_usdt = fake_treasury.get()
    text = f"<b>🥣 Crypto Bot: ${current_usdt:,.2f} USDT</b>\n🟢 USDT: {current_usdt:.4f} (${current_usdt:,.2f} USDT)\n\n<code>Баланс обновлен: только что</code>"
    await message.answer(text, parse_mode=ParseMode.HTML)

@dp.message(Command("fast"))
async def fast_command(message: Message, state: FSMContext):
    """Создание бесплатного розыгрыша (работает ТОЛЬКО в чатах)"""
    
    if message.chat.type == "private":
        return await message.answer("❌ Команда /fast работает только в групповых чатах!\n\nСоздайте чат и добавьте туда бота.", parse_mode=ParseMode.HTML)
    
    args = message.text.split()
    if len(args) != 2:
        return await message.answer("❌ Использование: <code>/fast 10</code> - создать розыгрыш с призом 10 USDT\n\n"
                                  "Примеры:\n"
                                  "<code>/fast 0.5</code> - приз 0.5 USDT\n"
                                  "<code>/fast 1</code> - приз 1 USDT\n"
                                  "<code>/fast 100</code> - приз 100 USDT\n\n"
                                  "⚠️ Участники НЕ платят! Приз списывается с создателя.", 
                                  parse_mode=ParseMode.HTML)
    
    try:
        prize = float(args[1].replace(",", "."))
        if math.isnan(prize) or prize <= 0:
            raise ValueError
    except ValueError:
        return await message.answer("❌ Введите корректную сумму (число больше 0)\n\nПример: <code>/fast 10</code>")
    
    if prize < 0.01:
        return await message.answer("❌ Минимальный приз — <b>0.01 USDT</b>")
    if prize > config.MAX_BET:
        return await message.answer(f"❌ Максимальный приз — <b>{config.MAX_BET:.2f} USDT</b>")
    
    user_id = message.from_user.id
    user_data = db.get_user_data(user_id)
    balance = user_data[3] if user_data else 0
    
    if balance < prize:
        return await message.answer(f"❌ Недостаточно средств для создания розыгрыша! Ваш баланс: {balance:.2f} USDT")
    
    if not db.add_balance(user_id, -prize, is_bet=True):
        return await message.answer("❌ Ошибка при списании средств!")
    
    global fast_game_counter
    fast_game_counter += 1
    game_id = fast_game_counter
    
    game = FastGame(game_id, user_id, prize)
    game.add_player(user_id)  # Создатель автоматически участвует
    fast_games[game_id] = game
    
    await show_fast_game(message, game_id, state)

@dp.callback_query(F.data == "fast_menu")
async def fast_menu_callback(callback: CallbackQuery, state: FSMContext):
    """Меню быстрой игры"""
    await callback.message.answer(
        "🎁 <b>Бесплатный розыгрыш</b>\n\n"
        "Используйте команду: <code>/fast сумма</code>\n\n"
        "📌 <b>Примеры:</b>\n"
        "<code>/fast 0.5</code> - розыгрыш с призом 0.5 USDT\n"
        "<code>/fast 1</code> - розыгрыш с призом 1 USDT\n"
        "<code>/fast 10</code> - розыгрыш с призом 10 USDT\n\n"
        "📖 <b>Правила:</b>\n"
        "• Создатель указывает приз (от 0.01 USDT) - он списывается с него\n"
        "• Создатель автоматически становится участником\n"
        "• Еще 5 человек нажимают кнопку «Участвовать» БЕСПЛАТНО\n"
        "• Когда наберется 6 участников — бот кидает кубик 🎲\n"
        "• Выигрывает тот, чей номер в списке совпал с числом на кубике\n"
        "• Победитель забирает ВЕСЬ приз!\n\n"
        "⚠️ <b>Внимание:</b> Команда работает только в групповых чатах!",
        parse_mode=ParseMode.HTML
    )

async def show_fast_game(message: Message, game_id: int, state: FSMContext):
    """Отображение текущего розыгрыша"""
    game = fast_games.get(game_id)
    if not game:
        return
    
    await state.set_state(FastGameState.waiting_for_players)
    await state.update_data(current_game_id=game_id)
    
    user_name = get_user_display_name(game.creator_id, message.from_user.first_name)
    
    text = f"🎁 <b>Бесплатный розыгрыш №{game_id}</b>\n"
    text += f"💰 Приз: <b>{game.prize:.2f} USDT</b>\n"
    text += f"👑 Организатор: {user_name}\n"
    text += f"👥 Участников: {game.get_players_count()}/6\n\n"
    
    if game.players:
        text += "<b>Участники:</b>\n"
        for i, player_id in enumerate(game.players, 1):
            player_name = get_user_display_name(player_id)
            text += f"{i}. {player_name}\n"
    else:
        text += "⏳ Ожидание участников...\n"
    
    text += f"\n🎲 <b>Участие бесплатное!</b> Победитель забирает весь приз."
    
    builder = InlineKeyboardBuilder()
    
    if not game.is_full():
        builder.row(InlineKeyboardButton(text="🎲 Участвовать бесплатно", callback_data=f"fast_join:{game_id}"))
    
    builder.row(InlineKeyboardButton(text="❌ Отменить розыгрыш", callback_data=f"fast_cancel:{game_id}"))
    
    await message.answer(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data.startswith("fast_join:"))
async def fast_join_callback(callback: CallbackQuery, state: FSMContext):
    """Обработчик участия в бесплатном розыгрыше"""
    game_id = int(callback.data.split(":")[1])
    game = fast_games.get(game_id)
    
    if not game:
        return await callback.answer("❌ Розыгрыш уже завершен или отменен!", show_alert=True)
    
    if game.status != "waiting":
        return await callback.answer("❌ Розыгрыш уже начался!", show_alert=True)
    
    if game.is_full():
        return await callback.answer("❌ Розыгрыш уже заполнен!", show_alert=True)
    
    user_id = callback.from_user.id
    
    if user_id in game.players:
        return await callback.answer("❌ Вы уже участвуете!", show_alert=True)
    
    # БЕСПЛАТНОЕ УЧАСТИЕ - НИЧЕГО НЕ СПИСЫВАЕМ
    game.add_player(user_id)
    
    if game.is_full():
        await start_fast_game(callback.message, game_id, state)
    else:
        await show_fast_game(callback.message, game_id, state)

@dp.callback_query(F.data.startswith("fast_cancel:"))
async def fast_cancel_callback(callback: CallbackQuery, state: FSMContext):
    """Отмена розыгрыша (только для создателя) - возврат приза"""
    game_id = int(callback.data.split(":")[1])
    game = fast_games.get(game_id)
    
    if not game:
        return await callback.answer("❌ Розыгрыш уже завершен!", show_alert=True)
    
    user_id = callback.from_user.id
    
    if game.creator_id != user_id:
        return await callback.answer("❌ Только создатель может отменить розыгрыш!", show_alert=True)
    
    # Возвращаем приз создателю (так как розыгрыш не состоялся)
    db.add_balance(game.creator_id, game.prize)
    
    del fast_games[game_id]
    await state.clear()
    
    await callback.message.edit_text(f"❌ Розыгрыш №{game_id} отменен. Приз {game.prize:.2f} USDT возвращен организатору.", parse_mode=ParseMode.HTML)
    await callback.answer("Розыгрыш отменен")

async def start_fast_game(message: Message, game_id: int, state: FSMContext):
    """Начало розыгрыша - бросаем кубик"""
    game = fast_games.get(game_id)
    if not game:
        return
    
    game.status = "playing"
    
    players_text = ""
    for i, player_id in enumerate(game.players, 1):
        player_name = get_user_display_name(player_id)
        players_text += f"{i}. {player_name}\n"
    
    text = f"🎁 <b>Бесплатный розыгрыш №{game_id} начинается!</b>\n\n"
    text += f"<b>Участники:</b>\n{players_text}\n"
    text += f"💰 <b>Призовой фонд: {game.prize:.2f} USDT</b>\n\n"
    text += "🎲 <b>Бот кидает кубик...</b>"
    
    await message.edit_text(text, parse_mode=ParseMode.HTML)
    
    await asyncio.sleep(2)
    
    dice_msg = await message.answer_dice(emoji="🎲")
    dice_value = dice_msg.dice.value
    
    await asyncio.sleep(3)
    
    winner_index = dice_value - 1
    if winner_index >= len(game.players):
        winner_index = len(game.players) - 1
    
    winner_id = game.players[winner_index]
    game.winner_id = winner_id
    
    # Победитель получает приз (приз уже списан с создателя при создании)
    db.add_balance(winner_id, game.prize)
    
    winner_name = get_user_display_name(winner_id)
    
    final_text = f"🎁 <b>Бесплатный розыгрыш №{game_id}</b>\n\n"
    final_text += f"<b>Участники:</b>\n{players_text}\n"
    final_text += f"🎲 <b>Выпало число: {dice_value}</b>\n\n"
    final_text += f"🏆 <b>ПОБЕДИТЕЛЬ:</b> {winner_name}\n"
    final_text += f"💰 <b>Выигрыш: {game.prize:.2f} USDT</b>"
    
    await message.answer(final_text, parse_mode=ParseMode.HTML)
    
    try:
        await message.bot.send_message(winner_id, f"🎉 Поздравляем! Вы выиграли {game.prize:.2f} USDT в бесплатном розыгрыше №{game_id}!")
    except:
        pass
    
    del fast_games[game_id]
    await state.clear()

@dp.message(CommandStart())
async def command_start_handler(message: Message) -> None:
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    
    referrer_id = None
    check_id = None
    args = message.text.split()
    
    if len(args) > 1:
        arg = args[1]
        if arg.startswith("invite_"):
            try:
                potential_ref_id = arg.replace("invite_", "")
                if potential_ref_id.isdigit():
                    referrer_id = int(potential_ref_id)
                    if referrer_id == user_id:
                        referrer_id = None
            except:
                pass
        elif arg.startswith("check_"):
            check_id = arg.replace("check_", "")
    
    is_new = db.register_user(user_id, username, referrer_id)
    if is_new and referrer_id:
        try:
            await message.bot.send_message(referrer_id, f"👤 У вас новый реферал: <b>{username}</b>!")
        except:
            pass
    
    if check_id:
        success, result = db.activate_check(check_id, user_id)
        if success:
            await message.answer(f"✅ Вы активировали чек на <b>{result} USDT</b>!", parse_mode=ParseMode.HTML)
        elif result == "already_used":
            await message.answer("❌ Вы уже активировали этот чек!", parse_mode=ParseMode.HTML)
        else:
            await message.answer("❌ Чек не найден или уже использован!", parse_mode=ParseMode.HTML)
    
    await message.answer(
        get_text(user_id, "welcome"), 
        reply_markup=get_main_keyboard(user_id), 
        parse_mode=ParseMode.HTML
    )

# --- УСТАНОВКА СТАВКИ ТОЛЬКО ЧЕРЕЗ $ ---
@dp.message(F.text.regexp(r"^(\d+[\.,]?\d*)\s*\$"))
async def set_bet_by_text_handler(message: Message, state: FSMContext):
    user_id = message.from_user.id
    current_state = await state.get_state()
    if current_state:
        await state.clear()
    
    raw_text = message.text.replace("$", "").replace(",", ".").strip()
    if not raw_text:
        return await message.answer("❌ Введите сумму, например: <code>5$</code>")
    
    try:
        amount = float(raw_text)
        if math.isnan(amount) or amount <= 0:
            raise ValueError
    except ValueError:
        return await message.answer("❌ Введите корректную сумму, например: <code>5$</code>")
    
    if amount < 0.01:
        return await message.answer("❌ Минимальная ставка — <b>0.01 USDT</b>")
    if amount > config.MAX_BET:
        return await message.answer(f"❌ Максимальная ставка — <b>{config.MAX_BET:.2f} USDT</b>")
    
    db.set_bet(user_id, amount)
    await message.answer(f"✅ Ваша ставка установлена на <b>{amount:.2f} USDT</b>")

# ==================== БЫСТРЫЕ СТАВКИ (куб чет, нечет и т.д.) ====================
@dp.message(F.text.lower().regexp(r"^(куб|кубы)\s+(чет|нечет|меньше|больше|\d+(\,\d+)?)$"))
async def quick_dice_handler(message: Message, state: FSMContext):
    """Быстрые текстовые ставки на кубики"""
    await state.clear()
    user_id = message.from_user.id
    
    user_data = db.get_user_data(user_id)
    if not user_data:
        db.register_user(user_id, message.from_user.username or message.from_user.first_name)
        user_data = db.get_user_data(user_id)
    
    text = message.text.lower()
    
    bet_type = None
    if "чет" in text:
        bet_type = "1_even"
    elif "нечет" in text:
        bet_type = "1_odd"
    elif "меньше" in text:
        bet_type = "1_low"
    elif "больше" in text:
        bet_type = "1_high"
    else:
        numbers = re.findall(r'\d+', text)
        if numbers:
            num = int(numbers[0])
            if 1 <= num <= 6:
                bet_type = f"num_{num}"
    
    if bet_type:
        await state.set_state(PlayingState.dice)
        await process_dice_game(message, user_id, bet_type, state)
    else:
        await message.answer("❌ Неверный формат. Примеры: куб чет, куб 3, куб меньше")

# ==================== ТЕКСТОВЫЕ КОМАНДЫ ДЛЯ ИГР ====================

@dp.message(F.text.lower().in_({"мины", "башня"}))
async def game_text_handler(message: Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    db.register_user(user_id, username)
    await state.clear()
    
    if message.text.lower() == "мины":
        await show_mines_menu(message, user_id, state, edit=False)
    elif message.text.lower() == "башня":
        await show_tower_menu(message, user_id, state, edit=False)

@dp.message(F.text.lower().in_({"игры", "играть"}))
async def text_games_handler(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    
    user_data = db.get_user_data(user_id)
    if not user_data:
        db.register_user(user_id, message.from_user.username or message.from_user.first_name)
        user_data = db.get_user_data(user_id)
        
    balance = user_data[3]
    current_bet = user_data[11]
    
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🎲", callback_data="game:dice_emoji"),
        InlineKeyboardButton(text="⚽", callback_data="game:soccer"),
        InlineKeyboardButton(text="🎰", callback_data="game:slots")
    )
    builder.row(
        InlineKeyboardButton(text="☃️ Telegram", callback_data="game:dice"),
        InlineKeyboardButton(text="🐋 Авторские", callback_data="custom_games")
    )
    builder.row(
        InlineKeyboardButton(text=get_btn(user_id, "modes"), callback_data="modes_menu")
    )
    builder.row(get_back_button("main"))
    
    text = (
        "🎮 <b>Выбирайте игру!</b>\n\n"
        f"<blockquote>Баланс — <b>{balance:.2f} USDT</b> ❞\n"
        f"Ставка — <b>{current_bet:.2f} USDT</b></blockquote>\n\n"
        "<i>Пополняй и сыграй на реальные деньги</i>"
    )
    await message.answer(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)

@dp.message(F.text.lower() == "произведение")
async def multiply_text_handler(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    
    user_data = db.get_user_data(user_id)
    if not user_data:
        db.register_user(user_id, message.from_user.username or message.from_user.first_name)
        user_data = db.get_user_data(user_id)
    balance = user_data[3]
    current_bet = user_data[11]
    
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="Умн. 1-18 (x1.25)", callback_data="dice_bet:mult_1_18"))
    builder.row(InlineKeyboardButton(text="Умн. 19-36 (x4.4)", callback_data="dice_bet:mult_19_36"))
    builder.row(get_back_button("dice_menu"))
    
    await message.answer(
        f"Сделайте выбор для игры произведение двух 🎲\n\n"
        f"<blockquote>Баланс — <b>{balance:.2f}</b> USDT\n"
        f"Ставка — <b>{current_bet:.2f}</b> USDT</blockquote>\n\n"
        f"<i>Пополняй и сыграй на реальные деньги</i>",
        reply_markup=builder.as_markup(),
        parse_mode=ParseMode.HTML
    )

@dp.message(F.text.lower() == "куб 7")
async def cmd_cubes_7_handler(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    user_data = db.get_user_data(user_id)
    if not user_data:
        db.register_user(user_id, message.from_user.username or message.from_user.first_name)
        user_data = db.get_user_data(user_id)
    balance = user_data[3]
    current_bet = user_data[11]
    
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🎲 Меньше 7 (x2.4)", callback_data="dice_bet:sum_less_7"))
    builder.row(InlineKeyboardButton(text="🎲 Точно 7 (x6)", callback_data="dice_bet:sum_equal_7"))
    builder.row(InlineKeyboardButton(text="🎲 Больше 7 (x2.4)", callback_data="dice_bet:sum_more_7"))
    builder.row(get_back_button("dice_menu"))
    
    await message.answer(
        f"Сделайте выбор для игры\n\nСумма двух 🎲, от 2 до 12\n\n"
        f"<blockquote>Баланс — <b>{balance:.2f}</b> USDT\n"
        f"Ставка — <b>{current_bet:.2f}</b> USDT</blockquote>\n\n"
        f"<i>Пополняй и сыграй на реальные деньги</i>",
        reply_markup=builder.as_markup(),
        parse_mode=ParseMode.HTML
    )

@dp.message(F.text == "/5")
async def cmd_not_6_handler(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    user_data = db.get_user_data(user_id)
    if not user_data:
        db.register_user(user_id, message.from_user.username or message.from_user.first_name)
        user_data = db.get_user_data(user_id)
    balance = user_data[3]
    current_bet = user_data[11]
    
    builder = InlineKeyboardBuilder()
    text = (
        "<b>Всё кроме 6 — большие иксы</b>\n\n"
        "🎲 1 это <b>× 3</b>\n"
        "🎲 2 это <b>× 4</b>\n"
        "🎲 3 это <b>× 5.2</b>\n"
        "🎲 4 это <b>× 6.4</b>\n"
        "🎲 5 это <b>× 7.6</b>\n"
        "🎲 6 это <b>минус × 19</b>"
    )
    builder.row(InlineKeyboardButton(text="🎲 Играть", callback_data="dice_bet:not_6"))
    builder.row(get_back_button("dice_menu"))
    
    await message.answer(
        f"{text}\n\n"
        f"<blockquote>Баланс — <b>{balance:.2f}</b> USDT\n"
        f"Ставка — <b>{current_bet:.2f}</b> USDT</blockquote>\n\n"
        f"<i>Пополняй и сыграй на реальные деньги</i>",
        reply_markup=builder.as_markup(),
        parse_mode=ParseMode.HTML
    )

@dp.message(F.text.lower() == "вб")
async def vb_command_handler(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    user_data = db.get_user_data(user_id)
    if not user_data:
        return
    balance = user_data[3]
    if balance <= 0:
        return await message.answer("❌ Ваш баланс пуст!")

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_vb"))
    builder.row(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_vb"))
    await message.answer(
        f"Вы действительно хотите поставить весь баланс (<b>{balance:.2f} USDT</b>)?",
        reply_markup=builder.as_markup(),
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data == "confirm_vb")
async def confirm_vb_callback(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    user_data = db.get_user_data(user_id)
    if not user_data:
        return
    balance = user_data[3]
    bet_amount = min(balance, config.MAX_BET)
    db.set_bet(user_id, bet_amount)
    await callback.message.edit_text(
        f"✅ Ваша ставка установлена на: <b>{bet_amount:.2f} USDT</b>" + 
        (f" (ограничено макс. ставкой)" if bet_amount < balance else ""),
        parse_mode=ParseMode.HTML
    )
    await text_games_handler(callback.message, state)

@dp.callback_query(F.data == "cancel_vb")
async def cancel_vb_callback(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("❌ Установка ставки отменена.")

@dp.message(F.text.lower().in_({"балик","б", "бал", "баланс"}))
async def text_balance_handler(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    user_data = db.get_user_data(user_id)
    if not user_data:
        db.register_user(user_id, message.from_user.username or message.from_user.first_name)
        user_data = db.get_user_data(user_id)
    
    player_num = user_data[1]
    balance = user_data[3]
    nickname = user_data[5]
    username = user_data[6]
    display_name = nickname if nickname else (f"@{username}" if username else message.from_user.first_name)
    
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=get_btn(user_id, "deposit"), callback_data="deposit"),
        InlineKeyboardButton(text=get_btn(user_id, "withdraw"), callback_data="withdraw")
    )
    builder.row(get_back_button("main"))
    text = f"<b>#{player_num} {display_name}</b>\n\n<blockquote><b>💳 Баланс — {balance:.2f} USDT</b></blockquote>"
    await message.answer(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)

@dp.message(F.text.startswith("/givebalance"))
async def give_balance_handler(message: Message, state: FSMContext):
    if message.from_user.id not in config.ADMINS:
        return
    try:
        parts = message.text.split()
        if len(parts) != 3:
            return await message.answer("❌ Формат: <code>/givebalance айди сумма</code>")
        target_id = int(parts[1])
        amount = float(parts[2])
        if amount is None or math.isnan(amount) or amount <= 0:
            return await message.answer("❌ Сумма должна быть положительным числом")
        if db.add_balance(target_id, amount):
            await message.answer(f"✅ Баланс игрока <code>{target_id}</code> изменен на <b>{amount:.2f} USDT</b>")
        else:
            await message.answer(f"❌ Игрок <code>{target_id}</code> не найден.")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

@dp.message(F.text.lower().regexp(r"^дать\s+(\d+[\.,]?\d*)"))
async def transfer_balance_handler(message: Message, state: FSMContext):
    await state.clear()
    if not message.reply_to_message:
        return
    if message.reply_to_message.from_user.is_bot:
        return await message.answer("❌ Нельзя передавать монеты ботам!")

    sender_id = message.from_user.id
    recipient_id = message.reply_to_message.from_user.id
    if sender_id == recipient_id:
        return await message.answer("❌ Нельзя передавать монеты самому себе!")

    match = re.search(r"(?i)дать\s+(\d+[\.,]?\d*)", message.text)
    if not match:
        return
    try:
        amount = float(match.group(1).replace(",", "."))
        if math.isnan(amount) or amount <= 0:
            raise ValueError
    except ValueError:
        return

    if amount < 0.1:
        return await message.answer("❌ Минимальная сумма перевода — <b>0.10 USDT</b>", parse_mode=ParseMode.HTML)

    sender_data = db.get_user_data(sender_id)
    if not sender_data:
        db.register_user(sender_id, message.from_user.username or message.from_user.first_name)
        sender_data = db.get_user_data(sender_id)
    if sender_data[3] < amount:
        return await message.answer("❌ У вас недостаточно средств!")

    recipient_data = db.get_user_data(recipient_id)
    if not recipient_data:
        db.register_user(recipient_id, message.reply_to_message.from_user.username or message.reply_to_message.from_user.first_name)

    if db.add_balance(sender_id, -amount, is_withdraw=True):
        db.add_balance(recipient_id, amount)
        sender_name = message.from_user.mention_html()
        recipient_name = message.reply_to_message.from_user.mention_html()
        await message.answer(f"🎊 {sender_name} передаёт <b>{amount:,.2f} USDT</b> {recipient_name}", parse_mode=ParseMode.HTML)

# ==================== ОСНОВНЫЕ CALLBACK ОБРАБОТЧИКИ ====================

@dp.callback_query(F.data.startswith("back:"))
async def back_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    previous_menu = callback.data.split(":")[1]
    
    if previous_menu == "main":
        await command_start_handler(callback.message)
    elif previous_menu == "checks_menu":
        await checks_menu_callback(callback, state)
    elif previous_menu == "profile":
        await profile_callback(callback, state)
    elif previous_menu == "play":
        await play_callback(callback, state)
    elif previous_menu == "modes_menu":
        await modes_menu_handler(callback, state)
    elif previous_menu == "game_mines":
        await game_mines_handler(callback, state)
    elif previous_menu == "game_tower":
        await game_tower_handler(callback, state)
    elif previous_menu == "custom_games":
        await custom_games_menu_handler(callback, state)
    elif previous_menu == "dice_menu":
        await dice_menu_handler(callback, state)
    elif previous_menu == "chats":
        await chats_callback(callback, state)
    elif previous_menu == "language":
        await language_menu_callback(callback, state)
    elif previous_menu == "privacy":
        await privacy_callback(callback, state)
    elif previous_menu == "referral":
        await referral_callback(callback, state)
    elif previous_menu == "stats":
        await stats_callback(callback, state)
    elif previous_menu == "deposit":
        await deposit_callback(callback, state)
    elif previous_menu == "withdraw":
        await withdraw_callback(callback, state)
    else:
        await command_start_handler(callback.message)

@dp.callback_query(F.data == "profile")
async def profile_callback(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    
    user_data = db.get_user_data(user_id)
    if not user_data:
        db.register_user(user_id, callback.from_user.username or callback.from_user.first_name)
        user_data = db.get_user_data(user_id)

    reg_date_str, player_num, lang, balance, privacy_type, nickname, username, total_bets, total_turnover, total_deposits, total_withdrawals, current_bet, referrer_id, ref_balance, total_ref_earned, rank_id, mines_count, tower_bombs = user_data
    
    rank_progress = (total_turnover % 1000) / 1000 * 100
    current_rank_name = RANKS[min(rank_id, len(RANKS)-1)]
    next_rank_name = RANKS[min(rank_id + 1, len(RANKS)-1)]
    filled_chars = int(rank_progress // 10)
    progress_bar = "⬜" * filled_chars + "⬛" * (10 - filled_chars)
    
    reg_date = datetime.strptime(reg_date_str, "%Y-%m-%d %H:%M:%S")
    days_delta = (datetime.now() - reg_date).days
    
    if lang == "ru":
        if days_delta == 0:
            days_text = "меньше дня"
        elif days_delta % 10 == 1 and days_delta % 100 != 11:
            days_text = f"{days_delta} день"
        elif days_delta % 10 in [2, 3, 4] and days_delta % 100 not in [12, 13, 14]:
            days_text = f"{days_delta} дня"
        else:
            days_text = f"{days_delta} дней"
    else:
        days_text = "less than a day" if days_delta == 0 else ("1 day" if days_delta == 1 else f"{days_delta} days")

    display_name = get_user_display_name(user_id, callback.from_user.first_name)
    profile_template = get_text(user_id, "profile")
    profile_text = profile_template.format(
        player_id=player_num, days=days_text, balance=balance, name=display_name,
        turnover=total_turnover, bets=total_bets, rank_progress=rank_progress,
        current_rank=current_rank_name, next_rank=next_rank_name, progress_bar=progress_bar
    )

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=get_btn(user_id, "deposit"), callback_data="deposit"),
        InlineKeyboardButton(text=get_btn(user_id, "withdraw"), callback_data="withdraw")
    )
    builder.row(
        InlineKeyboardButton(text=get_btn(user_id, "stats"), callback_data="stats"),
        InlineKeyboardButton(text=get_btn(user_id, "privacy"), callback_data="privacy")
    )
    builder.row(get_back_button("main"))
    
    await callback.message.edit_text(profile_text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data == "stats")
async def stats_callback(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    user_data = db.get_user_data(user_id)
    
    reg_date_str, player_num, lang, balance, privacy_type, nickname, username, total_bets, total_turnover, total_deposits, total_withdrawals, current_bet, referrer_id, ref_balance, total_ref_earned, rank_id, mines_count, tower_bombs = user_data
    
    reg_date = datetime.strptime(reg_date_str, "%Y-%m-%d %H:%M:%S")
    days_delta = (datetime.now() - reg_date).days
    
    if lang == "ru":
        if days_delta == 0:
            days_word = "дней"
        elif days_delta % 10 == 1 and days_delta % 100 != 11:
            days_word = "день"
        elif days_delta % 10 in [2, 3, 4] and days_delta % 100 not in [12, 13, 14]:
            days_word = "дня"
        else:
            days_word = "дней"
    else:
        days_word = "days" if days_delta != 1 else "day"
    
    display_name = get_user_display_name(user_id, callback.from_user.first_name)
    stats_text = get_text(user_id, "stats_text").format(
        name=display_name, bets=total_bets, turnover=total_turnover,
        days=days_delta, days_label=days_word,
        deposits=total_deposits, withdrawals=total_withdrawals
    )
    
    builder = InlineKeyboardBuilder()
    builder.row(get_back_button("profile"))
    
    await callback.message.edit_text(stats_text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data == "deposit")
async def deposit_callback(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=get_btn(user_id, "crypto_bot"), callback_data="deposit_cryptobot"))
    builder.row(get_back_button("profile"))
    await callback.message.edit_text(get_text(user_id, "deposit_method"), reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data == "deposit_cryptobot")
async def deposit_cryptobot_callback(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    await state.update_data(method="cryptobot")
    await state.set_state(DepositState.entering_amount)
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_action"))
    await callback.message.edit_text(
        get_text(user_id, "enter_deposit_amount").format(min_amount=config.MIN_DEPOSIT),
        reply_markup=builder.as_markup(),
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data == "cancel_action")
async def cancel_action_callback(callback: CallbackQuery, state: FSMContext):
    await state.set_state(None)
    await profile_callback(callback, state)

# --- ПОПОЛНЕНИЕ ---
@dp.message(DepositState.entering_amount)
async def process_deposit_amount(message: Message, state: FSMContext):
    user_id = message.from_user.id
    raw_text = message.text.replace(",", ".").strip()
    
    if not raw_text:
        return await message.answer("❌ Введите сумму числом")
    
    try:
        amount = float(raw_text)
        if math.isnan(amount) or amount <= 0:
            raise ValueError
    except ValueError:
        return await message.answer("❌ Введите корректную сумму (число больше 0)")

    if amount < config.MIN_DEPOSIT:
        return await message.answer(get_text(user_id, "error_min_deposit").format(min_amount=config.MIN_DEPOSIT))
    if amount > 1000000:
        return await message.answer("❌ Сумма слишком велика (максимум 1 000 000 USDT)")

    data = await state.get_data()
    method = data.get("method")
    
    pay_url, invoice_id = await crypto_pay.create_invoice(amount)
    if not pay_url:
        pay_url = "https://t.me/CryptoBot?start=IVVQxQuLnQA"
        invoice_id = "test_id"

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=get_btn(user_id, "pay").format(amount=amount), url=pay_url))
    builder.row(InlineKeyboardButton(text=get_text(user_id, "check_payment"), callback_data=f"check:{method}:{invoice_id}:{amount}"))
    builder.row(InlineKeyboardButton(text=get_btn(user_id, "change_amount"), callback_data="deposit_cryptobot"))
    builder.row(get_back_button("deposit"))
    
    await message.answer(get_text(user_id, "deposit_created"), reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
    await state.set_state(None)

@dp.callback_query(F.data.startswith("check:"))
async def check_payment_callback(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    method = parts[1]
    invoice_id = parts[2]
    amount = float(parts[3])
    user_id = callback.from_user.id

    is_paid = False
    if invoice_id != "test_id":
        invoice = await crypto_pay.get_invoice(invoice_id)
        if invoice and invoice.get("status") == "paid":
            is_paid = True

    if is_paid:
        if db.is_invoice_processed(invoice_id):
            return await callback.answer("❌ Этот счет уже был зачислен!", show_alert=True)
        db.mark_invoice_processed(invoice_id, user_id, amount, method)
        db.add_balance(user_id, amount, is_deposit=True)
        await callback.message.edit_text(get_text(user_id, "payment_success").format(amount=amount), parse_mode=ParseMode.HTML)
        await send_alert(callback.bot, user_id, amount, "deposit")
    else:
        await callback.answer(get_text(user_id, "payment_not_found"), show_alert=True)

@dp.callback_query(F.data == "withdraw")
async def withdraw_callback(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    user_data = db.get_user_data(user_id)
    balance = user_data[3] if user_data else 0.0
    
    if balance < config.MIN_WITHDRAW:
        return await callback.answer(get_text(user_id, "error_min_withdraw").format(min_amount=config.MIN_WITHDRAW), show_alert=True)

    await state.set_state(WithdrawState.entering_amount)
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_action"))
    await callback.message.edit_text(
        get_text(user_id, "enter_withdraw_amount").format(min_amount=config.MIN_WITHDRAW),
        reply_markup=builder.as_markup(),
        parse_mode=ParseMode.HTML
    )

# --- ВЫВОД ---
@dp.message(WithdrawState.entering_amount)
async def process_withdraw_amount(message: Message, state: FSMContext):
    user_id = message.from_user.id
    user_data = db.get_user_data(user_id)
    balance = user_data[3] if user_data else 0.0

    raw_text = message.text.replace("$", "").replace(",", ".").strip()
    if not raw_text:
        return await message.answer("❌ Введите сумму числом")
    
    try:
        amount = float(raw_text)
        if math.isnan(amount) or amount <= 0:
            raise ValueError
    except ValueError:
        return await message.answer(get_text(user_id, "enter_withdraw_amount").format(min_amount=config.MIN_WITHDRAW))

    if amount < config.MIN_WITHDRAW:
        return await message.answer(get_text(user_id, "error_min_withdraw").format(min_amount=config.MIN_WITHDRAW))
    if amount > 1000000:
        return await message.answer("❌ Сумма слишком велика.")
    if amount > balance:
        return await message.answer(f"❌ Недостаточно средств. Ваш баланс: {balance:.2f} USDT")

    await state.update_data(amount=amount)
    await state.set_state(WithdrawState.choosing_method)
    
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🤖 Crypto Bot", callback_data="withdraw_method:cryptobot"))
    builder.row(get_back_button("withdraw"))
    await message.answer("💰 Выберите метод вывода:", reply_markup=builder.as_markup())

@dp.callback_query(WithdrawState.choosing_method, F.data.startswith("withdraw_method:"))
async def withdraw_method_callback(callback: CallbackQuery, state: FSMContext):
    method = callback.data.split(":")[1]
    await state.update_data(method=method)
    user_id = callback.from_user.id
    data = await state.get_data()
    
    if data.get("processing_withdraw"):
        return await callback.answer()
    await state.update_data(processing_withdraw=True)
    amount = data.get("amount")

    try:
        if not db.add_balance(user_id, -amount, is_withdraw=True):
            await state.update_data(processing_withdraw=False)
            await state.set_state(None)
            return await callback.answer("❌ Ошибка при списании баланса.", show_alert=True)
        
        transfer_success, _ = await crypto_pay.transfer(user_id, amount)
        if transfer_success:
            await callback.message.edit_text(f"✅ Вывод <b>{amount:.2f} USDT</b> успешно выполнен!", parse_mode=ParseMode.HTML)
            await send_alert(callback.bot, user_id, amount, "withdraw")
            await state.update_data(processing_withdraw=False)
            await state.set_state(None)
            return
        
        check_url = await crypto_pay.create_check(amount, pin_to_user_id=user_id)
        if check_url:
            await callback.message.edit_text(
                f"✅ Чек на сумму <b>{amount:.2f} USDT</b> успешно создан!\n\n🔗 Ссылка: {check_url}",
                reply_markup=InlineKeyboardBuilder().row(InlineKeyboardButton(text="🎁 Забрать", url=check_url)).as_markup(),
                parse_mode=ParseMode.HTML
            )
            await send_alert(callback.bot, user_id, amount, "withdraw")
            await state.update_data(processing_withdraw=False)
            await state.set_state(None)
            return
        
        db.add_balance(user_id, amount)
        db.cursor.execute("UPDATE users SET total_withdrawals = total_withdrawals - ? WHERE user_id = ?", (amount, user_id))
        db.conn.commit()
        
        await callback.message.edit_text(
            "Заявка на вывод подана, ожидайте!\n🛡 Мы отправили запрос администраторам, они выплатят вам вручную!",
            parse_mode=ParseMode.HTML
        )
        
        user_name = get_user_display_name(user_id)
        admin_text = f"⚠️ <b>ЗАЯВКА НА ВЫВОД</b>\n\n👤 Игрок: {user_name}\n💵 Сумма: <b>{amount:.2f} USDT</b>"
        for admin_id in config.ADMINS:
            try:
                await callback.bot.send_message(admin_id, admin_text, parse_mode=ParseMode.HTML)
            except Exception as e:
                logger.error(f"Failed to send admin alert: {e}")
        
        await state.update_data(processing_withdraw=False)
        await state.set_state(None)
    except Exception as e:
        logger.error(f"Error during withdrawal: {e}")
        db.add_balance(user_id, amount)
        await callback.answer("❌ Ошибка. Баланс возвращен.", show_alert=True)
        await state.update_data(processing_withdraw=False)
        await state.set_state(None)

@dp.callback_query(F.data == "chats")
async def chats_callback(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=get_btn(user_id, "main_chat"), url=config.CHAT_URL))
    builder.row(get_back_button("main"))
    await callback.message.edit_text(get_text(user_id, "chats"), reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data == "language")
async def language_menu_callback(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    current_lang = get_lang(user_id)
    
    builder = InlineKeyboardBuilder()
    ru_text = get_btn(user_id, "lang_ru") + (" ✅" if current_lang == "ru" else "")
    en_text = get_btn(user_id, "lang_en") + (" ✅" if current_lang == "en" else "")
    builder.row(
        InlineKeyboardButton(text=ru_text, callback_data="set_lang_ru"),
        InlineKeyboardButton(text=en_text, callback_data="set_lang_en")
    )
    builder.row(get_back_button("main"))
    await callback.message.edit_text(get_text(user_id, "language_select"), reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data.startswith("set_lang_"))
async def set_language_callback(callback: CallbackQuery, state: FSMContext):
    new_lang = callback.data.split("_")[-1]
    user_id = callback.from_user.id
    db.set_lang(user_id, new_lang)
    await language_menu_callback(callback, state)

@dp.callback_query(F.data == "privacy")
async def privacy_callback(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    user_data = db.get_user_data(user_id)
    if not user_data:
        return
    
    reg_date, player_num, lang, balance, privacy_type, nickname, username, *rest = user_data
    
    display_modes = {
        "username": f"@{username}" if username else "Username",
        "name": callback.from_user.first_name,
        "id": f"Игрок #{player_num}",
        "nickname": nickname if nickname else "Псевдоним"
    }
    current_display = display_modes.get(privacy_type, "Username")
    
    builder = InlineKeyboardBuilder()
    btn_user = ("✅ " if privacy_type == "username" else "") + (f"@{username}" if username else "Username")
    btn_name = ("✅ " if privacy_type == "name" else "") + callback.from_user.first_name
    builder.row(
        InlineKeyboardButton(text=btn_user, callback_data="set_priv:username"),
        InlineKeyboardButton(text=btn_name, callback_data="set_priv:name")
    )
    btn_id = ("✅ " if privacy_type == "id" else "") + f"Игрок #{player_num}"
    btn_nick = ("✅ " if privacy_type == "nickname" else "") + (nickname if nickname else "Псевдоним")
    builder.row(
        InlineKeyboardButton(text=btn_id, callback_data="set_priv:id"),
        InlineKeyboardButton(text=btn_nick, callback_data="set_priv:nickname")
    )
    builder.row(InlineKeyboardButton(text=get_btn(user_id, "settings"), callback_data="privacy_settings"))
    builder.row(get_back_button("profile"))
    
    await callback.message.edit_text(
        get_text(user_id, "privacy").format(display_mode=current_display),
        reply_markup=builder.as_markup(),
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data.startswith("set_priv:"))
async def set_privacy_type_callback(callback: CallbackQuery, state: FSMContext):
    privacy_type = callback.data.split(":")[1]
    user_id = callback.from_user.id
    db.set_privacy(user_id, privacy_type)
    await callback.answer(get_text(user_id, "privacy_updated"))
    await privacy_callback(callback, state)

@dp.callback_query(F.data == "privacy_settings")
async def privacy_settings_callback(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    await state.set_state(PrivacyState.entering_nickname)
    await callback.message.edit_text(get_text(user_id, "privacy_set_nickname"), parse_mode=ParseMode.HTML)

@dp.message(PrivacyState.entering_nickname)
async def process_nickname(message: Message, state: FSMContext):
    user_id = message.from_user.id
    nickname = message.text[:15]
    db.set_nickname(user_id, nickname)
    db.set_privacy(user_id, "nickname")
    await state.set_state(None)
    await message.answer(get_text(user_id, "nickname_updated"))
    await command_start_handler(message)

@dp.callback_query(F.data == "referral")
async def referral_callback(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    user_data = db.get_user_data(user_id)
    if not user_data:
        return
        
    ref_count = db.get_ref_stats(user_id)
    ref_balance = user_data[13]
    total_earned = user_data[14]
    
    bot_info = await callback.bot.get_me()
    ref_link = f"t.me/{bot_info.username}?start=invite_{user_id}"
    
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=f"Забрать на баланс · {ref_balance:.2f} USDT", callback_data="claim_ref"))
    builder.row(InlineKeyboardButton(text="Пригласить друга", switch_inline_query=f"Играй со мной! {ref_link}"))
    builder.row(InlineKeyboardButton(text="Подробнее", url=config.CHANNEL_URL))
    builder.row(get_back_button("main"))

    text = (
        f"<b>| 💰 Реф. система  ❞</b>\n\n"
        f"1 📈 5% | {ref_count} 👤 | {ref_balance:.2f} USDT | {total_earned:.2f} USDT\n\n"
        f"Ваша ссылка\n<code>{ref_link}</code>\n\nОбщий доход\n{total_earned:.2f} USDT"
    )
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data == "claim_ref")
async def claim_ref_callback(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    claimed = db.claim_ref_balance(user_id)
    if claimed > 0:
        await callback.answer(f"✅ Выведено {claimed:.2f} USDT на основной баланс!", show_alert=True)
        await referral_callback(callback, state)
    else:
        await callback.answer("❌ На балансе меньше 1 USDT или он пуст.", show_alert=True)

@dp.callback_query(F.data == "play")
async def play_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = callback.from_user.id
    
    user_data = db.get_user_data(user_id)
    if not user_data:
        return
        
    balance = user_data[3]
    current_bet = user_data[11]
    
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=get_btn(user_id, "game_dice"), callback_data="game:dice_emoji"),
        InlineKeyboardButton(text=get_btn(user_id, "game_soccer"), callback_data="game:soccer"),
        InlineKeyboardButton(text=get_btn(user_id, "game_slots"), callback_data="game:slots")
    )
    builder.row(
        InlineKeyboardButton(text=get_btn(user_id, "provider_tg"), callback_data="game:dice"),
        InlineKeyboardButton(text=get_btn(user_id, "provider_custom"), callback_data="custom_games")
    )
    builder.row(
        InlineKeyboardButton(text=get_btn(user_id, "modes"), callback_data="modes_menu")
    )
    builder.row(get_back_button("main"))

    await callback.message.edit_text(
        get_text(user_id, "play").format(balance=balance, bet=current_bet), 
        reply_markup=builder.as_markup(), 
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data == "modes_menu")
async def modes_menu_handler(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    user_data = db.get_user_data(user_id)
    if not user_data:
        return
        
    balance = user_data[3]
    current_bet = user_data[11]
    
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=get_btn(user_id, "game_mines"), callback_data="game_mines"),
        InlineKeyboardButton(text=get_btn(user_id, "game_tower"), callback_data="game_tower")
    )
    builder.row(get_back_button("play"))

    await callback.message.edit_text(
        get_text(user_id, "modes_menu").format(balance=balance, bet=current_bet), 
        reply_markup=builder.as_markup(), 
        parse_mode=ParseMode.HTML
    )

# ==================== ИГРА МИНЫ ====================
def get_mines_coef(step, total_mines, commission=0.94):
    if step == 0:
        return 1.0
    if step > (25 - total_mines):
        return 0.0
    c = 1.0
    for i in range(step):
        c *= (25 - i) / (25 - total_mines - i)
    return c * commission

def get_mines_coefs_line(mines_count, current_step=0, limit=7):
    coefs = []
    start_step = max(1, current_step - 2)
    for i in range(start_step, start_step + limit):
        if i > (25 - mines_count):
            break
        val = get_mines_coef(i, mines_count)
        if i == current_step:
            coefs.append(f"<b>x{val:.2f}</b>")
        else:
            coefs.append(f"x{val:.2f}")
    line = " → ".join(coefs)
    if start_step + limit <= (25 - mines_count):
        line += " ... 🎀"
    else:
        line += " 🎀"
    return line

async def show_mines_menu(message: Message, user_id: int, state: FSMContext, edit: bool = True):
    user_data = db.get_user_data(user_id)
    mines_count = user_data[16] if user_data else 3
    
    player_id = user_data[1]
    balance = user_data[3]
    bet = user_data[11]
    
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=f"🕹️ Играть · {bet:,.2f} USDT", callback_data=f"start_mines:{mines_count}"))
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data="modes_menu"),
        InlineKeyboardButton(text=f"Изменить · {mines_count} 💣", callback_data="select_mines_count")
    )
    
    text = get_text(user_id, "mines_main").format(
        player_id=player_id, balance=balance, bet=bet, mines=mines_count
    )
    
    if edit:
        await message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
    else:
        await message.answer(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data == "game_mines")
async def game_mines_handler(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = callback.from_user.id
    await show_mines_menu(callback.message, user_id, state, edit=True)

@dp.callback_query(F.data == "select_mines_count")
async def select_mines_count_handler(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    user_data = db.get_user_data(user_id)
    current_mines = user_data[16] if user_data else 3
    
    builder = InlineKeyboardBuilder()
    for i in range(2, 25):
        if i == current_mines:
            builder.add(InlineKeyboardButton(text=f"✅ {i} 💣", callback_data=f"set_mines:{i}"))
        else:
            builder.add(InlineKeyboardButton(text=f"{i} 💣", callback_data=f"set_mines:{i}"))
    builder.adjust(5)
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="game_mines"))
    
    coefs_line = get_mines_coefs_line(current_mines, limit=8)
    text = get_text(user_id, "mines_select").format(mines=current_mines, coefs=coefs_line)
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data.startswith("set_mines:"))
async def set_mines_handler(callback: CallbackQuery, state: FSMContext):
    count = int(callback.data.split(":")[1])
    user_id = callback.from_user.id
    db.set_mines_count(user_id, count)
    await select_mines_count_handler(callback, state)

@dp.callback_query(F.data.startswith("start_mines:"))
async def start_mines_handler(callback: CallbackQuery, state: FSMContext):
    if await state.get_state() == MinesState.playing:
        return await callback.answer("❌ Вы уже в игре!", show_alert=True)
    await state.set_state(MinesState.playing)
    
    mines_count = int(callback.data.split(":")[1])
    user_id = callback.from_user.id
    user_data = db.get_user_data(user_id)
    balance = user_data[3]
    bet = user_data[11]
    
    if balance < bet:
        await state.clear()
        return await callback.answer("❌ Недостаточно средств!", show_alert=True)
    if not db.add_balance(user_id, -bet, is_bet=True):
        await state.clear()
        return await callback.answer("❌ Ошибка при списании ставки!", show_alert=True)
        
    msg_id = str(callback.message.message_id)
    field = [0] * 25
    mines_indices = random.sample(range(25), mines_count)
    for idx in mines_indices:
        field[idx] = 1
        
    game_data = {
        "type": "mines", "mines_count": mines_count, "field": field,
        "bet": bet, "revealed": [], "processing_click": False
    }
    await state.update_data({f"game_{msg_id}": game_data})
    await show_mines_field(callback.message, user_id, state)

async def show_mines_field(message: Message, user_id: int, state: FSMContext):
    msg_id = str(message.message_id)
    all_data = await state.get_data()
    game_data = all_data.get(f"game_{msg_id}")
    if not game_data:
        return
        
    revealed = game_data.get("revealed", [])
    mines_count = game_data.get("mines_count")
    bet = game_data.get("bet")
    current_coef = get_mines_coef(len(revealed), mines_count)
    win_amount = bet * current_coef
    
    builder = InlineKeyboardBuilder()
    for i in range(25):
        if i in revealed:
            builder.add(InlineKeyboardButton(text="💎", callback_data="none"))
        else:
            builder.add(InlineKeyboardButton(text="🌑", callback_data=f"mine_click:{i}"))
    builder.adjust(5)
    builder.row(InlineKeyboardButton(text=f"⚡ Забрать · {win_amount:,.2f} USDT", callback_data="mine_cashout"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="game_mines"))

    coefs_line = get_mines_coefs_line(mines_count, len(revealed) + 1)
    text = get_text(user_id, "mines_playing").format(
        mines=mines_count, bet=bet, coef=current_coef, win=win_amount, coefs=coefs_line
    )
    await message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data.startswith("mine_click:"))
async def mine_click_handler(callback: CallbackQuery, state: FSMContext):
    idx = int(callback.data.split(":")[1])
    user_id = callback.from_user.id
    msg_id = str(callback.message.message_id)
    all_data = await state.get_data()
    game_data = all_data.get(f"game_{msg_id}")
    
    if not game_data or game_data.get("type") != "mines":
        return await callback.answer("❌ Игра уже завершена!", show_alert=True)
    if game_data.get("processing_click"):
        return await callback.answer()
        
    game_data["processing_click"] = True
    await state.update_data({f"game_{msg_id}": game_data})

    try:
        field = game_data["field"]
        revealed = game_data["revealed"]
        if idx in revealed:
            return await callback.answer("❌ Эта ячейка уже открыта!", show_alert=True)
        
        if field[idx] == 1:
            builder = InlineKeyboardBuilder()
            for i in range(25):
                if i == idx:
                    builder.add(InlineKeyboardButton(text="💥", callback_data="none"))
                elif field[i] == 1:
                    builder.add(InlineKeyboardButton(text="💣", callback_data="none"))
                elif i in revealed:
                    builder.add(InlineKeyboardButton(text="💎", callback_data="none"))
                else:
                    builder.add(InlineKeyboardButton(text="🌑", callback_data="none"))
            builder.adjust(5)
            builder.row(InlineKeyboardButton(text="🔄 Играть еще", callback_data="game_mines"))
            builder.row(InlineKeyboardButton(text=get_btn(user_id, "back"), callback_data="game_mines"))
            
            all_data = await state.get_data()
            if f"game_{msg_id}" in all_data:
                del all_data[f"game_{msg_id}"]
                await state.set_data(all_data)
                
            user_name = get_user_display_name(user_id, callback.from_user.first_name)
            new_balance = db.get_user_data(user_id)[3]
            text = (
                f"👤 <b>{user_name}</b>\n"
                f"<b>Проигрывает в игре 💣 на {game_data['bet']:.2f} USDT</b>\n"
                f"<blockquote><b>× 0 🎄 Выигрыш 0.00 USDT ❞</b></blockquote>\n\n"
                f"<b>📋 Баланс {new_balance:.2f} USDT</b>"
            )
            await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
            await state.clear()
        else:
            revealed.append(idx)
            game_data["revealed"] = revealed
            game_data["processing_click"] = False
            await state.update_data({f"game_{msg_id}": game_data})
            if len(revealed) == (25 - game_data["mines_count"]):
                await mine_cashout_handler(callback, state)
            else:
                await show_mines_field(callback.message, user_id, state)
    finally:
        all_data = await state.get_data()
        if f"game_{msg_id}" in all_data:
            current_game = all_data[f"game_{msg_id}"]
            if current_game.get("processing_click"):
                current_game["processing_click"] = False
                await state.update_data({f"game_{msg_id}": current_game})

@dp.callback_query(F.data == "mine_cashout")
async def mine_cashout_handler(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    msg_id = str(callback.message.message_id)
    all_data = await state.get_data()
    game_data = all_data.get(f"game_{msg_id}")
    
    if not game_data or game_data.get("type") != "mines":
        return await callback.answer("❌ Игра уже завершена!", show_alert=True)
    if game_data.get("processing_click"):
        return await callback.answer()
        
    game_data["processing_click"] = True
    await state.update_data({f"game_{msg_id}": game_data})

    try:
        revealed = game_data["revealed"]
        mines_count = game_data["mines_count"]
        bet = game_data["bet"]
        
        if not revealed:
            game_data["processing_click"] = False
            await state.update_data({f"game_{msg_id}": game_data})
            return await callback.answer("❌ Откройте хотя бы одну ячейку!", show_alert=True)

        coef = get_mines_coef(len(revealed), mines_count)
        win_amount = bet * coef
        
        if not db.add_balance(user_id, win_amount):
            game_data["processing_click"] = False
            await state.update_data({f"game_{msg_id}": game_data})
            return await callback.answer("❌ Ошибка при начислении выигрыша!", show_alert=True)

        new_balance = db.get_user_data(user_id)[3]
        field = game_data["field"]
        builder = InlineKeyboardBuilder()
        for i in range(25):
            if i in revealed:
                builder.add(InlineKeyboardButton(text="💎", callback_data="none"))
            elif field[i] == 1:
                builder.add(InlineKeyboardButton(text="💣", callback_data="none"))
            else:
                builder.add(InlineKeyboardButton(text="🌑", callback_data="none"))
        builder.adjust(5)
        builder.row(InlineKeyboardButton(text="🔄 Играть еще", callback_data="game_mines"))
        builder.row(InlineKeyboardButton(text=get_btn(user_id, "back"), callback_data="game_mines"))

        all_data = await state.get_data()
        if f"game_{msg_id}" in all_data:
            del all_data[f"game_{msg_id}"]
            await state.set_data(all_data)
            
        user_name = get_user_display_name(user_id, callback.from_user.first_name)
        text = (
            f"<b>👤 {user_name}</b>\n"
            f"<b>Побеждает в игре 💣 на {bet:.2f} USDT</b>\n"
            f"<blockquote><b>× {coef:.2f} 🎄 Выигрыш {win_amount:.2f} USDT ❞</b></blockquote>\n\n"
            f"<b>📋 Баланс {new_balance:.2f} USDT</b>"
        )
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
        if win_amount >= 50:
            await send_alert(callback.bot, user_id, win_amount, "win")
        await state.clear()
    finally:
        all_data = await state.get_data()
        if f"game_{msg_id}" in all_data:
            current_game = all_data[f"game_{msg_id}"]
            if current_game.get("processing_click"):
                current_game["processing_click"] = False
                await state.update_data({f"game_{msg_id}": current_game})

# ==================== ИГРА БАШНЯ ====================
TOWER_COEFS = {
    1: [1.17, 1.47, 1.84, 2.29, 2.87],
    2: [1.46, 2.19, 3.29, 4.93, 7.40],
    3: [1.95, 3.90, 7.80, 15.60, 31.20],
    4: [2.92, 8.76, 26.28, 78.84, 236.52]
}

async def show_tower_menu(message: Message, user_id: int, state: FSMContext, edit=True):
    user_data = db.get_user_data(user_id)
    bombs_count = user_data[17] if user_data else 1
    
    username = user_data[6] or "Игрок"
    balance = user_data[3]
    bet = user_data[11]
    
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=f"🕹 Играть · {bet:,.2f} USDT", callback_data=f"tower_start_game:{bombs_count}"))
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data="modes_menu"),
        InlineKeyboardButton(text=f"Изменить · {bombs_count} 💣", callback_data="tower_select_bombs")
    )
    
    coefs_line = " → ".join([f"x{c:.2f}" for c in TOWER_COEFS[bombs_count]])
    text = (
        f"🏙 <b>Башня</b>\n\n"
        f"👤 <b>{username}</b>\n"
        f"<blockquote>👛 <b>Баланс — {balance:,.2f} USDT</b>\n"
        f"<b>Ставка — {bet:,.2f} USDT</b></blockquote>\n\n"
        f"Выбрано — {bombs_count} 💣\n"
        f"<blockquote>{coefs_line} ❞</blockquote>"
    )
    
    if edit:
        await message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
    else:
        await message.answer(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data == "game_tower")
async def game_tower_handler(callback: CallbackQuery, state: FSMContext):
    if await state.get_state() == TowerState.playing:
        return await callback.answer("❌ Вы уже в игре!", show_alert=True)
    await state.set_state(TowerState.playing)
    user_id = callback.from_user.id
    await show_tower_menu(callback.message, user_id, state, edit=True)

@dp.callback_query(F.data == "tower_select_bombs")
async def tower_select_bombs_handler(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    user_data = db.get_user_data(user_id)
    current_bombs = user_data[17] if user_data else 1
    
    builder = InlineKeyboardBuilder()
    for i in range(1, 5):
        if i == current_bombs:
            builder.add(InlineKeyboardButton(text=f"✅ {i} 💣", callback_data=f"tower_set_bombs:{i}"))
        else:
            builder.add(InlineKeyboardButton(text=f"{i} 💣", callback_data=f"tower_set_bombs:{i}"))
    builder.adjust(4)
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="game_tower"))
    
    coefs_line = " → ".join([f"x{c:.2f}" for c in TOWER_COEFS[current_bombs]])
    text = (
        f"💣 <b>Выберите количество</b>\n\n"
        f"Выбрано — {current_bombs} 💣\n\n"
        f"<blockquote>{coefs_line} ❞</blockquote>"
    )
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data.startswith("tower_set_bombs:"))
async def tower_set_bombs_handler(callback: CallbackQuery, state: FSMContext):
    count = int(callback.data.split(":")[1])
    user_id = callback.from_user.id
    db.set_tower_bombs(user_id, count)
    await tower_select_bombs_handler(callback, state)

@dp.callback_query(F.data.startswith("tower_start_game:"))
async def tower_start_game_handler(callback: CallbackQuery, state: FSMContext):
    bombs_count = int(callback.data.split(":")[1])
    user_id = callback.from_user.id
    
    user_data = db.get_user_data(user_id)
    balance = user_data[3]
    bet = user_data[11]
    
    if balance < bet:
        return await callback.answer("❌ Недостаточно средств!", show_alert=True)
    if not db.add_balance(user_id, -bet, is_bet=True):
        return await callback.answer("❌ Ошибка при списании ставки!", show_alert=True)
        
    msg_id = str(callback.message.message_id)
    field = []
    for _ in range(5):
        level = [0] * 5
        actual_bombs = min(bombs_count, 4)
        bombs_indices = random.sample(range(5), actual_bombs)
        for idx in bombs_indices:
            level[idx] = 1
        field.append(level)
        
    game_data = {
        "type": "tower", "tower_bombs": bombs_count, "tower_field": field,
        "tower_bet": bet, "tower_level": 0, "tower_revealed": [], "processing_click": False
    }
    await state.update_data({f"game_{msg_id}": game_data})
    await show_tower_field(callback.message, user_id, state)

async def show_tower_field(message: Message, user_id: int, state: FSMContext):
    msg_id = str(message.message_id)
    all_data = await state.get_data()
    game_data = all_data.get(f"game_{msg_id}")
    if not game_data:
        return
        
    level = game_data.get("tower_level", 0)
    bombs_count = game_data.get("tower_bombs", 1)
    bet = game_data.get("tower_bet")
    revealed = game_data.get("tower_revealed", [])
    
    coefs = TOWER_COEFS[bombs_count]
    current_coef = coefs[level-1] if level > 0 else 1.0
    win_amount = bet * current_coef
    
    builder = InlineKeyboardBuilder()
    for l in range(4, -1, -1):
        builder.add(InlineKeyboardButton(text=f"x{coefs[l]:.2f}", callback_data="none"))
        for i in range(5):
            if l < level:
                chosen_idx = revealed[l]
                if i == chosen_idx:
                    builder.add(InlineKeyboardButton(text="💎", callback_data="none"))
                else:
                    builder.add(InlineKeyboardButton(text="🌑", callback_data="none"))
            elif l == level:
                builder.add(InlineKeyboardButton(text="🌍", callback_data=f"tower_click:{l}:{i}"))
            else:
                builder.add(InlineKeyboardButton(text="🌑", callback_data="none"))
    builder.adjust(6)
    if level > 0:
        builder.row(InlineKeyboardButton(text=f"⚡ Забрать · {win_amount:,.2f} USDT", callback_data="tower_cashout"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="game_tower"))

    text = f"🏙 <b>Башня · {bombs_count} 💣</b>\n\n<b>{bet:,.2f} USDT × {current_coef:.2f} ➔ {win_amount:,.2f} USDT</b>"
    await message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data.startswith("tower_click:"))
async def tower_click_handler(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    level = int(parts[1])
    idx = int(parts[2])
    user_id = callback.from_user.id
    msg_id = str(callback.message.message_id)
    all_data = await state.get_data()
    game_data = all_data.get(f"game_{msg_id}")
    
    if not game_data or game_data.get("type") != "tower":
        return await callback.answer("❌ Игра уже завершена!", show_alert=True)
    if game_data.get("processing_click"):
        return await callback.answer()
        
    game_data["processing_click"] = True
    await state.update_data({f"game_{msg_id}": game_data})

    try:
        current_level = game_data["tower_level"]
        if level != current_level:
            return await callback.answer()

        field = game_data["tower_field"]
        revealed = game_data["tower_revealed"]
        bombs_count = game_data["tower_bombs"]
        bet = game_data["tower_bet"]
        
        if field[level][idx] == 1:
            all_data = await state.get_data()
            if f"game_{msg_id}" in all_data:
                del all_data[f"game_{msg_id}"]
                await state.set_data(all_data)
                
            user_name = get_user_display_name(user_id, callback.from_user.first_name)
            new_balance = db.get_user_data(user_id)[3]
            
            builder = InlineKeyboardBuilder()
            for l in range(4, -1, -1):
                builder.add(InlineKeyboardButton(text=f"x{TOWER_COEFS[bombs_count][l]:.2f}", callback_data="none"))
                for i in range(5):
                    if l < level:
                        if i == revealed[l]: builder.add(InlineKeyboardButton(text="💎", callback_data="none"))
                        else: builder.add(InlineKeyboardButton(text="🌑", callback_data="none"))
                    elif l == level:
                        if i == idx: builder.add(InlineKeyboardButton(text="💥", callback_data="none"))
                        elif field[l][i] == 1: builder.add(InlineKeyboardButton(text="💣", callback_data="none"))
                        else: builder.add(InlineKeyboardButton(text="🌑", callback_data="none"))
                    else:
                        if field[l][i] == 1: builder.add(InlineKeyboardButton(text="💣", callback_data="none"))
                        else: builder.add(InlineKeyboardButton(text="🌑", callback_data="none"))
            builder.adjust(6)
            builder.row(InlineKeyboardButton(text="🔄 Играть еще", callback_data="game_tower"))
            builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="game_tower"))

            text = (
                f"👤 <b>{user_name}</b>\n"
                f"<b>Проигрывает в игре 🏙 на {bet:,.2f} USDT</b>\n"
                f"<blockquote><b>× 0 🎄 Выигрыш 0.00 USDT ❞</b></blockquote>\n\n"
                f"<b>📋 Баланс {new_balance:,.2f} USDT</b>"
            )
            await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
            await state.clear()
        else:
            revealed.append(idx)
            new_level = level + 1
            game_data["tower_level"] = new_level
            game_data["tower_revealed"] = revealed
            game_data["processing_click"] = False
            await state.update_data({f"game_{msg_id}": game_data})
            if new_level == 5:
                await tower_cashout_handler(callback, state)
            else:
                await show_tower_field(callback.message, user_id, state)
    finally:
        all_data = await state.get_data()
        if f"game_{msg_id}" in all_data:
            current_game = all_data[f"game_{msg_id}"]
            if current_game.get("processing_click"):
                current_game["processing_click"] = False
                await state.update_data({f"game_{msg_id}": current_game})

@dp.callback_query(F.data == "tower_cashout")
async def tower_cashout_handler(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    msg_id = str(callback.message.message_id)
    all_data = await state.get_data()
    game_data = all_data.get(f"game_{msg_id}")
    
    if not game_data or game_data.get("type") != "tower":
        return await callback.answer("❌ Игра уже завершена!", show_alert=True)
    if game_data.get("processing_click"):
        return await callback.answer()
        
    game_data["processing_click"] = True
    await state.update_data({f"game_{msg_id}": game_data})

    try:
        level = game_data["tower_level"]
        bombs_count = game_data["tower_bombs"]
        bet = game_data["tower_bet"]
        revealed = game_data["tower_revealed"]
        
        if level == 0:
            game_data["processing_click"] = False
            await state.update_data({f"game_{msg_id}": game_data})
            return await callback.answer("❌ Сделайте хотя бы один ход!", show_alert=True)
            
        coef = TOWER_COEFS[bombs_count][level-1]
        win_amount = bet * coef
        
        if not db.add_balance(user_id, win_amount):
            game_data["processing_click"] = False
            await state.update_data({f"game_{msg_id}": game_data})
            return await callback.answer("❌ Ошибка при начислении выигрыша!", show_alert=True)

        new_balance = db.get_user_data(user_id)[3]
        user_name = get_user_display_name(user_id, callback.from_user.first_name)
        
        builder = InlineKeyboardBuilder()
        for l in range(4, -1, -1):
            builder.add(InlineKeyboardButton(text=f"x{TOWER_COEFS[bombs_count][l]:.2f}", callback_data="none"))
            for i in range(5):
                if l < level:
                    if i == revealed[l]: builder.add(InlineKeyboardButton(text="💎", callback_data="none"))
                    else: builder.add(InlineKeyboardButton(text="🌑", callback_data="none"))
                else:
                    if game_data["tower_field"][l][i] == 1: builder.add(InlineKeyboardButton(text="💣", callback_data="none"))
                    else: builder.add(InlineKeyboardButton(text="🌑", callback_data="none"))
        builder.adjust(6)
        builder.row(InlineKeyboardButton(text="🔄 Играть еще", callback_data="game_tower"))
        builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="game_tower"))

        all_data = await state.get_data()
        if f"game_{msg_id}" in all_data:
            del all_data[f"game_{msg_id}"]
            await state.set_data(all_data)
            
        text = (
            f"<b>👤 {user_name}</b>\n"
            f"<b>Побеждает в игре 🏙 на {bet:,.2f} USDT</b>\n"
            f"<blockquote><b>× {coef:.2f} 🎄 Выигрыш {win_amount:,.2f} USDT ❞</b></blockquote>\n\n"
            f"<b>📋 Баланс {new_balance:,.2f} USDT</b>"
        )
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
        await state.clear()
        if win_amount >= 50:
            await send_alert(callback.bot, user_id, win_amount, "win")
    finally:
        all_data = await state.get_data()
        if f"game_{msg_id}" in all_data:
            current_game = all_data[f"game_{msg_id}"]
            if current_game.get("processing_click"):
                current_game["processing_click"] = False
                await state.update_data({f"game_{msg_id}": current_game})

# ==================== АВТОРСКИЕ ИГРЫ ====================
@dp.callback_query(F.data == "custom_games")
async def custom_games_menu_handler(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    user_data = db.get_user_data(user_id)
    if not user_data:
        return
        
    balance = user_data[3]
    bet = user_data[11]
    
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🏴‍☠️ x2", callback_data="custom_game:2"),
        InlineKeyboardButton(text="🧭 x3", callback_data="custom_game:3"),
        InlineKeyboardButton(text="🐟 x4", callback_data="custom_game:4"),
        InlineKeyboardButton(text="🎈 x5", callback_data="custom_game:5")
    )
    builder.row(
        InlineKeyboardButton(text="💣 x10", callback_data="custom_game:10"),
        InlineKeyboardButton(text="🍄 x15", callback_data="custom_game:15"),
        InlineKeyboardButton(text="🍒 x20", callback_data="custom_game:20"),
        InlineKeyboardButton(text="🦋 x30", callback_data="custom_game:30")
    )
    builder.row(
        InlineKeyboardButton(text="💎 x40", callback_data="custom_game:40"),
        InlineKeyboardButton(text="🚀 x50", callback_data="custom_game:50"),
        InlineKeyboardButton(text="🐳 x100", callback_data="custom_game:100")
    )
    builder.row(get_back_button("play"))
    
    text = (
        "<b>🐋 Авторские игры</b>\n\n"
        f"<blockquote>Баланс — {balance:.2f} USDT\n"
        f"Ставка — {bet:.2f} USDT</blockquote>\n\n"
        "<i>Выбирайте коэффициент и испытайте удачу!</i>"
    )
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data.startswith("custom_game:"))
async def custom_game_play_handler(callback: CallbackQuery, state: FSMContext):
    if await state.get_state() == PlayingState.custom:
        return await callback.answer("❌ Дождитесь окончания текущей игры!", show_alert=True)
    await state.set_state(PlayingState.custom)
    
    coef = int(callback.data.split(":")[1])
    user_id = callback.from_user.id
        
    game_data = await state.get_data()
    if game_data.get("processing_click"):
        return await callback.answer()
    await state.update_data(processing_click=True)
    
    try:
        user_data = db.get_user_data(user_id)
        if not user_data:
            return
            
        balance = user_data[3]
        bet = user_data[11]
        
        if balance < bet:
            await state.clear()
            return await callback.answer("❌ Недостаточно средств!", show_alert=True)
        if not db.add_balance(user_id, -bet, is_bet=True):
            await state.clear()
            return await callback.answer("❌ Ошибка при списании ставки!", show_alert=True)
        
        user_name = get_user_display_name(user_id, callback.from_user.first_name)
        await callback.message.answer(f"<b>{user_name} ставит {bet:.2f} USDT</b>\n<blockquote><b>🐋 Авторская игра: x{coef}</b></blockquote>", parse_mode=ParseMode.HTML)
        
        emoji_map = {2: "🏴‍☠️", 3: "🧭", 4: "🐟", 5: "🎈", 10: "💣", 15: "🍄", 20: "🍒", 30: "🦋", 40: "💎", 50: "🚀", 100: "🐳"}
        emoji = emoji_map.get(coef, "🎲")
        await callback.message.answer(emoji)
        
        win_number = random.randint(1, coef)
        is_win = (win_number == coef)
        win_amount = bet * coef if is_win else 0
        
        if is_win:
            db.add_balance(user_id, win_amount)
            
        new_balance = db.get_user_data(user_id)[3]
        
        if is_win:
            text = (
                f"<b>👤 {user_name}</b>\n"
                f"<b>Побеждает в игре {emoji} на {bet:.2f} USDT</b>\n"
                f"<blockquote><b>× {coef} 🎄 Выигрыш {win_amount:.2f} USDT ❞</b></blockquote>\n\n"
                f"<b>📋 Баланс {new_balance:.2f} USDT</b>"
            )
        else:
            referrer_id = user_data[12]
            if referrer_id:
                db.add_ref_balance(referrer_id, bet * 0.05)
            text = (
                f"<b>👤 {user_name}</b>\n"
                f"<b>Проигрывает в игре {emoji} на {bet:.2f} USDT</b>\n"
                f"<blockquote><b>× 0 🎄 Выигрыш 0.00 USDT ❞</b></blockquote>\n\n"
                f"<b>📋 Баланс {new_balance:.2f} USDT</b>"
            )
        
        await callback.message.answer(text, parse_mode=ParseMode.HTML)
        if is_win and win_amount >= 50:
            await send_alert(callback.bot, user_id, win_amount, "win")
        await state.clear()
    finally:
        if await state.get_state() == PlayingState.custom:
            await state.update_data(processing_click=False)

# ==================== ИГРЫ С ЭМОДЗИ ====================
EMOJI_GAME_OPTIONS = {
    "soccer": ["Мимо ворот", "В штангу", "Гол в центр", "Гол от штанги", "Гол в угол"],
    "slots": ["🎰 3 семёрки", "🍇 3 винограда", "🍋 3 лимона", "💿 3 бара"]
}

async def emoji_strategy_menu(callback: CallbackQuery, state: FSMContext, game_type: str, selected_indices: list = None):
    user_id = callback.from_user.id
    user_data = db.get_user_data(user_id)
    balance = user_data[3]
    current_bet = user_data[11]
    
    if selected_indices is None:
        selected_indices = []
    options = EMOJI_GAME_OPTIONS.get(game_type, [])
    count = len(selected_indices)
    
    if game_type == "slots":
        coef = [0, 60, 30, 20, 15][count] if count <= 4 else 0
    else:
        coef = [0, 5, 2.5, 1.66, 1.25][count] if count <= 4 else 0
    
    builder = InlineKeyboardBuilder()
    for i, opt_text in enumerate(options):
        prefix = "✅ " if i in selected_indices else ""
        builder.add(InlineKeyboardButton(text=f"{prefix}{opt_text}", callback_data=f"strat_toggle:{game_type}:{i}"))
    builder.adjust(2)
    if count > 0:
        builder.row(InlineKeyboardButton(text=f"🫐 Играть (x{coef}) 🫐", callback_data=f"strat_play:{game_type}"))
    builder.row(get_back_button("play"))
    
    text = (
        f"⚽ <b>Выберите стратегию игры!</b>\n\n"
        f"<i>Вы можете выбрать несколько исходов</i>\n\n"
        f"<blockquote>Баланс — <b>{balance:.2f} USDT</b>\n"
        f"Ставка — <b>{current_bet:.2f} USDT</b></blockquote>"
    )
    await state.update_data(selected_indices=selected_indices)
    await state.set_state(PlayingState.strategy)
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data.startswith("strat_toggle:"))
async def strat_toggle_handler(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    game_type = parts[1]
    index = int(parts[2])
    
    data = await state.get_data()
    selected_indices = data.get("selected_indices", [])
    if index in selected_indices:
        selected_indices.remove(index)
    else:
        if len(selected_indices) >= 4:
            return await callback.answer("❌ Можно выбрать максимум 4 варианта!", show_alert=True)
        selected_indices.append(index)
    await emoji_strategy_menu(callback, state, game_type, selected_indices)

@dp.callback_query(F.data.startswith("strat_play:"))
async def strat_play_handler(callback: CallbackQuery, state: FSMContext):
    game_type = callback.data.split(":")[1]
    user_id = callback.from_user.id
    data = await state.get_data()
    selected_indices = data.get("selected_indices", [])
    
    if not selected_indices:
        return await callback.answer("❌ Выберите хотя бы один исход!", show_alert=True)
    
    user_data = db.get_user_data(user_id)
    balance = user_data[3]
    bet = user_data[11]
    
    if balance < bet:
        return await callback.answer("❌ Недостаточно средств!", show_alert=True)
    if not db.add_balance(user_id, -bet, is_bet=True):
        return await callback.answer("❌ Ошибка при списании ставки!", show_alert=True)
    
    count = len(selected_indices)
    if game_type == "slots":
        coef = [0, 60, 30, 20, 15][count]
    else:
        coef = [0, 5, 2.5, 1.66, 1.25][count]
    
    emoji = {"soccer": "⚽", "slots": "🎰"}.get(game_type, "🎲")
    user_name = get_user_display_name(user_id, callback.from_user.first_name)
    
    await callback.message.answer(f"<b>{user_name} ставит {bet:.2f} USDT</b>", parse_mode=ParseMode.HTML)
    msg = await callback.message.answer_dice(emoji=emoji)
    value = msg.dice.value
    
    is_win = False
    if game_type == "slots":
        slot_values = {0: 1, 1: 22, 2: 43, 3: 64}
        for idx in selected_indices:
            if value == slot_values.get(idx):
                is_win = True
                break
    else:
        for idx in selected_indices:
            if idx == 4 and value >= 5:
                is_win = True
                break
            elif value == idx + 1:
                is_win = True
                break
    
    await asyncio.sleep(4)
    win_amount = bet * coef if is_win else 0
    
    if is_win:
        db.add_balance(user_id, win_amount)
        new_balance = db.get_user_data(user_id)[3]
        text = f"<b>👤 {user_name}</b>\n<b>Побеждает в игре {emoji} на {bet:.2f} USDT</b>\n<blockquote><b>× {coef} 🎄 Выигрыш {win_amount:.2f} USDT ❞</b></blockquote>\n\n<b>📋 Баланс {new_balance:.2f} USDT</b>"
        if win_amount >= 50:
            await send_alert(callback.bot, user_id, win_amount, "win")
    else:
        referrer_id = user_data[12]
        if referrer_id:
            db.add_ref_balance(referrer_id, bet * 0.05)
        new_balance = db.get_user_data(user_id)[3]
        text = f"<b>👤 {user_name}</b>\n<b>Проигрывает в игре {emoji} на {bet:.2f} USDT</b>\n<blockquote><b>× 0 🎄 Выигрыш 0.00 USDT ❞</b></blockquote>\n\n<b>📋 Баланс {new_balance:.2f} USDT</b>"
    
    await callback.message.answer(text, parse_mode=ParseMode.HTML)
    await state.clear()

# ==================== ИГРЫ С КУБИКАМИ ====================

@dp.callback_query(F.data.startswith("game:"))
async def game_handler(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    game_type = callback.data.split(":")[1]
    
    if game_type == "dice":
        await dice_menu_handler(callback, state)
    elif game_type in ["soccer", "slots"]:
        await emoji_strategy_menu(callback, state, game_type)
    elif game_type == "dice_emoji":
        await old_game_handler(callback, state)
    else:
        await callback.answer("🚧 Режим в разработке", show_alert=True)

async def dice_menu_handler(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    user_data = db.get_user_data(user_id)
    balance = user_data[3]
    current_bet = user_data[11]
    
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🎲 1 куб", callback_data="dice_mode:1"),
        InlineKeyboardButton(text="🎲 2 куба", callback_data="dice_mode:2"),
        InlineKeyboardButton(text="🎲 3 куба", callback_data="dice_mode:3")
    )
    builder.row(
        InlineKeyboardButton(text="🎲 На число", callback_data="dice_mode:number"),
        InlineKeyboardButton(text="🎲 Нет 6", callback_data="dice_mode:not_6")
    )
    builder.row(
        InlineKeyboardButton(text="🎲 Кубы 7", callback_data="dice_mode:cubes_7"),
        InlineKeyboardButton(text="🎲 Произведение", callback_data="dice_mode:multiply")
    )
    builder.row(get_back_button("play"))
    
    await callback.message.edit_text(
        f"<b>🎲 Выберите режим игры!</b>\n\n"
        f"<blockquote>Баланс — <b>{balance:.2f}</b> USDT\n"
        f"Ставка — <b>{current_bet:.2f}</b> USDT</blockquote>\n\n"
        f"<i>Пополняй и сыграй на реальные деньги</i>",
        reply_markup=builder.as_markup(),
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data.startswith("dice_mode:"))
async def dice_mode_handler(callback: CallbackQuery, state: FSMContext):
    mode = callback.data.split(":")[1]
    user_id = callback.from_user.id
    user_data = db.get_user_data(user_id)
    balance = user_data[3]
    current_bet = user_data[11]
    
    builder = InlineKeyboardBuilder()
    text = ""
    
    if mode == "1":
        text = "Сделайте выбор для игры 🎲"
        builder.row(
            InlineKeyboardButton(text="🎲 1, 2, 3 (x2)", callback_data="dice_bet:1_low"),
            InlineKeyboardButton(text="🎲 4, 5, 6 (x2)", callback_data="dice_bet:1_high")
        )
        builder.row(
            InlineKeyboardButton(text="🎲 Чётное (x2)", callback_data="dice_bet:1_even"),
            InlineKeyboardButton(text="🎲 Нечётное (x2)", callback_data="dice_bet:1_odd")
        )
    elif mode == "2":
        text = "Сделайте выбор для игры 🎲🎲"
        builder.row(
            InlineKeyboardButton(text="Сумма чёт. (x2)", callback_data="dice_bet:2_even"),
            InlineKeyboardButton(text="Сумма нечёт. (x2)", callback_data="dice_bet:2_odd")
        )
        builder.row(
            InlineKeyboardButton(text="🎲 > 🎲 (x2.4)", callback_data="dice_bet:2_left_more"),
            InlineKeyboardButton(text="🎲 < 🎲 (x2.4)", callback_data="dice_bet:2_right_more")
        )
        builder.row(
            InlineKeyboardButton(text="Оба чёт. (x4)", callback_data="dice_bet:2_both_even"),
            InlineKeyboardButton(text="Оба нечёт. (x4)", callback_data="dice_bet:2_both_odd")
        )
        builder.row(
            InlineKeyboardButton(text="Шаг (x3.6)", callback_data="dice_bet:2_step"),
            InlineKeyboardButton(text="🎲 Дубль", callback_data="dice_bet:2_double")
        )
    elif mode == "3":
        text = "Выберите игру с тремя бросками 🎲"
        builder.row(
            InlineKeyboardButton(text="🎲 Трипл", callback_data="dice_bet:3_triple"),
            InlineKeyboardButton(text="🎲 67", callback_data="dice_bet:3_67")
        )
    elif mode == "number":
        text = "Сделайте выбор для игры\n\nЧто выпадет на 🎲?"
        builder.row(
            InlineKeyboardButton(text="🎲 1 (x6)", callback_data="dice_bet:num_1"),
            InlineKeyboardButton(text="🎲 2 (x6)", callback_data="dice_bet:num_2")
        )
        builder.row(
            InlineKeyboardButton(text="🎲 3 (x6)", callback_data="dice_bet:num_3"),
            InlineKeyboardButton(text="🎲 4 (x6)", callback_data="dice_bet:num_4")
        )
        builder.row(
            InlineKeyboardButton(text="🎲 5 (x6)", callback_data="dice_bet:num_5"),
            InlineKeyboardButton(text="🎲 6 (x6)", callback_data="dice_bet:num_6")
        )
    elif mode == "not_6":
        text = "<b>Всё кроме 6 — большие иксы</b>\n\n🎲 1 это ×3\n🎲 2 это ×4\n🎲 3 это ×5.2\n🎲 4 это ×6.4\n🎲 5 это ×7.6\n🎲 6 это минус ×19"
        builder.row(InlineKeyboardButton(text="🎲 Играть", callback_data="dice_bet:not_6"))
    elif mode == "cubes_7":
        text = "Сделайте выбор для игры\n\nСумма двух 🎲, от 2 до 12"
        builder.row(InlineKeyboardButton(text="🎲 Меньше 7 (x2.4)", callback_data="dice_bet:sum_less_7"))
        builder.row(InlineKeyboardButton(text="🎲 Точно 7 (x6)", callback_data="dice_bet:sum_equal_7"))
        builder.row(InlineKeyboardButton(text="🎲 Больше 7 (x2.4)", callback_data="dice_bet:sum_more_7"))
    elif mode == "multiply":
        text = "Сделайте выбор для игры произведение двух 🎲"
        builder.row(InlineKeyboardButton(text="Умн. 1-18 (x1.25)", callback_data="dice_bet:mult_1_18"))
        builder.row(InlineKeyboardButton(text="Умн. 19-36 (x4.4)", callback_data="dice_bet:mult_19_36"))

    builder.row(get_back_button("dice_menu"))
    
    await callback.message.edit_text(
        f"{text}\n\n"
        f"<blockquote>Баланс — <b>{balance:.2f}</b> USDT\n"
        f"Ставка — <b>{current_bet:.2f}</b> USDT</blockquote>\n\n"
        f"<i>Пополняй и сыграй на реальные деньги</i>",
        reply_markup=builder.as_markup(),
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data.startswith("dice_bet:"))
async def dice_bet_handler(callback: CallbackQuery, state: FSMContext):
    if await state.get_state() == PlayingState.dice:
        return await callback.answer("❌ Дождитесь окончания текущей игры!", show_alert=True)
    await state.set_state(PlayingState.dice)
    
    bet_type = callback.data.split(":")[1]
    await process_dice_game(callback.message, callback.from_user.id, bet_type, state, callback=callback)

async def process_dice_game(message: Message, user_id: int, bet_type: str, state: FSMContext, custom_numbers: list = None, callback: CallbackQuery = None):
    game_data = await state.get_data()
    if game_data.get("processing_click"):
        if callback: await callback.answer()
        return
    await state.update_data(processing_click=True)
    
    try:
        user_data = db.get_user_data(user_id)
        if not user_data:
            return
    
        balance = user_data[3]
        bet = user_data[11]
        
        if bet <= 0:
            db.set_bet(user_id, 0.2)
            bet = 0.2

        if bet_type == "not_6":
            if bet < 0.1:
                if callback: return await callback.answer("❌ Минимальная ставка в этом режиме — 0.1 USDT", show_alert=True)
                else: return await message.answer("❌ Минимальная ставка в этом режиме — 0.1 USDT")
            if balance < 2.0:
                if callback: return await callback.answer("❌ Для игры в этом режиме баланс должен быть не менее 2 USDT", show_alert=True)
                else: return await message.answer("❌ Для игры в этом режиме баланс должен быть не менее 2 USDT")

        if balance < bet:
            await state.update_data(processing_click=False)
            await state.clear()
            if callback: return await callback.answer("❌ Недостаточно средств для ставки!", show_alert=True)
            else: return await message.answer("❌ Недостаточно средств для ставки!")
            
        if bet_type == "not_6":
            potential_loss = bet * 19
            if balance < potential_loss:
                 await state.update_data(processing_click=False)
                 await state.clear()
                 text = f"❌ Недостаточно средств! При выпадении 6 вы потеряете {potential_loss:.2f} USDT.\nНужно иметь эту сумму на балансе."
                 if callback: return await callback.answer(text, show_alert=True)
                 else: return await message.answer(text)
        else:
            if not db.add_balance(user_id, -bet, is_bet=True):
                await state.update_data(processing_click=False)
                await state.clear()
                text = "❌ Ошибка при списании ставки. Недостаточно средств!"
                if callback: return await callback.answer(text, show_alert=True)
                else: return await message.answer(text)
        
        dice_count = 1
        if bet_type.startswith("2_") or bet_type.startswith("sum_") or bet_type.startswith("mult_"):
            dice_count = 2
        elif bet_type.startswith("3_"):
            dice_count = 3
            
        targets_map = {
            "1_low": "1-3", "1_high": "4-6", "1_even": "Чет", "1_odd": "Нечет",
            "2_even": "Сумма чет", "2_odd": "Сумма нечет",
            "2_left_more": "Левый > Правый", "2_right_more": "Левый < Правый",
            "2_both_even": "Оба чет", "2_both_odd": "Оба нечет",
            "2_double": "Дубль", "2_step": "Шаг",
            "3_triple": "Трипл", "3_67": "Сумма 6 или 7",
            "not_6": "Всё кроме 6",
            "sum_less_7": "Меньше 7", "sum_equal_7": "Точно 7", "sum_more_7": "Больше 7",
            "mult_1_18": "Умн. 1-18", "mult_19_36": "Умн. 19-36"
        }
        
        if custom_numbers:
            target = f"на числа {', '.join(map(str, sorted(custom_numbers)))}"
        elif bet_type.startswith("num_"):
            target = f"на число {bet_type.split('_')[1]}"
        else:
            target = targets_map.get(bet_type, bet_type)

        user_name = get_user_display_name(user_id, message.from_user.first_name)
        bet_msg_text = (
            f"<b>{user_name} ставит {bet:.2f} USDT</b>\n"
            f"<blockquote><b>🎲 {target}</b></blockquote>"
        )
        await message.answer(bet_msg_text, parse_mode=ParseMode.HTML)

        win_coef = 0
        dices = []
        for _ in range(dice_count):
            msg = await message.answer_dice(emoji="🎲")
            dices.append(msg.dice.value)
        
        await asyncio.sleep(4)
        
        if custom_numbers:
            if dices[0] in custom_numbers:
                coefs = {1: 6, 2: 3, 3: 2, 4: 1.5, 5: 1.2}
                win_coef = coefs.get(len(custom_numbers), 0)
        elif bet_type == "1_low":
            if dices[0] in [1, 2, 3]: win_coef = 2
        elif bet_type == "1_high":
            if dices[0] in [4, 5, 6]: win_coef = 2
        elif bet_type == "1_even":
            if dices[0] % 2 == 0: win_coef = 2
        elif bet_type == "1_odd":
            if dices[0] % 2 != 0: win_coef = 2
        elif bet_type.startswith("num_"):
            target_num = int(bet_type.split("_")[1])
            if dices[0] == target_num: win_coef = 6
        elif bet_type == "2_even":
            if sum(dices) % 2 == 0: win_coef = 2
        elif bet_type == "2_odd":
            if sum(dices) % 2 != 0: win_coef = 2
        elif bet_type == "2_left_more":
            if dices[0] > dices[1]: win_coef = 2.4
        elif bet_type == "2_right_more":
            if dices[0] < dices[1]: win_coef = 2.4
        elif bet_type == "2_both_even":
            if dices[0] % 2 == 0 and dices[1] % 2 == 0: win_coef = 4
        elif bet_type == "2_both_odd":
            if dices[0] % 2 != 0 and dices[1] % 2 != 0: win_coef = 4
        elif bet_type == "2_double":
            if dices[0] == dices[1]: win_coef = 6
        elif bet_type == "2_step":
            if abs(dices[0] - dices[1]) == 1: win_coef = 3.6
        elif bet_type == "3_triple":
            if dices[0] == dices[1] == dices[2]: win_coef = 30
        elif bet_type == "3_67":
            if sum(dices) in [6, 7]: win_coef = 5
        elif bet_type == "sum_less_7":
            if sum(dices) < 7: win_coef = 2.4
        elif bet_type == "sum_equal_7":
            if sum(dices) == 7: win_coef = 6
        elif bet_type == "sum_more_7":
            if sum(dices) > 7: win_coef = 2.4
        elif bet_type == "mult_1_18":
            if dices[0] * dices[1] <= 18: win_coef = 1.25
        elif bet_type == "mult_19_36":
            if dices[0] * dices[1] >= 19: win_coef = 4.4
        elif bet_type == "not_6":
            if dices[0] == 6:
                if not db.add_balance(user_id, -(bet * 19), is_bet=True):
                    current_bal = db.get_user_data(user_id)[3]
                    db.add_balance(user_id, -current_bal)
                win_coef = 0
                referrer_id = user_data[12]
                if referrer_id:
                    db.add_ref_balance(referrer_id, (bet * 19) * 0.05)
                await state.update_data(processing_click=False)
                await state.clear()
                return
            else:
                win_coef = [0, 3, 4, 5.2, 6.4, 7.6][dices[0]-1]

        win_amount = 0
        if win_coef > 0:
            win_amount = bet * win_coef
            if bet_type == "not_6":
                db.add_balance(user_id, bet * (win_coef - 1))
            else:
                db.add_balance(user_id, win_amount)
                
            user_name = get_user_display_name(user_id, message.from_user.first_name)
            new_balance = db.get_user_data(user_id)[3]
            text = (
                f"<b>👤 {user_name}</b>\n"
                f"<b>Побеждает в игре 🎲 на {bet:.2f} USDT</b>\n"
                f"<blockquote><b>× {win_coef:.2f} 🎄 Выигрыш {win_amount:.2f} USDT ❞</b></blockquote>\n\n"
                f"<b>📋 Баланс {new_balance:.2f} USDT</b>"
            )
            await state.update_data(processing_click=False)
            await message.answer(text, parse_mode=ParseMode.HTML)
            await state.clear()
            if win_amount >= 50:
                await send_alert(message.bot, user_id, win_amount, "win")
        else:
            if bet_type != "not_6":
                referrer_id = user_data[12]
                if referrer_id:
                    db.add_ref_balance(referrer_id, bet * 0.05)
            
            user_name = get_user_display_name(user_id, message.from_user.first_name)
            new_balance = db.get_user_data(user_id)[3]
            text = (
                f"<b>👤 {user_name}</b>\n"
                f"<b>Проигрывает в игре 🎲 на {bet:.2f} USDT</b>\n"
                f"<blockquote><b>× 0 🎄 Выигрыш 0.00 USDT ❞</b></blockquote>\n\n"
                f"<b>📋 Баланс {new_balance:.2f} USDT</b>"
            )
            await state.update_data(processing_click=False)
            await message.answer(text, parse_mode=ParseMode.HTML)
            await state.clear()
    except Exception as e:
        logger.error(f"Error in process_dice_game: {e}")
        await message.answer("❌ Произошла ошибка во время игры. Пожалуйста, обратитесь в поддержку.")
        await state.clear()
    finally:
        if await state.get_state() == PlayingState.dice:
            await state.update_data(processing_click=False)

async def old_game_handler(callback: CallbackQuery, state: FSMContext):
    if await state.get_state() == PlayingState.old:
        return await callback.answer("❌ Дождитесь окончания текущей игры!", show_alert=True)
    await state.set_state(PlayingState.old)
    
    user_id = callback.from_user.id
    game_type = callback.data.split(":")[1]
    
    user_data = db.get_user_data(user_id)
    balance = user_data[3]
    bet = user_data[11]
    
    if bet <= 0:
        db.set_bet(user_id, 0.2)
        bet = 0.2

    if balance < bet:
        return await callback.answer("❌ Недостаточно средств для ставки!", show_alert=True)
    if not db.add_balance(user_id, -bet, is_bet=True):
        return await callback.answer("❌ Ошибка при списании ставки!", show_alert=True)
    
    emoji_map = {"dice_emoji": "🎲", "soccer": "⚽", "slots": "🎰"}
    emoji = emoji_map.get(game_type, "🎲")
    user_name = get_user_display_name(user_id, callback.from_user.first_name)
    
    await callback.message.answer(f"<b>{user_name} ставит {bet:.2f} USDT</b>\n<blockquote><b>🎮 Игра: {emoji}</b></blockquote>", parse_mode=ParseMode.HTML)
    
    msg = await callback.message.answer_dice(emoji=emoji)
    value = msg.dice.value
    
    is_win = False
    coef = 1.9
    if game_type == "dice_emoji":
        if value >= 4: is_win = True
    elif game_type == "soccer":
        if value >= 3: is_win = True
    elif game_type == "slots":
        coef = 10.0
        if value in [1, 22, 43, 64]: is_win = True
    
    await asyncio.sleep(4)
    win_amount = bet * coef if is_win else 0
    
    if is_win:
        db.add_balance(user_id, win_amount)
        new_balance = db.get_user_data(user_id)[3]
        text = f"<b>👤 {user_name}</b>\n<b>Побеждает в игре {emoji} на {bet:.2f} USDT</b>\n<blockquote><b>× {coef} 🎄 Выигрыш {win_amount:.2f} USDT ❞</b></blockquote>\n\n<b>📋 Баланс {new_balance:.2f} USDT</b>"
        if win_amount >= 50:
            await send_alert(callback.bot, user_id, win_amount, "win")
    else:
        referrer_id = user_data[12]
        if referrer_id:
            db.add_ref_balance(referrer_id, bet * 0.05)
        new_balance = db.get_user_data(user_id)[3]
        text = f"<b>👤 {user_name}</b>\n<b>Проигрывает в игре {emoji} на {bet:.2f} USDT</b>\n<blockquote><b>× 0 🎄 Выигрыш 0.00 USDT ❞</b></blockquote>\n\n<b>📋 Баланс {new_balance:.2f} USDT</b>"
    
    await msg.reply(text, parse_mode=ParseMode.HTML)
    await state.clear()

@dp.callback_query(F.data.startswith("coming_soon"))
async def coming_soon_callback(callback: CallbackQuery, state: FSMContext):
    await callback.answer("🚧 Этот раздел находится в разработке!", show_alert=True)

# ==================== ЧЕКИ (ПРОМОКОДЫ) ====================

@dp.callback_query(F.data == "checks_menu")
async def checks_menu_callback(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    user_navigation[user_id] = user_navigation.get(user_id, []) + ["checks_menu"]
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=get_btn(user_id, "create_check"), callback_data="create_check"),
        InlineKeyboardButton(text=get_btn(user_id, "my_checks"), callback_data="my_checks")
    )
    builder.row(get_back_button("main"))
    text = "🎫 <b>Управление чеками</b>\n\nЧеки — это ссылки, по которым пользователи могут получить USDT на баланс.\n\n• <b>Создать чек</b> — укажите сумму и количество активаций\n• <b>Мои чеки</b> — список ваших активных чеков"
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data == "create_check")
async def create_check_amount_callback(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    await state.set_state(CheckState.entering_amount)
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_check"))
    await callback.message.edit_text("💰 Введите сумму чека в USDT:", reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data == "cancel_check")
async def cancel_check_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await checks_menu_callback(callback, state)

# --- СОЗДАНИЕ ЧЕКА ---
@dp.message(CheckState.entering_amount)
async def process_check_amount(message: Message, state: FSMContext):
    user_id = message.from_user.id
    raw_text = message.text.replace(",", ".").strip()
    if not raw_text:
        return await message.answer("❌ Введите сумму числом")
    try:
        amount = float(raw_text)
        if math.isnan(amount) or amount <= 0:
            raise ValueError
    except ValueError:
        return await message.answer("❌ Введите корректную сумму (число больше 0)")
    if amount < 0.1:
        return await message.answer("❌ Минимальная сумма чека — <b>0.1 USDT</b>")
    if amount > 10000:
        return await message.answer("❌ Максимальная сумма чека — <b>10000 USDT</b>")
    user_data = db.get_user_data(user_id)
    balance = user_data[3] if user_data else 0
    if balance < amount:
        return await message.answer(f"❌ Недостаточно средств! Ваш баланс: {balance:.2f} USDT")
    await state.update_data(check_amount=amount)
    await state.set_state(CheckState.entering_uses)
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_check"))
    await message.answer("🔢 Введите количество активаций (1-10000):", reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)

@dp.message(CheckState.entering_uses)
async def process_check_uses(message: Message, state: FSMContext):
    user_id = message.from_user.id
    try:
        uses = int(message.text)
    except ValueError:
        return await message.answer("❌ Введите целое число (количество активаций)")
    if uses < 1:
        return await message.answer("❌ Минимальное количество активаций — <b>1</b>")
    if uses > 10000:
        return await message.answer("❌ Максимальное количество активаций — <b>10000</b>")
    data = await state.get_data()
    amount = data.get("check_amount")
    if not db.add_balance(user_id, -amount):
        await state.clear()
        return await message.answer("❌ Ошибка при списании средств!")
    check_id = db.create_check(user_id, amount, uses)
    bot_info = await message.bot.get_me()
    check_link = f"https://t.me/{bot_info.username}?start=check_{check_id}"
    await state.clear()
    text = f"✅ Чек успешно создан!\n\n🔗 Ссылка: <code>{check_link}</code>\n💰 Сумма: {amount} USDT\n📊 Активаций: {uses}\n\nОтправьте эту ссылку пользователям!"
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔗 Скопировать ссылку", url=check_link))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="checks_menu"))
    await message.answer(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data == "my_checks")
async def my_checks_callback(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    checks = db.get_my_checks(user_id)
    if not checks:
        text = "📭 У вас нет активных чеков."
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="✨ Создать чек", callback_data="create_check"))
        builder.row(get_back_button("checks_menu"))
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
        return
    builder = InlineKeyboardBuilder()
    for check in checks:
        check_id, amount, uses_left, max_uses, created_at = check
        builder.row(InlineKeyboardButton(text=f"🎫 {check_id[:8]}... | {amount} USDT | {uses_left}/{max_uses}", callback_data=f"check_detail:{check_id}"))
    builder.row(get_back_button("checks_menu"))
    await callback.message.edit_text("📋 <b>Ваши активные чеки</b>\n\nНажмите на чек для управления.", reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data.startswith("check_detail:"))
async def check_detail_callback(callback: CallbackQuery, state: FSMContext):
    check_id = callback.data.split(":")[1]
    user_id = callback.from_user.id
    db.cursor.execute("SELECT amount, uses_left, max_uses, created_at FROM checks WHERE check_id = ? AND creator_id = ?", (check_id, user_id))
    row = db.cursor.fetchone()
    if not row:
        await callback.answer("❌ Чек не найден!", show_alert=True)
        return
    amount, uses_left, max_uses, created_at = row
    bot_info = await callback.bot.get_me()
    check_link = f"https://t.me/{bot_info.username}?start=check_{check_id}"
    text = f"🎫 Чек: <code>{check_id}</code>\n💰 Сумма: {amount} USDT\n📊 Осталось активаций: {uses_left}/{max_uses}\n📅 Создан: {created_at}"
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔗 Ссылка на чек", url=check_link))
    builder.row(InlineKeyboardButton(text="🗑 Деактивировать", callback_data=f"deactivate_check:{check_id}"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="my_checks"))
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data.startswith("deactivate_check:"))
async def deactivate_check_callback(callback: CallbackQuery, state: FSMContext):
    check_id = callback.data.split(":")[1]
    user_id = callback.from_user.id
    if db.deactivate_check(check_id, user_id):
        await callback.answer("✅ Чек деактивирован!", show_alert=True)
    else:
        await callback.answer("❌ Не удалось деактивировать чек", show_alert=True)
    await my_checks_callback(callback, state)

async def main() -> None:
    if not config.BOT_TOKEN:
        print("ОШИБКА: Токен бота не найден.")
        return

    bot = Bot(
        token=config.BOT_TOKEN, 
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML, 
            link_preview=LinkPreviewOptions(is_disabled=True)
        )
    )
    
    await update_bot_username(bot)
    print(f"Бот {BOT_USERNAME} запущен и готов к работе!")
    
    try:
        await dp.start_polling(bot)
    except Exception as e:
        print(f"Критическая ошибка: {e}")
        raise e

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот остановлен")
