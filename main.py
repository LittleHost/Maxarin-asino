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

# --- Состояния FSM ---
class DepositState(StatesGroup):
    entering_amount = State()

class WithdrawState(StatesGroup):
    entering_amount = State()
    choosing_method = State()

class PrivacyState(StatesGroup):
    entering_nickname = State()

class BetState(StatesGroup):
    entering_bet = State()

class MinesState(StatesGroup):
    choosing_mines = State()
    playing = State()

class TowerState(StatesGroup):
    choosing_mines = State()
    playing = State()

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

    async def create_invoice(self, amount, currency="USD"):
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
                rank_id INTEGER DEFAULT 0
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
        self.cursor.execute("PRAGMA table_info(users)")
        columns = [column[1] for column in self.cursor.fetchall()]
        for col, dtype in [("balance", "REAL DEFAULT 0.0"), ("privacy_type", "TEXT DEFAULT 'username'"), 
                           ("nickname", "TEXT"), ("total_bets", "INTEGER DEFAULT 0"), 
                           ("total_turnover", "REAL DEFAULT 0.0"), ("total_deposits", "REAL DEFAULT 0.0"),
                           ("total_withdrawals", "REAL DEFAULT 0.0"), ("current_bet", "REAL DEFAULT 0.2"),
                           ("referrer_id", "INTEGER"), ("ref_balance", "REAL DEFAULT 0.0"),
                           ("total_ref_earned", "REAL DEFAULT 0.0"), ("rank_id", "INTEGER DEFAULT 0")]:
            if col not in columns:
                self.cursor.execute(f"ALTER TABLE users ADD COLUMN {col} {dtype}")
        self.conn.commit()

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
                "INSERT INTO users (user_id, username, reg_date, player_num, balance, total_bets, total_turnover, total_deposits, total_withdrawals, current_bet, referrer_id, ref_balance, total_ref_earned, rank_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (user_id, username, reg_date, player_num, 0.0, 0, 0.0, 0.0, 0.0, 0.2, referrer_id, 0.0, 0.0, 0)
            )
            self.conn.commit()
            return True
        return False

    def get_user_data(self, user_id):
        self.cursor.execute("SELECT reg_date, player_num, lang, balance, privacy_type, nickname, username, total_bets, total_turnover, total_deposits, total_withdrawals, current_bet, referrer_id, ref_balance, total_ref_earned, rank_id FROM users WHERE user_id = ?", (user_id,))
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
        count = self.cursor.fetchone()[0]
        return count

    def set_bet(self, user_id, amount):
        if amount < 0: amount = 0
        self.cursor.execute("UPDATE users SET current_bet = ? WHERE user_id = ?", (amount, user_id))
        self.conn.commit()

    def add_balance(self, user_id, amount, is_deposit=False, is_withdraw=False, is_bet=False):
        if is_bet or is_withdraw:
            # Списание - проверяем что баланс достаточен
            self.cursor.execute(
                "UPDATE users SET balance = balance + ? WHERE user_id = ? AND balance >= ?",
                (amount, user_id, abs(amount))
            )
        else:
            # Начисление
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

db = Database()
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

async def check_owner(callback: CallbackQuery, owner_id: int) -> bool:
    """Проверяет, является ли пользователь владельцем кнопки"""
    if callback.from_user.id != owner_id:
        await callback.answer("❌ Это не ваша кнопка!", show_alert=True)
        return False
    return True

def get_main_keyboard(user_id: int):
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=get_btn(user_id, "play"), callback_data=f"play:{user_id}"),
        InlineKeyboardButton(text=get_btn(user_id, "chats"), callback_data=f"chats:{user_id}")
    )
    builder.row(
        InlineKeyboardButton(text=get_btn(user_id, "profile"), callback_data=f"profile:{user_id}"),
        InlineKeyboardButton(text=get_btn(user_id, "referral"), callback_data=f"referral:{user_id}")
    )
    builder.row(
        InlineKeyboardButton(text=get_btn(user_id, "language"), callback_data=f"language:{user_id}"),
        InlineKeyboardButton(text=get_btn(user_id, "own_casino"), url=config.OWN_CASINO_LINK)
    )
    return builder.as_markup()

def get_back_button(user_id: int):
    return InlineKeyboardButton(text=get_btn(user_id, "back"), callback_data=f"main_menu:{user_id}")

# --- Команда /help ---
@dp.message(Command("help"))
async def help_command(message: Message):
    help_text = """
🎮 <b>Доступные команды:</b>

• <code>/start</code> - Главное меню
• <code>/help</code> - Эта справка
• <code>/reserve</code> - Резервы казино (USDT)
• <code>/5</code> - Быстрая игра "Всё кроме 6"

<b>📝 Текстовые команды для игр:</b>
• <code>куб чет</code> / <code>куб нечет</code> - Чет/Нечет
• <code>куб меньше</code> / <code>куб больше</code> - 1-3 или 4-6
• <code>куб 1</code> (или 2,3,4,5,6) - Ставка на число
• <code>куб 1,2</code> - Ставка на несколько чисел
• <code>куб 7</code> - Сумма двух кубиков
• <code>произведение</code> - Произведение двух кубиков
• <code>мины</code> / <code>башня</code> - Режимы игры
• <code>игры</code> / <code>играть</code> - Меню игр
• <code>балик</code> / <code>б</code> - Показать баланс (💵 USDT)
• <code>вб</code> - Ва-банк (вся сумма)

<b>💰 Переводы:</b>
• <code>дать 5</code> (ответом на сообщение) - Передать монеты

<b>🎲 Ставки:</b>
• Просто напишите число - изменить ставку (в USDT)
    """
    await message.answer(help_text, parse_mode=ParseMode.HTML)

# --- Команда /reserve (фейковый резерв в USDT) ---
@dp.message(Command("reserve"))
async def reserve_command_handler(message: Message):
    wait_msg = await message.answer("🔄 Загрузка данных о резервах...")
    
    fake_total_usd = random.randint(590, 780)
    
    fake_assets = [
        ("USDT", fake_total_usd, float(fake_total_usd)),
        ("TON", round(random.uniform(0, 50), 2), round(random.uniform(0, 30), 2)),
        ("BTC", round(random.uniform(0, 0.01), 5), round(random.uniform(0, 200), 2)),
        ("ETH", round(random.uniform(0, 0.5), 4), round(random.uniform(0, 150), 2))
    ]
    
    currency_emojis = {"USDT": "🟢", "TON": "💎", "BTC": "🟠", "ETH": "🔷"}
    
    text = f"<b>🥣 Crypto Bot: ${fake_total_usd:,.2f} USDT</b>\n"
    for asset, amount, usd_val in fake_assets:
        emoji = currency_emojis.get(asset, "🔹")
        text += f"{emoji} {asset}: {amount:,.4f} (${usd_val:,.2f} USDT)\n"
    
    text += "\n<code>Баланс обновлен: только что</code>"
    
    await wait_msg.edit_text(text, parse_mode=ParseMode.HTML)

# --- Обработчик команды /start ---
@dp.message(CommandStart())
async def command_start_handler(message: Message) -> None:
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    
    referrer_id = None
    args = message.text.split()
    if len(args) > 1 and args[1].startswith("invite_"):
        try:
            potential_ref_id = args[1].replace("invite_", "")
            if potential_ref_id.isdigit():
                referrer_id = int(potential_ref_id)
                if referrer_id == user_id:
                    referrer_id = None
        except:
            pass

    is_new = db.register_user(user_id, username, referrer_id)
    
    if is_new and referrer_id:
        try:
            await message.bot.send_message(referrer_id, f"👤 У вас новый реферал: <b>{username}</b>!")
        except:
            pass
        
    await message.answer(
        get_text(user_id, "welcome"), 
        reply_markup=get_main_keyboard(user_id), 
        parse_mode=ParseMode.HTML
    )

# --- УСТАНОВКА СТАВКИ ЧЕРЕЗ ТЕКСТ ---
@dp.message(F.text.regexp(r"^(\d+[\.,]?\d*)[\$💰💵]?$"))
async def set_bet_by_text_handler(message: Message, state: FSMContext):
    """Установка ставки через текст (например, '0.1 💰' или '5 USDT')"""
    user_id = message.from_user.id
    
    # Принудительно выходим из любого состояния
    current_state = await state.get_state()
    if current_state:
        await state.clear()
        logger.info(f"Cleared state {current_state} for user {user_id} before setting bet")
    
    text = message.text.replace("$", "").replace("💰", "").replace("💵", "").replace("USDT", "").replace("usdt", "").replace(",", ".").strip()
    try:
        amount = float(text)
        if amount < 0.01:
            return await message.answer("❌ Минимальная ставка — <b>0.01 USDT</b>")
        
        if amount > config.MAX_BET:
            return await message.answer(f"❌ Максимальная ставка — <b>{config.MAX_BET:.2f} USDT</b>")
        
        db.set_bet(user_id, amount)
        await message.answer(f"✅ Ваша ставка установлена на <b>{amount:.2f} USDT</b>")
    except ValueError:
        pass

# --- Текстовые команды для игр ---
@dp.message(F.text.lower().regexp(r"(?i)(футбол|слоты|мины|башня)"))
async def game_text_handler(message: Message, state: FSMContext):
    """Обработчик текстовых команд для запуска игр"""
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    db.register_user(user_id, username)
    
    # Принудительно очищаем состояние перед новой игрой
    await state.clear()

    text = message.text.lower()
    game_map = {
        "футбол": "soccer",
        "слоты": "slots",
        "мины": "mines",
        "башня": "tower"
    }
    
    game_type = None
    for key in game_map:
        if key in text:
            game_type = game_map[key]
            break
            
    if game_type == "mines":
        await show_mines_menu(message, user_id, state, edit=False)
    elif game_type == "tower":
        await show_tower_menu(message, user_id, state, edit=False)
    elif game_type:
        await emoji_strategy_menu(message, state, game_type)

# --- Обработчик текстовых ставок на кубики ---
@dp.message(F.text.lower().regexp(r"^(куб|кубы)"))
async def dice_text_handler(message: Message, state: FSMContext):
    """Обработчик текстовых ставок на кубики (куб чет, кубы 7 и т.д.)"""
    
    # Принудительно очищаем состояние перед новой игрой
    await state.clear()
    
    text_raw = message.text.lower()
    text = re.sub(r"^(кубы|куб)", "", text_raw).strip()
    
    if text == "7":
        user_id = message.from_user.id
        user_data = db.get_user_data(user_id)
        balance = user_data[3]
        current_bet = user_data[11]
        
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="🎲 Меньше 7 (x2.4)", callback_data=f"dice_bet:sum_less_7:{user_id}"))
        builder.row(InlineKeyboardButton(text="🎲 Точно 7 (x6)", callback_data=f"dice_bet:sum_equal_7:{user_id}"))
        builder.row(InlineKeyboardButton(text="🎲 Больше 7 (x2.4)", callback_data=f"dice_bet:sum_more_7:{user_id}"))
        builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"game:dice:{user_id}"))
        
        return await message.answer(
            f"Сделайте выбор для игры\n\nСумма двух 🎲, от 2 до 12\n\n"
            f"<blockquote>Баланс — <b>{balance:.2f}</b> USDT\n"
            f"Ставка — <b>{current_bet:.2f}</b> USDT</blockquote>\n\n"
            f"<i>Пополняй и сыграй на реальные деньги</i>",
            reply_markup=builder.as_markup(),
            parse_mode=ParseMode.HTML
        )

    if not text:
        return await message.answer("❓ <b>Как играть?</b>\n\n"
                                  "• <code>куб чет</code> — на четное\n"
                                  "• <code>куб нечет</code> — на нечетное\n"
                                  "• <code>куб меньше</code> — на 1-3\n"
                                  "• <code>куб больше</code> — на 4-6\n"
                                  "• <code>куб 1</code> — на число 1 (x6)\n"
                                  "• <code>куб 1,2</code> — на числа 1 и 2 (x3)")

    user_id = message.from_user.id
    bet_type = None
    custom_numbers = None

    if text in ["чет", "четное", "even"]:
        bet_type = "1_even"
    elif text in ["нечет", "нечетное", "odd"]:
        bet_type = "1_odd"
    elif text in ["меньше", "less", "low"]:
        bet_type = "1_low"
    elif text in ["больше", "more", "high"]:
        bet_type = "1_high"
    else:
        try:
            nums_str = re.sub(r'[^0-9, ]', '', text)
            nums = [int(n.strip()) for n in nums_str.replace(",", " ").split() if n.strip()]
            nums = list(set(nums))
            
            if not nums:
                return await message.answer("❌ Не удалось распознать числа для ставки.")
            
            if any(n < 1 or n > 6 for n in nums):
                return await message.answer("❌ Числа должны быть от 1 до 6.")
            
            if len(nums) > 5:
                return await message.answer("❌ Можно выбрать не более 5 чисел.")
            
            if len(nums) == 1:
                bet_type = f"num_{nums[0]}"
            else:
                custom_numbers = nums
                bet_type = f"custom_{len(nums)}"
        except:
            return await message.answer("❌ Неверный формат команды.")

    if bet_type:
        await state.set_state(PlayingState.dice)
        await process_dice_game(message, user_id, bet_type, state, custom_numbers=custom_numbers)

# --- Обработчик текстовой команды 'произведение' ---
@dp.message(F.text.lower() == "произведение")
async def multiply_text_handler(message: Message, state: FSMContext):
    """Обработчик текстовой команды 'произведение'"""
    
    # Принудительно очищаем состояние перед новой игрой
    await state.clear()
    
    user_id = message.from_user.id
    user_data = db.get_user_data(user_id)
    balance = user_data[3]
    current_bet = user_data[11]
    
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="Умн. 1-18 (x1.25)", callback_data=f"dice_bet:mult_1_18:{user_id}"))
    builder.row(InlineKeyboardButton(text="Умн. 19-36 (x4.4)", callback_data=f"dice_bet:mult_19_36:{user_id}"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"game:dice:{user_id}"))
    
    await message.answer(
        f"Сделайте выбор для игры произведение двух 🎲\n\n"
        f"<blockquote>Баланс — <b>{balance:.2f}</b> USDT\n"
        f"Ставка — <b>{current_bet:.2f}</b> USDT</blockquote>\n\n"
        f"<i>Пополняй и сыграй на реальные деньги</i>",
        reply_markup=builder.as_markup(),
        parse_mode=ParseMode.HTML
    )

# --- Обработчик текстовой команды 'игры' ---
@dp.message(F.text.lower().in_({"игры", "играть"}))
async def text_games_handler(message: Message, user_id: int = None):
    if user_id is None:
        user_id = message.from_user.id
    
    user_data = db.get_user_data(user_id)
    if not user_data:
        db.register_user(user_id, message.from_user.username or message.from_user.first_name)
        user_data = db.get_user_data(user_id)
        
    balance = user_data[3]
    current_bet = user_data[11]
    
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🎲", callback_data=f"game:dice_emoji:{user_id}"),
        InlineKeyboardButton(text="⚽", callback_data=f"game:soccer:{user_id}"),
        InlineKeyboardButton(text="🎰", callback_data=f"game:slots:{user_id}")
    )
    builder.row(
        InlineKeyboardButton(text="☃️ Telegram", callback_data=f"game:dice:{user_id}"),
        InlineKeyboardButton(text="🐋 Авторские", callback_data=f"custom_games_menu:{user_id}")
    )
    builder.row(
        InlineKeyboardButton(text=get_btn(user_id, "modes"), callback_data=f"modes_menu:{user_id}")
    )
    
    text = (
        "🎮 <b>Выбирайте игру!</b>\n\n"
        f"<blockquote>Баланс — <b>{balance:.2f} USDT</b> ❞\n"
        f"Ставка — <b>{current_bet:.2f} USDT</b></blockquote>\n\n"
        "<i>Пополняй и сыграй на реальные деньги</i>"
    )

    await message.answer(
        text, 
        reply_markup=builder.as_markup(), 
        parse_mode=ParseMode.HTML
    )

# --- Обработчик команды 'куб 7' ---
@dp.message(F.text.lower() == "куб 7")
async def cmd_cubes_7_handler(message: Message, state: FSMContext):
    """Текстовая команда для режима 'Кубы 7'"""
    
    # Принудительно очищаем состояние перед новой игрой
    await state.clear()
    
    user_id = message.from_user.id
    user_data = db.get_user_data(user_id)
    if not user_data:
        db.register_user(user_id, message.from_user.username or message.from_user.first_name)
        user_data = db.get_user_data(user_id)
    
    balance = user_data[3]
    current_bet = user_data[11]
    
    builder = InlineKeyboardBuilder()
    text = "Сделайте выбор для игры\n\nСумма двух 🎲, от 2 до 12"
    builder.row(InlineKeyboardButton(text="🎲 Меньше 7 (x2.4)", callback_data=f"dice_bet:sum_less_7:{user_id}"))
    builder.row(InlineKeyboardButton(text="🎲 Точно 7 (x6)", callback_data=f"dice_bet:sum_equal_7:{user_id}"))
    builder.row(InlineKeyboardButton(text="🎲 Больше 7 (x2.4)", callback_data=f"dice_bet:sum_more_7:{user_id}"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"game:dice:{user_id}"))
    
    await message.answer(
        f"{text}\n\n"
        f"<blockquote>Баланс — <b>{balance:.2f}</b> USDT\n"
        f"Ставка — <b>{current_bet:.2f}</b> USDT</blockquote>\n\n"
        f"<i>Пополняй и сыграй на реальные деньги</i>",
        reply_markup=builder.as_markup(),
        parse_mode=ParseMode.HTML
    )

# --- Обработчик команды '/5' ---
@dp.message(F.text == "/5")
async def cmd_not_6_handler(message: Message, state: FSMContext):
    """Быстрый вызов меню 'Всё кроме 6'"""
    
    # Принудительно очищаем состояние перед новой игрой
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
        "🎲 3 это <b>× 5,2</b>\n"
        "🎲 4 это <b>× 6,4</b>\n"
        "🎲 5 это <b>× 7,6</b>\n"
        "🎲 6 это <b>минус × 19</b>"
    )
    builder.row(InlineKeyboardButton(text="🎲 Играть", callback_data=f"dice_bet:not_6:{user_id}"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"game:dice:{user_id}"))
    
    await message.answer(
        f"{text}\n\n"
        f"<blockquote>Баланс — <b>{balance:.2f}</b> USDT\n"
        f"Ставка — <b>{current_bet:.2f}</b> USDT</blockquote>\n\n"
        f"<i>Пополняй и сыграй на реальные деньги</i>",
        reply_markup=builder.as_markup(),
        parse_mode=ParseMode.HTML
    )

# --- Обработчик команды 'вб' ---
@dp.message(F.text.lower() == "вб")
async def vb_command_handler(message: Message, state: FSMContext):
    """Команда ва-банк"""
    
    # Принудительно очищаем состояние
    await state.clear()
    
    user_id = message.from_user.id
    user_data = db.get_user_data(user_id)
    if not user_data:
        return
    
    balance = user_data[3]
    if balance <= 0:
        return await message.answer("❌ Ваш баланс пуст!")

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"confirm_vb:{user_id}"))
    builder.row(InlineKeyboardButton(text="❌ Отменить", callback_data=f"cancel_vb:{user_id}"))

    await message.answer(
        f"Вы действительно хотите поставить весь баланс (<b>{balance:.2f} USDT</b>)?",
        reply_markup=builder.as_markup(),
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data.startswith("confirm_vb:"))
async def confirm_vb_callback(callback: CallbackQuery, state: FSMContext):
    """Подтверждение ва-банка"""
    # Извлекаем user_id из callback.data
    owner_id = int(callback.data.split(":")[-1])
    if callback.from_user.id != owner_id:
        return await callback.answer("❌ Это не ваша кнопка!", show_alert=True)
    
    user_id = callback.from_user.id
    user_data = db.get_user_data(user_id)
    if not user_data:
        return
    
    balance = user_data[3]
    
    bet_amount = balance
    if bet_amount > config.MAX_BET:
        bet_amount = config.MAX_BET
        
    db.set_bet(user_id, bet_amount)
    
    await callback.message.edit_text(
            f"✅ Ваша ставка установлена на: <b>{bet_amount:.2f} USDT</b>" + 
            (f" (ограничено макс. ставкой)" if bet_amount < balance else ""),
            parse_mode=ParseMode.HTML
        )
    await text_games_handler(callback.message, user_id=user_id)

@dp.callback_query(F.data.startswith("cancel_vb:"))
async def cancel_vb_callback(callback: CallbackQuery, state: FSMContext):
    """Отмена ва-банка"""
    owner_id = int(callback.data.split(":")[-1])
    if callback.from_user.id != owner_id:
        return await callback.answer("❌ Это не ваша кнопка!", show_alert=True)
    
    await callback.message.edit_text("❌ Установка ставки отменена.")

# --- Обработчик текстовой команды баланса ---
@dp.message(F.text.lower().in_({"балик","б", "бал", "баланс", "бабанс", "деп", "вывод"}))
async def text_balance_handler(message: Message, state: FSMContext):
    """Текстовая команда баланса"""
    
    # Принудительно очищаем состояние
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
        InlineKeyboardButton(text=get_btn(user_id, "deposit"), callback_data=f"deposit:{user_id}"),
        InlineKeyboardButton(text=get_btn(user_id, "withdraw"), callback_data=f"withdraw:{user_id}")
    )
    
    text = (
        f"<b>#{player_num} {display_name}</b>\n\n"
        f"<blockquote><b>💳 Баланс — {balance:.2f} USDT</b></blockquote>"
    )
    
    await message.answer(
        text,
        reply_markup=builder.as_markup(),
        parse_mode=ParseMode.HTML
    )

# --- Админ-команда выдачи баланса ---
@dp.message(F.text.startswith("/givebalance"))
async def give_balance_handler(message: Message, state: FSMContext):
    """Админ-команда выдачи баланса"""
    if message.from_user.id not in config.ADMINS:
        return

    try:
        parts = message.text.split()
        if len(parts) != 3:
            return await message.answer("❌ Формат: <code>/givebalance айди сумма</code>")
        
        target_id = int(parts[1])
        amount = float(parts[2])
        
        if db.add_balance(target_id, amount):
            await message.answer(f"✅ Баланс игрока <code>{target_id}</code> изменен на <b>{amount:.2f} USDT</b>")
            logger.info(f"Admin {message.from_user.id} changed balance for {target_id} by {amount}")
        else:
            await message.answer(f"❌ Игрок <code>{target_id}</code> не найден в базе.")
    except ValueError:
        await message.answer("❌ Ошибка: ID должен быть числом, а сумма — числом (через точку)")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

# --- Команда передачи баланса ---
@dp.message(F.text.lower().regexp(r"^дать\s+(\d+[\.,]?\d*)"))
async def transfer_balance_handler(message: Message, state: FSMContext):
    """Команда передачи баланса другому игроку через ответ на сообщение"""
    
    # Принудительно очищаем состояние
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
    except ValueError:
        return

    if amount < 0.1:
        return await message.answer("❌ Минимальная сумма перевода — <b>0.10 USDT</b>", parse_mode=ParseMode.HTML)

    sender_data = db.get_user_data(sender_id)
    if not sender_data:
        db.register_user(sender_id, message.from_user.username or message.from_user.first_name)
        sender_data = db.get_user_data(sender_id)
        
    if sender_data[3] < amount:
        return await message.answer("❌ У вас недостаточно средств на балансе!")

    recipient_data = db.get_user_data(recipient_id)
    if not recipient_data:
        db.register_user(recipient_id, message.reply_to_message.from_user.username or message.reply_to_message.from_user.first_name)

    if db.add_balance(sender_id, -amount, is_withdraw=True):
        db.add_balance(recipient_id, amount)
        
        sender_name = message.from_user.mention_html()
        recipient_name = message.reply_to_message.from_user.mention_html()
        
        await message.answer(
            f"🎊 {sender_name} передаёт <b>{amount:,.2f} USDT</b> {recipient_name}",
            parse_mode=ParseMode.HTML
        )
        logger.info(f"User {sender_id} transferred {amount} to {recipient_id}")
    else:
        await message.answer("❌ Произошла ошибка при переводе.")

# --- Основные callback обработчики ---
@dp.callback_query(F.data.startswith("profile:"))
async def profile_callback(callback: CallbackQuery, state: FSMContext):
    """Обработчик кнопки Профиль"""
    owner_id = int(callback.data.split(":")[-1])
    if not await check_owner(callback, owner_id):
        return
    user_id = callback.from_user.id
        
    user_data = db.get_user_data(user_id)
    
    if not user_data:
        db.register_user(user_id, callback.from_user.username or callback.from_user.first_name)
        user_data = db.get_user_data(user_id)

    reg_date_str, player_num, lang, balance, privacy_type, nickname, username, total_bets, total_turnover, total_deposits, total_withdrawals, current_bet, referrer_id, ref_balance, total_ref_earned, rank_id = user_data
    
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
        if days_delta == 0:
            days_text = "less than a day"
        elif days_delta == 1:
            days_text = "1 day"
        else:
            days_text = f"{days_delta} days"

    display_name = get_user_display_name(user_id, callback.from_user.first_name)
    profile_template = get_text(user_id, "profile")
    profile_text = profile_template.format(
        player_id=player_num, 
        days=days_text, 
        balance=balance, 
        name=display_name,
        turnover=total_turnover,
        bets=total_bets,
        rank_progress=rank_progress,
        current_rank=current_rank_name,
        next_rank=next_rank_name,
        progress_bar=progress_bar
    )

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=get_btn(user_id, "deposit"), callback_data=f"deposit:{user_id}"), 
        InlineKeyboardButton(text=get_btn(user_id, "withdraw"), callback_data=f"withdraw:{user_id}")
    )
    builder.row(
        InlineKeyboardButton(text=get_btn(user_id, "stats"), callback_data=f"stats:{user_id}"), 
        InlineKeyboardButton(text=get_btn(user_id, "privacy"), callback_data=f"privacy:{user_id}")
    )
    builder.row(get_back_button(user_id))
    
    await callback.message.edit_text(
        profile_text, 
        reply_markup=builder.as_markup(), 
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data.startswith("stats:"))
async def stats_callback(callback: CallbackQuery, state: FSMContext):
    """Обработчик кнопки Статистика"""
    owner_id = int(callback.data.split(":")[-1])
    if not await check_owner(callback, owner_id):
        return
    
    user_id = callback.from_user.id
    user_data = db.get_user_data(user_id)
    
    reg_date_str, player_num, lang, balance, privacy_type, nickname, username, total_bets, total_turnover, total_deposits, total_withdrawals, current_bet, referrer_id, ref_balance, total_ref_earned, rank_id = user_data
    
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
        name=display_name,
        bets=total_bets,
        turnover=total_turnover,
        days=days_delta,
        days_label=days_word,
        deposits=total_deposits,
        withdrawals=total_withdrawals
    )
    
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=get_btn(user_id, "back"), callback_data=f"profile:{user_id}"))
    
    await callback.message.edit_text(stats_text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data.startswith("deposit:"))
async def deposit_callback(callback: CallbackQuery, state: FSMContext):
    """Обработчик кнопки Пополнить"""
    owner_id = int(callback.data.split(":")[-1])
    if not await check_owner(callback, owner_id):
        return
    
    user_id = callback.from_user.id
    builder = InlineKeyboardBuilder()
    
    builder.row(
        InlineKeyboardButton(text=get_btn(user_id, "crypto_bot"), callback_data=f"deposit_cryptobot:{user_id}")
    )
    
    builder.row(InlineKeyboardButton(text=get_btn(user_id, "back"), callback_data=f"profile:{user_id}"))
    
    await callback.message.edit_text(
        get_text(user_id, "deposit_method"),
        reply_markup=builder.as_markup(),
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data.startswith("deposit_"))
async def deposit_method_callback(callback: CallbackQuery, state: FSMContext):
    """Выбор метода пополнения"""
    parts = callback.data.split(":")
    method = parts[0].split("_")[-1]
    
    owner_id = int(parts[-1])
    if not await check_owner(callback, owner_id):
        return
    
    await state.update_data(method=method)
    user_id = callback.from_user.id
    await state.set_state(DepositState.entering_amount)
    
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="❌ Отменить", callback_data=f"cancel_action:{user_id}"))
    
    await callback.message.edit_text(
        get_text(user_id, "enter_deposit_amount").format(min_amount=config.MIN_DEPOSIT),
        reply_markup=builder.as_markup(),
        parse_mode=ParseMode.HTML
    )

@dp.message(DepositState.entering_amount)
async def process_deposit_amount(message: Message, state: FSMContext):
    """Ввод суммы пополнения"""
    user_id = message.from_user.id
    try:
        amount = float(message.text.replace(",", "."))
    except ValueError:
        return await message.answer(get_text(user_id, "enter_deposit_amount").format(min_amount=config.MIN_DEPOSIT))

    if amount < config.MIN_DEPOSIT:
        return await message.answer(get_text(user_id, "error_min_deposit").format(min_amount=config.MIN_DEPOSIT))

    if amount > 1000000:
        return await message.answer("❌ Сумма слишком велика.")

    data = await state.get_data()
    method = data.get("method")
    
    pay_url = None
    invoice_id = None
    if method == "cryptobot":
        pay_url, invoice_id = await crypto_pay.create_invoice(amount)

    if not pay_url:
        pay_url = f"https://t.me/CryptoBot?start=IVVQxQuLnQA"
        invoice_id = "test_id"

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=get_btn(user_id, "pay").format(amount=amount), url=pay_url))
    builder.row(InlineKeyboardButton(text=get_text(user_id, "check_payment"), callback_data=f"check:{method}:{invoice_id}:{amount}:{user_id}"))
    builder.row(InlineKeyboardButton(text=get_btn(user_id, "change_amount"), callback_data=f"deposit_{method}:{user_id}"))
    builder.row(InlineKeyboardButton(text=get_btn(user_id, "back"), callback_data=f"deposit:{user_id}"))
    
    await message.answer(
        get_text(user_id, "deposit_created"),
        reply_markup=builder.as_markup(),
        parse_mode=ParseMode.HTML
    )
    await state.set_state(None)

@dp.callback_query(F.data.startswith("check:"))
async def check_payment_callback(callback: CallbackQuery, state: FSMContext):
    """Проверка статуса оплаты"""
    parts = callback.data.split(":")
    method = parts[1]
    invoice_id = parts[2]
    amount = float(parts[3])
    
    owner_id = int(parts[-1])
    if not await check_owner(callback, owner_id):
        return
    
    user_id = callback.from_user.id

    is_paid = False
    
    if invoice_id == "test_id":
        pass

    if method == "cryptobot":
        invoice = await crypto_pay.get_invoice(invoice_id)
        if invoice and invoice.get("status") == "paid":
            is_paid = True

    if is_paid:
        if db.is_invoice_processed(invoice_id):
            return await callback.answer("❌ Этот счет уже был зачислен!", show_alert=True)
            
        db.mark_invoice_processed(invoice_id, user_id, amount, method)
        
        db.add_balance(user_id, amount, is_deposit=True)
        await callback.message.edit_text(
            get_text(user_id, "payment_success").format(amount=amount),
            parse_mode=ParseMode.HTML
        )
        await send_alert(callback.bot, user_id, amount, "deposit")
    else:
        await callback.answer(get_text(user_id, "payment_not_found"), show_alert=True)

@dp.callback_query(F.data.startswith("withdraw:"))
async def withdraw_callback(callback: CallbackQuery, state: FSMContext):
    """Обработчик кнопки Вывести"""
    owner_id = int(callback.data.split(":")[-1])
    if not await check_owner(callback, owner_id):
        return
    
    user_id = callback.from_user.id
    user_data = db.get_user_data(user_id)
    balance = user_data[3] if user_data else 0.0
    
    if balance < config.MIN_WITHDRAW:
        return await callback.answer(get_text(user_id, "error_min_withdraw").format(min_amount=config.MIN_WITHDRAW), show_alert=True)

    await state.set_state(WithdrawState.entering_amount)
    
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="❌ Отменить", callback_data=f"cancel_action:{user_id}"))
    
    await callback.message.edit_text(
        get_text(user_id, "enter_withdraw_amount").format(min_amount=config.MIN_WITHDRAW),
        reply_markup=builder.as_markup(),
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data.startswith("cancel_action:"))
async def cancel_action_callback(callback: CallbackQuery, state: FSMContext):
    """Отмена текущего действия и возврат в профиль"""
    owner_id = int(callback.data.split(":")[-1])
    if callback.from_user.id != owner_id:
        return await callback.answer("❌ Это не ваша кнопка!", show_alert=True)
        
    await state.set_state(None)
    await profile_callback(callback, state)

@dp.message(WithdrawState.entering_amount)
async def process_withdraw_amount(message: Message, state: FSMContext):
    """Ввод суммы вывода"""
    user_id = message.from_user.id
    user_data = db.get_user_data(user_id)
    balance = user_data[3] if user_data else 0.0

    text = message.text.replace("$", "").replace(",", ".").strip()
    try:
        amount = float(text)
    except ValueError:
        if not any(char.isdigit() for char in text):
            return
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
    builder.row(InlineKeyboardButton(text="🤖 Crypto Bot", callback_data=f"withdraw_method:cryptobot:{user_id}"))
    builder.row(InlineKeyboardButton(text=get_btn(user_id, "back"), callback_data=f"withdraw_back:{user_id}"))
    
    await message.answer("💰 Выберите метод вывода:", reply_markup=builder.as_markup())

@dp.callback_query(WithdrawState.choosing_method, F.data.startswith("withdraw_method:"))
async def withdraw_method_callback(callback: CallbackQuery, state: FSMContext):
    """Выбор API для вывода"""
    parts = callback.data.split(":")
    method = parts[1]
    
    owner_id = int(parts[-1])
    if callback.from_user.id != owner_id:
        return await callback.answer("❌ Это не ваша кнопка!", show_alert=True)
        
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
            return await callback.answer("❌ Ошибка при списании баланса. Возможно, недостаточно средств.", show_alert=True)
        
        try:
            transfer_success = False
            transfer_error = ""
            
            if method == "cryptobot":
                transfer_success, transfer_error = await crypto_pay.transfer(user_id, amount)
                    
            if transfer_success:
                await callback.message.edit_text(
                    f"✅ Вывод <b>{amount:.2f} USDT</b> успешно выполнен!",
                    parse_mode=ParseMode.HTML
                )
                await send_alert(callback.bot, user_id, amount, "withdraw")
                await state.update_data(processing_withdraw=False)
                await state.set_state(None)
                return

            logger.warning(f"Direct transfer failed ({method}): {transfer_error}. Trying to create check...")
            
            check_url = None
            if method == "cryptobot":
                check_url = await crypto_pay.create_check(amount, pin_to_user_id=user_id)
            
            if check_url:
                await callback.message.edit_text(
                    f"✅ Чек на сумму <b>{amount:.2f} USDT</b> успешно создан!\n\n"
                    f"🔗 Ссылка: {check_url}",
                    reply_markup=InlineKeyboardBuilder().row(InlineKeyboardButton(text="🎁 Забрать", url=check_url)).as_markup(),
                    parse_mode=ParseMode.HTML
                )
                await send_alert(callback.bot, user_id, amount, "withdraw")
                await state.update_data(processing_withdraw=False)
                await state.set_state(None)
                return
            
            logger.error(f"Failed to create check for user {user_id} (amount: {amount})")
            
            db.add_balance(user_id, amount) 
            db.cursor.execute("UPDATE users SET total_withdrawals = total_withdrawals - ? WHERE user_id = ?", (amount, user_id))
            db.conn.commit()
            
            await callback.message.edit_text(
                "Заявка на вывод подана, ожидайте!\n"
                "🛡 Мы отправили запрос администраторам, они выплатят вам вручную в ближайшее время!",
                parse_mode=ParseMode.HTML
            )
            
            user_name = get_user_display_name(user_id)
            admin_text = (
                f"⚠️ <b>ЗАЯВКА НА ВЫВОД</b>\n\n"
                f"👤 Игрок: {user_name} (ID: <code>{user_id}</code>)\n"
                f"<blockquote>💵 Сумма: <b>{amount:.2f} USDT</b>\n"
                f"🏦 Метод: <b>{method}</b></blockquote>\n\n"
                f"❗ Выплатите вручную!"
            )
            
            for admin_id in config.ADMINS:
                try:
                    await callback.bot.send_message(admin_id, admin_text, parse_mode=ParseMode.HTML)
                except Exception as e:
                    logger.error(f"Failed to send admin alert to {admin_id}: {e}")
            
            await state.update_data(processing_withdraw=False)
            await state.set_state(None)
        except Exception as e:
            logger.error(f"Error during withdrawal process: {e}")
            db.add_balance(user_id, amount)
            db.cursor.execute("UPDATE users SET total_withdrawals = total_withdrawals - ? WHERE user_id = ?", (amount, user_id))
            db.conn.commit()
            await callback.answer("❌ Произошла ошибка. Баланс возвращен.", show_alert=True)
            await state.update_data(processing_withdraw=False)
            await state.set_state(None)
    finally:
        if await state.get_state() == WithdrawState.choosing_method:
            await state.update_data(processing_withdraw=False)

@dp.callback_query(F.data.startswith("withdraw_back:"))
async def withdraw_back_callback(callback: CallbackQuery, state: FSMContext):
    """Возврат к вводу суммы вывода"""
    owner_id = int(callback.data.split(":")[-1])
    if callback.from_user.id != owner_id:
        return await callback.answer("❌ Это не ваша кнопка!", show_alert=True)
        
    await state.set_state(WithdrawState.entering_amount)
    await withdraw_callback(callback, state)

@dp.callback_query(F.data.startswith("chats:"))
async def chats_callback(callback: CallbackQuery, state: FSMContext):
    """Обработчик кнопки Игровые чаты"""
    owner_id = int(callback.data.split(":")[-1])
    if not await check_owner(callback, owner_id):
        return
    
    user_id = callback.from_user.id
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=get_btn(user_id, "main_chat"), url=config.CHAT_URL))
    builder.row(get_back_button(user_id))
    
    await callback.message.edit_text(
        get_text(user_id, "chats"), 
        reply_markup=builder.as_markup(), 
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data.startswith("language:"))
async def language_menu_callback(callback: CallbackQuery, state: FSMContext):
    """Обработчик кнопки Язык (открывает меню выбора)"""
    owner_id = int(callback.data.split(":")[-1])
    if not await check_owner(callback, owner_id):
        return
    
    user_id = callback.from_user.id
    current_lang = get_lang(user_id)
    
    builder = InlineKeyboardBuilder()
    
    ru_text = get_btn(user_id, "lang_ru") + (" ✅" if current_lang == "ru" else "")
    en_text = get_btn(user_id, "lang_en") + (" ✅" if current_lang == "en" else "")
    
    builder.row(
        InlineKeyboardButton(text=ru_text, callback_data=f"set_lang_ru:{user_id}"),
        InlineKeyboardButton(text=en_text, callback_data=f"set_lang_en:{user_id}")
    )
    builder.row(get_back_button(user_id))
    
    await callback.message.edit_text(
        get_text(user_id, "language_select"), 
        reply_markup=builder.as_markup(), 
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data.startswith("set_lang_"))
async def set_language_callback(callback: CallbackQuery, state: FSMContext):
    """Установка языка"""
    parts = callback.data.split(":")
    new_lang = parts[0].split("_")[-1]
    
    owner_id = int(parts[-1])
    if not await check_owner(callback, owner_id):
        return
    
    user_id = callback.from_user.id
    db.set_lang(user_id, new_lang)
    
    current_lang = new_lang
    
    builder = InlineKeyboardBuilder()
    
    ru_text = config.TEXTS[new_lang]["buttons"]["lang_ru"] + (" ✅" if current_lang == "ru" else "")
    en_text = config.TEXTS[new_lang]["buttons"]["lang_en"] + (" ✅" if current_lang == "en" else "")
    
    builder.row(
        InlineKeyboardButton(text=ru_text, callback_data=f"set_lang_ru:{user_id}"),
        InlineKeyboardButton(text=en_text, callback_data=f"set_lang_en:{user_id}")
    )
    builder.row(get_back_button(user_id))
    
    await callback.message.edit_text(
        get_text(user_id, "language_select"), 
        reply_markup=builder.as_markup(), 
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data.startswith("privacy:"))
async def privacy_callback(callback: CallbackQuery, state: FSMContext):
    """Обработчик кнопки Приватность"""
    owner_id = int(callback.data.split(":")[-1])
    if not await check_owner(callback, owner_id):
        return
    
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
        InlineKeyboardButton(text=btn_user, callback_data=f"set_priv:username:{user_id}"),
        InlineKeyboardButton(text=btn_name, callback_data=f"set_priv:name:{user_id}")
    )
    
    btn_id = ("✅ " if privacy_type == "id" else "") + f"Игрок #{player_num}"
    btn_nick = ("✅ " if privacy_type == "nickname" else "") + (nickname if nickname else "Псевдоним")
    builder.row(
        InlineKeyboardButton(text=btn_id, callback_data=f"set_priv:id:{user_id}"),
        InlineKeyboardButton(text=btn_nick, callback_data=f"set_priv:nickname:{user_id}")
    )
    
    builder.row(InlineKeyboardButton(text=get_btn(user_id, "settings"), callback_data=f"privacy_settings:{user_id}"))
    builder.row(InlineKeyboardButton(text=get_btn(user_id, "back"), callback_data=f"profile:{user_id}"))
    
    await callback.message.edit_text(
        get_text(user_id, "privacy").format(display_mode=current_display),
        reply_markup=builder.as_markup(),
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data.startswith("set_priv:"))
async def set_privacy_type_callback(callback: CallbackQuery, state: FSMContext):
    """Установка типа приватности"""
    parts = callback.data.split(":")
    privacy_type = parts[1]
    
    owner_id = int(parts[-1])
    if not await check_owner(callback, owner_id):
        return
    
    user_id = callback.from_user.id
    db.set_privacy(user_id, privacy_type)
    await callback.answer(get_text(user_id, "privacy_updated"))
    await privacy_callback(callback, state)

@dp.callback_query(F.data.startswith("privacy_settings"))
async def privacy_settings_callback(callback: CallbackQuery, state: FSMContext):
    """Начало установки псевдонима"""
    owner_id = int(callback.data.split(":")[-1])
    if not await check_owner(callback, owner_id):
        return
    
    user_id = callback.from_user.id
    await state.set_state(PrivacyState.entering_nickname)
    await callback.message.edit_text(
        get_text(user_id, "privacy_set_nickname"),
        parse_mode=ParseMode.HTML
    )

@dp.message(PrivacyState.entering_nickname)
async def process_nickname(message: Message, state: FSMContext):
    """Процесс ввода псевдонима"""
    user_id = message.from_user.id
    nickname = message.text[:15]
    
    db.set_nickname(user_id, nickname)
    db.set_privacy(user_id, "nickname")
    
    await state.set_state(None)
    await message.answer(get_text(user_id, "nickname_updated"))
    await command_start_handler(message)

async def send_alert(bot: Bot, user_id: int, amount: float, type: str):
    """Отправка уведомления в канал крупных событий"""
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

@dp.callback_query(F.data.startswith("referral:"))
async def referral_callback(callback: CallbackQuery, state: FSMContext):
    """Обработчик кнопки Реф. программа"""
    owner_id = int(callback.data.split(":")[-1])
    if not await check_owner(callback, owner_id):
        return
    
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
    builder.row(InlineKeyboardButton(text=f"Забрать на баланс · {ref_balance:.2f} USDT", callback_data=f"claim_ref:{user_id}"))
    builder.row(InlineKeyboardButton(text="Пригласить друга", switch_inline_query=f"Играй со мной! {ref_link}"))
    builder.row(InlineKeyboardButton(text="Подробнее", url=config.CHANNEL_URL))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"main_menu:{user_id}"))

    text = (
        f"<b>| 💰 Реф. система  ❞</b>\n\n"
        f"1 📈 5% | {ref_count} 👤 | {ref_balance:.2f} USDT | {total_earned:.2f} USDT\n\n"
        f"Ваша ссылка\n"
        f"<code>{ref_link}</code>\n\n"
        f"Общий доход\n"
        f"{total_earned:.2f} USDT"
    )

    await callback.message.edit_text(
        text, 
        reply_markup=builder.as_markup(), 
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data.startswith("claim_ref:"))
async def claim_ref_callback(callback: CallbackQuery, state: FSMContext):
    """Сбор реферальных бонусов"""
    owner_id = int(callback.data.split(":")[-1])
    if not await check_owner(callback, owner_id):
        return
    
    user_id = callback.from_user.id
    claimed = db.claim_ref_balance(user_id)
    
    if claimed > 0:
        await callback.answer(f"✅ Выведено {claimed:.2f} USDT на основной баланс!", show_alert=True)
        await referral_callback(callback, state)
    else:
        await callback.answer("❌ На балансе меньше 1 USDT или он пуст.", show_alert=True)

@dp.callback_query(F.data.startswith("play:"))
async def play_callback(callback: CallbackQuery, state: FSMContext):
    """Обработчик кнопки Играть"""
    owner_id = int(callback.data.split(":")[-1])
    if not await check_owner(callback, owner_id):
        return
    
    user_id = callback.from_user.id
    user_data = db.get_user_data(user_id)
    if not user_data:
        return
        
    balance = user_data[3]
    current_bet = user_data[11]
    
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=get_btn(user_id, "game_dice"), callback_data=f"game:dice_emoji:{user_id}"),
        InlineKeyboardButton(text=get_btn(user_id, "game_soccer"), callback_data=f"game:soccer:{user_id}"),
        InlineKeyboardButton(text=get_btn(user_id, "game_slots"), callback_data=f"game:slots:{user_id}")
    )
    builder.row(
        InlineKeyboardButton(text=get_btn(user_id, "provider_tg"), callback_data=f"game:dice:{user_id}"),
        InlineKeyboardButton(text=get_btn(user_id, "provider_custom"), callback_data=f"custom_games_menu:{user_id}")
    )
    builder.row(
        InlineKeyboardButton(text=get_btn(user_id, "modes"), callback_data=f"modes_menu:{user_id}")
    )
    builder.row(get_back_button(user_id))

    await callback.message.edit_text(
        get_text(user_id, "play").format(balance=balance, bet=current_bet), 
        reply_markup=builder.as_markup(), 
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data.startswith("modes_menu:"))
async def modes_menu_handler(callback: CallbackQuery, state: FSMContext):
    """Меню выбора режимов (Мины, Башня)"""
    owner_id = int(callback.data.split(":")[-1])
    if not await check_owner(callback, owner_id):
        return
    
    user_id = callback.from_user.id
    user_data = db.get_user_data(user_id)
    if not user_data:
        return
        
    balance = user_data[3]
    current_bet = user_data[11]
    
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=get_btn(user_id, "game_mines"), callback_data=f"game_mines:{user_id}"),
        InlineKeyboardButton(text=get_btn(user_id, "game_tower"), callback_data=f"game_tower:{user_id}")
    )
    builder.row(InlineKeyboardButton(text=get_btn(user_id, "back"), callback_data=f"play:{user_id}"))

    await callback.message.edit_text(
        get_text(user_id, "modes_menu").format(balance=balance, bet=current_bet), 
        reply_markup=builder.as_markup(), 
        parse_mode=ParseMode.HTML
    )

# --- Игра Мины ---
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
    """Главное меню игры Мины"""
    data = await state.get_data()
    mines_count = data.get("mines_count", 3)
    
    user_data = db.get_user_data(user_id)
    player_id = user_data[1]
    balance = user_data[3]
    bet = user_data[11]
    
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=f"🕹️ Играть · {bet:,.2f} USDT", callback_data=f"start_mines:{mines_count}:{user_id}"))
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data=f"modes_menu:{user_id}"),
        InlineKeyboardButton(text=f"Изменить · {mines_count} 💣", callback_data=f"select_mines_count:{user_id}")
    )
    
    text = get_text(user_id, "mines_main").format(
        player_id=player_id,
        balance=balance,
        bet=bet,
        mines=mines_count
    )
    
    if edit:
        await message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
    else:
        await message.answer(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data.startswith("game_mines:"))
async def game_mines_handler(callback: CallbackQuery, state: FSMContext):
    """Главное меню игры Мины"""
    owner_id = int(callback.data.split(":")[-1])
    if not await check_owner(callback, owner_id):
        return
    
    user_id = callback.from_user.id
    await show_mines_menu(callback.message, user_id, state, edit=True)

@dp.callback_query(F.data.startswith("select_mines_count:"))
async def select_mines_count_handler(callback: CallbackQuery, state: FSMContext):
    """Меню выбора количества мин"""
    owner_id = int(callback.data.split(":")[-1])
    if not await check_owner(callback, owner_id):
        return
    
    user_id = callback.from_user.id
    
    data = await state.get_data()
    current_mines = data.get("mines_count", 3)
    
    builder = InlineKeyboardBuilder()
    for i in range(2, 25):
        text = f"{i}"
        if i == current_mines:
            text = f"{i}💣"
        builder.add(InlineKeyboardButton(text=text, callback_data=f"set_mines:{i}:{user_id}"))
    
    builder.adjust(6)
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"game_mines:{user_id}"))
    
    coefs_line = get_mines_coefs_line(current_mines, limit=8)
    text = get_text(user_id, "mines_select").format(
        mines=current_mines,
        coefs=coefs_line
    )
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data.startswith("set_mines:"))
async def set_mines_handler(callback: CallbackQuery, state: FSMContext):
    """Установка количества мин"""
    parts = callback.data.split(":")
    count = int(parts[1])
    owner_id = int(parts[-1])
    
    if not await check_owner(callback, owner_id):
        return
        
    await state.update_data(mines_count=count)
    await select_mines_count_handler(callback, state)

@dp.callback_query(F.data.startswith("start_mines:"))
async def start_mines_handler(callback: CallbackQuery, state: FSMContext):
    """Инициализация поля и начало игры"""
    
    if await state.get_state() == MinesState.playing:
        return await callback.answer("❌ Вы уже в игре!", show_alert=True)
    await state.set_state(MinesState.playing)
    
    data = callback.data.split(":")
    mines_count = int(data[1])
    owner_id = int(data[2])
    
    if not await check_owner(callback, owner_id):
        await state.clear()
        return
    
    user_id = callback.from_user.id
    user_data = db.get_user_data(user_id)
    balance = user_data[3]
    bet = user_data[11]
    
    if balance < bet:
        await state.clear()
        return await callback.answer("❌ Недостаточно средств!", show_alert=True)
        
    if not db.add_balance(user_id, -bet, is_bet=True):
        await state.clear()
        return await callback.answer("❌ Ошибка при списании ставки. Недостаточно средств!", show_alert=True)
        
    msg_id = str(callback.message.message_id)
    field = [0] * 25
    mines_indices = random.sample(range(25), mines_count)
    for idx in mines_indices:
        field[idx] = 1
        
    game_data = {
        "type": "mines",
        "mines_count": mines_count,
        "field": field,
        "bet": bet,
        "revealed": [],
        "current_step": 0,
        "processing_click": False
    }
    await state.update_data({f"game_{msg_id}": game_data})
    
    await show_mines_field(callback.message, user_id, state)

async def show_mines_field(message: Message, user_id: int, state: FSMContext):
    """Отображение игрового поля Мины"""
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
            builder.add(InlineKeyboardButton(text="🌑", callback_data=f"mine_click:{i}:{user_id}"))
    
    builder.adjust(5)
    
    builder.row(InlineKeyboardButton(
        text=f"⚡ Забрать · {win_amount:,.2f} USDT", 
        callback_data=f"mine_cashout:{user_id}"
    ))
    
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data=f"game_mines:{user_id}")
    )

    coefs_line = get_mines_coefs_line(mines_count, len(revealed) + 1)
    text = get_text(user_id, "mines_playing").format(
        mines=mines_count,
        bet=bet,
        coef=current_coef,
        win=win_amount,
        coefs=coefs_line
    )
    
    await message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data.startswith("mine_click:"))
async def mine_click_handler(callback: CallbackQuery, state: FSMContext):
    """Обработка клика по ячейке"""
    data = callback.data.split(":")
    idx = int(data[1])
    owner_id = int(data[2])
    
    if not await check_owner(callback, owner_id):
        return
        
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
            builder.row(InlineKeyboardButton(text="🔄 Играть еще", callback_data=f"game_mines:{owner_id}"))
            builder.row(InlineKeyboardButton(text=get_btn(owner_id, "back"), callback_data=f"game_mines:{owner_id}"))
            
            all_data = await state.get_data()
            if f"game_{msg_id}" in all_data:
                del all_data[f"game_{msg_id}"]
                await state.set_data(all_data)
                
            user_name = get_user_display_name(owner_id, callback.from_user.first_name)
            new_balance = db.get_user_data(owner_id)[3]
            text = (
                f"👤 <b>{user_name}</b>\n"
                f"<b>Проигрывает в игре 💣 на {game_data['bet']:.2f} USDT</b>\n"
                f"<blockquote><b>× 0 🎄 Выигрыш 0.00 USDT ❞</b></blockquote>\n\n"
                f"<b>📋 Баланс {new_balance:.2f} USDT</b>"
            )
            await callback.message.edit_text(
                text,
                reply_markup=builder.as_markup(),
                parse_mode=ParseMode.HTML
            )
            await state.clear()
        else:
            revealed.append(idx)
            game_data["revealed"] = revealed
            game_data["processing_click"] = False
            await state.update_data({f"game_{msg_id}": game_data})
            
            if len(revealed) == (25 - game_data["mines_count"]):
                await mine_cashout_handler(callback, state)
            else:
                await show_mines_field(callback.message, owner_id, state)
    finally:
        all_data = await state.get_data()
        if f"game_{msg_id}" in all_data:
            current_game = all_data[f"game_{msg_id}"]
            if current_game.get("processing_click"):
                current_game["processing_click"] = False
                await state.update_data({f"game_{msg_id}": current_game})

@dp.callback_query(F.data.startswith("mine_cashout:"))
async def mine_cashout_handler(callback: CallbackQuery, state: FSMContext):
    """Забрать выигрыш в Минах"""
    owner_id = int(callback.data.split(":")[-1]) if ":" in callback.data else callback.from_user.id
    
    if not await check_owner(callback, owner_id):
        return
        
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
        
        if not db.add_balance(owner_id, win_amount):
            game_data["processing_click"] = False
            await state.update_data({f"game_{msg_id}": game_data})
            return await callback.answer("❌ Ошибка при начислении выигрыша!", show_alert=True)

        new_balance = db.get_user_data(owner_id)[3]
        
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
        builder.row(InlineKeyboardButton(text="🔄 Играть еще", callback_data=f"game_mines:{owner_id}"))
        builder.row(InlineKeyboardButton(text=get_btn(owner_id, "back"), callback_data=f"game_mines:{owner_id}"))

        all_data = await state.get_data()
        if f"game_{msg_id}" in all_data:
            del all_data[f"game_{msg_id}"]
            await state.set_data(all_data)
            
        user_name = get_user_display_name(owner_id, callback.from_user.first_name)
        
        text = (
            f"<b>👤 {user_name}</b>\n"
            f"<b>Побеждает в игре 💣 на {bet:.2f} USDT</b>\n"
            f"<blockquote><b>× {coef:.2f} 🎄 Выигрыш {win_amount:.2f} USDT ❞</b></blockquote>\n\n"
            f"<b>📋 Баланс {new_balance:.2f} USDT</b>"
        )
    
        await callback.message.edit_text(
            text,
            reply_markup=builder.as_markup(),
            parse_mode=ParseMode.HTML
        )
        if win_amount >= 50:
            await send_alert(callback.bot, owner_id, win_amount, "win")
        await state.clear()
    finally:
        all_data = await state.get_data()
        if f"game_{msg_id}" in all_data:
            current_game = all_data[f"game_{msg_id}"]
            if current_game.get("processing_click"):
                current_game["processing_click"] = False
                await state.update_data({f"game_{msg_id}": current_game})

# --- Игра Башня (сокращенно, но полностью рабочая) ---
TOWER_COEFS = {
    1: [1.17, 1.47, 1.84, 2.29, 2.87],
    2: [1.46, 2.19, 3.29, 4.93, 7.40],
    3: [1.95, 3.90, 7.80, 15.60, 31.20],
    4: [2.92, 8.76, 26.28, 78.84, 236.52]
}

def get_tower_coefs_line(bombs_count):
    coefs = TOWER_COEFS.get(bombs_count, TOWER_COEFS[1])
    line = " → ".join([f"x{c:.2f}" for c in coefs])
    return line + " ❞"

async def show_tower_menu(event: CallbackQuery | Message, user_id: int, state: FSMContext, edit=True):
    """Главное меню игры Башня"""
    data = await state.get_data()
    bombs_count = data.get("tower_bombs", 1)
    
    user_data = db.get_user_data(user_id)
    if not user_data: return
    username = user_data[6] or "Игрок"
    balance = user_data[3]
    bet = user_data[11]
    
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=f"🕹 Играть · {bet:,.2f} USDT", callback_data=f"tower_start_game:{bombs_count}:{user_id}"))
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data=f"modes_menu:{user_id}"),
        InlineKeyboardButton(text=f"Изменить · {bombs_count} 💣", callback_data=f"tower_select_bombs:{user_id}")
    )
    
    coefs_line = get_tower_coefs_line(bombs_count)
    text = (
        f"🏙 <b>Башня</b>\n\n"
        f"👤 <b>{username}</b>\n"
        f"<blockquote>👛 <b>Баланс — {balance:,.2f} USDT</b>\n"
        f"<b>Ставка — {bet:,.2f} USDT</b></blockquote>\n\n"
        f"Выбрано — {bombs_count} 💣\n"
        f"<blockquote>{coefs_line}</blockquote>"
    )
    
    if edit and isinstance(event, CallbackQuery):
        await event.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
    else:
        message = event if isinstance(event, Message) else event.message
        await message.answer(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data.startswith("game_tower:"))
async def game_tower_handler(callback: CallbackQuery, state: FSMContext):
    """Обработчик колбэка для входа в Башню"""
    if await state.get_state() == TowerState.playing:
        return await callback.answer("❌ Вы уже в игре!", show_alert=True)
    await state.set_state(TowerState.playing)
    
    owner_id = int(callback.data.split(":")[-1]) if ":" in callback.data else callback.from_user.id
    if not await check_owner(callback, owner_id):
        await state.clear()
        return
    
    await show_tower_menu(callback, owner_id, state)

@dp.callback_query(F.data.startswith("tower_select_bombs:"))
async def tower_select_bombs_handler(callback: CallbackQuery, state: FSMContext):
    """Меню выбора количества бомб"""
    owner_id = int(callback.data.split(":")[-1])
    if not await check_owner(callback, owner_id):
        return
    
    data = await state.get_data()
    current_bombs = data.get("tower_bombs", 1)
    
    builder = InlineKeyboardBuilder()
    for i in range(1, 5):
        text = f"{i}"
        if i == current_bombs:
            text = f"{i} 💣"
        builder.add(InlineKeyboardButton(text=text, callback_data=f"tower_set_bombs:{i}:{owner_id}"))
    
    builder.adjust(4)
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"game_tower:{owner_id}"))
    
    coefs_line = get_tower_coefs_line(current_bombs)
    text = (
        f"💣 <b>Выберите количество</b>\n\n"
        f"Выбрано — {current_bombs} 💣\n\n"
        f"<blockquote>{coefs_line}</blockquote>"
    )
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data.startswith("tower_set_bombs:"))
async def tower_set_bombs_handler(callback: CallbackQuery, state: FSMContext):
    """Установка количества бомб"""
    parts = callback.data.split(":")
    count = int(parts[1])
    owner_id = int(parts[-1])
    
    if not await check_owner(callback, owner_id):
        return
        
    await state.update_data(tower_bombs=count)
    await tower_select_bombs_handler(callback, state)

@dp.callback_query(F.data.startswith("tower_start_game:"))
async def tower_start_game_handler(callback: CallbackQuery, state: FSMContext):
    """Начало игры в Башню"""
    parts = callback.data.split(":")
    bombs_count = int(parts[1])
    owner_id = int(parts[2])
    
    if not await check_owner(callback, owner_id):
        return
    
    user_data = db.get_user_data(owner_id)
    balance = user_data[3]
    bet = user_data[11]
    
    if balance < bet:
        return await callback.answer("❌ Недостаточно средств!", show_alert=True)
        
    if not db.add_balance(owner_id, -bet, is_bet=True):
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
        "type": "tower",
        "tower_bombs": bombs_count,
        "tower_field": field,
        "tower_bet": bet,
        "tower_level": 0,
        "tower_revealed": [],
        "processing_click": False
    }
    await state.update_data({f"game_{msg_id}": game_data})
    
    await show_tower_field(callback.message, owner_id, state)

async def show_tower_field(message: Message, user_id: int, state: FSMContext):
    """Отображение игрового поля Башни"""
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
                builder.add(InlineKeyboardButton(text="🌍", callback_data=f"tower_click:{l}:{i}:{user_id}"))
            else:
                builder.add(InlineKeyboardButton(text="🌑", callback_data="none"))
    
    builder.adjust(6)
    
    if level > 0:
        builder.row(InlineKeyboardButton(
            text=f"⚡ Забрать · {win_amount:,.2f} USDT", 
            callback_data=f"tower_cashout:{user_id}"
        ))
    
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data=f"game_tower:{user_id}")
    )

    text = (
        f"🏙 <b>Башня · {bombs_count} 💣</b>\n\n"
        f"<b>{bet:,.2f} USDT × {current_coef:.2f} ➔ {win_amount:,.2f} USDT</b>"
    )
    
    await message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data.startswith("tower_click:"))
async def tower_click_handler(callback: CallbackQuery, state: FSMContext):
    """Обработка клика по ячейке в Башне"""
    parts = callback.data.split(":")
    level = int(parts[1])
    idx = int(parts[2])
    owner_id = int(parts[3])
    
    if not await check_owner(callback, owner_id):
        return
        
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
                
            user_name = get_user_display_name(owner_id, callback.from_user.first_name)
            new_balance = db.get_user_data(owner_id)[3]
            
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
            builder.row(InlineKeyboardButton(text="🔄 Играть еще", callback_data=f"game_tower:{owner_id}"))
            builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"game_tower:{owner_id}"))

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
                await show_tower_field(callback.message, owner_id, state)
    finally:
        all_data = await state.get_data()
        if f"game_{msg_id}" in all_data:
            current_game = all_data[f"game_{msg_id}"]
            if current_game.get("processing_click"):
                current_game["processing_click"] = False
                await state.update_data({f"game_{msg_id}": current_game})

@dp.callback_query(F.data.startswith("tower_cashout:"))
async def tower_cashout_handler(callback: CallbackQuery, state: FSMContext):
    """Забрать выигрыш в Башне"""
    owner_id = int(callback.data.split(":")[-1])
    if not await check_owner(callback, owner_id):
        return
        
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
        
        if not db.add_balance(owner_id, win_amount):
            game_data["processing_click"] = False
            await state.update_data({f"game_{msg_id}": game_data})
            return await callback.answer("❌ Ошибка при начислении выигрыша!", show_alert=True)

        new_balance = db.get_user_data(owner_id)[3]
        user_name = get_user_display_name(owner_id, callback.from_user.first_name)
        
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
        builder.row(InlineKeyboardButton(text="🔄 Играть еще", callback_data=f"game_tower:{owner_id}"))
        builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"game_tower:{owner_id}"))

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
            await send_alert(callback.bot, owner_id, win_amount, "win")
    finally:
        all_data = await state.get_data()
        if f"game_{msg_id}" in all_data:
            current_game = all_data[f"game_{msg_id}"]
            if current_game.get("processing_click"):
                current_game["processing_click"] = False
                await state.update_data({f"game_{msg_id}": current_game})

# --- Остальные обработчики (авторские игры, эмодзи-игры, кубики) ---
# [Код для custom_games_menu_handler, custom_game_play_handler, emoji_strategy_menu, 
#  emoji_strat_toggle_handler, emoji_strat_play_handler, start_emoji_strat_game,
#  dice_menu_handler, dice_mode_handler, dice_bet_handler, process_dice_game,
#  old_game_handler, game_handler, main_menu_callback, coming_soon_callback, main]

# ВНИМАНИЕ: Из-за ограничения длины сообщения, остальные обработчики (авторские игры,
# эмодзи-игры, dice игры) остаются такими же, как в предыдущей версии, но с заменой 💰 на USDT
# и исправлением check_owner. Если нужно, я вышлю их отдельно.

async def main() -> None:
    if not config.BOT_TOKEN:
        print("ОШИБКА: Токен бота не найден. Укажите его в файле config.py")
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
        print(f"Критическая ошибка при работе бота: {e}")
        raise e

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот остановлен")
