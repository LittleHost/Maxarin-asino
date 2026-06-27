import asyncio
import logging
import sqlite3
import random
import re
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters import Command
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.callback_data import CallbackData
from aiogram.utils.executor import start_polling

# Инициализация для aiogram 2.x
bot = Bot(token=TOKEN, parse_mode=ParseMode.HTML)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# ===== КОНФИГ =====
TOKEN = "8560416585:AAGZL4yp8VBsG1AP_lIkQsP3QUHUJGifN0s"
ADMINS = [5262554364, 7966949924]
CHAT_ID = -1003746900057
CHAT_LINK = "https://t.me/fcmobileworldcup"

# ===== ПРЕМИУМ ЭМОДЗИ =====
EMOJI = {
    "hello": "5226775277094347795",
    "id": "5226772171832991907",
    "username": "5226616973189746219",
    "world": "5226774675798923342",
    "bot": "5226727293719712131",
    "championship": "5226775650756500291",
    "rocket": "5226842102490501226",
    "stars": "5226753840912570607"
}

# ===== ФУНКЦИИ ДЛЯ ПРЕМИУМ ЭМОДЗИ =====
def premium_emoji(emoji_id, fallback="⭐"):
    return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'

def get_emoji(name):
    return premium_emoji(EMOJI.get(name, EMOJI["stars"]), "⭐")

# ===== НАСТРОЙКА =====
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(
    token=TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ===== БАЗА ДАННЫХ =====
DB_NAME = "tournament.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT UNIQUE,
            club TEXT,
            team TEXT,
            registered BOOLEAN DEFAULT 0,
            created_at TEXT
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tournaments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            type TEXT,
            participants_count INTEGER,
            status TEXT DEFAULT 'active',
            created_at TEXT,
            message_id INTEGER
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tournament_id INTEGER,
            player1 TEXT,
            player2 TEXT,
            score TEXT DEFAULT '0-0',
            round TEXT,
            is_finished BOOLEAN DEFAULT 0,
            FOREIGN KEY (tournament_id) REFERENCES tournaments (id)
        )
    ''')
    
    conn.commit()
    conn.close()

# ===== ФУНКЦИИ БД =====

def save_user_id(user_id, username):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    username = username.replace('@', '').strip() if username else None
    cursor.execute('SELECT id FROM users WHERE username = ?', (username,))
    existing = cursor.fetchone()
    if existing:
        cursor.execute('UPDATE users SET id = ? WHERE username = ?', (user_id, username))
    else:
        cursor.execute('''
            INSERT OR IGNORE INTO users (id, username, registered, created_at)
            VALUES (?, ?, 0, ?)
        ''', (user_id, username, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def register_user(username, club, team):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    username = username.replace('@', '').strip()
    cursor.execute('SELECT id FROM users WHERE username = ?', (username,))
    user = cursor.fetchone()
    if user:
        cursor.execute('''
            UPDATE users 
            SET club = ?, team = ?, registered = 1
            WHERE username = ?
        ''', (club, team, username))
        result = True
    else:
        fake_id = random.randint(1000000000, 9999999999)
        cursor.execute('''
            INSERT INTO users (id, username, club, team, registered, created_at)
            VALUES (?, ?, ?, ?, 1, ?)
        ''', (fake_id, username, club, team, datetime.now().isoformat()))
        result = False
    conn.commit()
    conn.close()
    return result

def get_user_by_id(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))
    user = cursor.fetchone()
    conn.close()
    return user

def get_all_users():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE registered = 1 ORDER BY username')
    users = cursor.fetchall()
    conn.close()
    return users

def get_registered_users():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT username, club, team FROM users WHERE registered = 1')
    users = cursor.fetchall()
    conn.close()
    return users

def create_tournament(name, type_, count, message_id=None):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO tournaments (name, type, participants_count, created_at, message_id)
        VALUES (?, ?, ?, ?, ?)
    ''', (name, type_, count, datetime.now().isoformat(), message_id))
    tournament_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return tournament_id

def save_matches(tournament_id, matches):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    for match in matches:
        cursor.execute('''
            INSERT INTO matches (tournament_id, player1, player2, round, score)
            VALUES (?, ?, ?, ?, ?)
        ''', (tournament_id, match['player1'], match['player2'], match['round'], match.get('score', '0-0')))
    conn.commit()
    conn.close()

def get_tournament_matches(tournament_name):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT m.* FROM matches m
        JOIN tournaments t ON m.tournament_id = t.id
        WHERE t.name = ?
        ORDER BY m.id
    ''', (tournament_name,))
    matches = cursor.fetchall()
    conn.close()
    return matches

def update_match_score(tournament_name, player1, player2, score):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    player1 = player1.replace('@', '').strip()
    player2 = player2.replace('@', '').strip()
    cursor.execute('''
        UPDATE matches 
        SET score = ?, is_finished = 1
        WHERE tournament_id = (SELECT id FROM tournaments WHERE name = ?)
        AND ((player1 = ? AND player2 = ?) OR (player1 = ? AND player2 = ?))
    ''', (score, tournament_name, player1, player2, player2, player1))
    success = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return success

def get_tournament_message_id(tournament_name):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT message_id FROM tournaments WHERE name = ?', (tournament_name,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def get_tournament_by_name(name):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM tournaments WHERE name = ?', (name,))
    result = cursor.fetchone()
    conn.close()
    return result

def get_all_tournaments():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM tournaments ORDER BY created_at DESC')
    result = cursor.fetchall()
    conn.close()
    return result

def get_tournament_by_id(tournament_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM tournaments WHERE id = ?', (tournament_id,))
    result = cursor.fetchone()
    conn.close()
    return result

def get_matches_by_round(tournament_name, round_name):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT * FROM matches 
        WHERE tournament_id = (SELECT id FROM tournaments WHERE name = ?)
        AND round = ?
    ''', (tournament_name, round_name))
    matches = cursor.fetchall()
    conn.close()
    return matches

def add_next_round(tournament_name, matches):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    tournament_id = get_tournament_by_name(tournament_name)[0]
    for match in matches:
        cursor.execute('''
            INSERT INTO matches (tournament_id, player1, player2, round, score)
            VALUES (?, ?, ?, ?, ?)
        ''', (tournament_id, match['player1'], match['player2'], match['round'], '0-0'))
    conn.commit()
    conn.close()

# ===== КЛАВИАТУРЫ =====

def get_main_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(
        text=f"{get_emoji('world')} Меню",
        callback_data="profile"
    )
    builder.button(
        text=f"{get_emoji('rocket')} Профиль",
        callback_data="profile"
    )
    builder.button(
        text=f"{get_emoji('stars')} Информация",
        callback_data="info"
    )
    builder.adjust(1)
    return builder.as_markup()

def get_back_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(
        text=f"{get_emoji('stars')} Назад",
        callback_data="back"
    )
    return builder.as_markup()

def get_admin_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="📝 Регистрация", callback_data="admin_register")
    builder.button(text="👥 Игроки", callback_data="admin_players")
    builder.button(text="🏆 Турниры", callback_data="admin_tournaments")
    builder.adjust(1)
    return builder.as_markup()

def get_tournament_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Создать", callback_data="create_tournament")
    builder.button(text="📋 Список", callback_data="list_tournaments")
    builder.button(text="🔙 Назад", callback_data="back_admin")
    builder.adjust(1)
    return builder.as_markup()

# ===== СОСТОЯНИЯ FSM =====

class RegisterState(StatesGroup):
    waiting_for_data = State()

class TournamentState(StatesGroup):
    waiting_for_name = State()
    waiting_for_count = State()
    waiting_for_type = State()

# ===== ГЕНЕРАЦИЯ СЕТКИ =====

def get_round_order():
    return [
        f"{get_emoji('hello')} 1/16",
        f"{get_emoji('stars')} 1/8",
        f"{get_emoji('rocket')} 1/4",
        f"{get_emoji('world')} 1/2",
        f"{get_emoji('championship')} Финал"
    ]

def get_next_round(current_round):
    rounds = get_round_order()
    try:
        idx = rounds.index(current_round)
        if idx + 1 < len(rounds):
            return rounds[idx + 1]
    except ValueError:
        pass
    return None

def generate_bracket(players, tournament_type):
    if len(players) < 2:
        return None, "❌ Недостаточно игроков! Нужно минимум 2."
    
    player_list = []
    for p in players:
        if tournament_type == 'clubs':
            name = f"{p[1]} ({p[0]})"
        else:
            name = f"{p[2]} ({p[0]})"
        player_list.append(name)
    
    random.shuffle(player_list)
    total = len(player_list)
    
    next_power = 1
    while next_power < total:
        next_power *= 2
    
    while len(player_list) < next_power:
        player_list.append(None)
    
    if next_power <= 2:
        round_names = [f"{get_emoji('championship')} Финал"]
    elif next_power <= 4:
        round_names = [f"{get_emoji('world')} 1/2", f"{get_emoji('championship')} Финал"]
    elif next_power <= 8:
        round_names = [f"{get_emoji('rocket')} 1/4", f"{get_emoji('world')} 1/2", f"{get_emoji('championship')} Финал"]
    elif next_power <= 16:
        round_names = [f"{get_emoji('stars')} 1/8", f"{get_emoji('rocket')} 1/4", f"{get_emoji('world')} 1/2", f"{get_emoji('championship')} Финал"]
    else:
        round_names = [f"{get_emoji('hello')} 1/16", f"{get_emoji('stars')} 1/8", f"{get_emoji('rocket')} 1/4", f"{get_emoji('world')} 1/2", f"{get_emoji('championship')} Финал"]
    
    matches = []
    current_round = 0
    players_in_round = player_list.copy()
    
    while len(players_in_round) > 1:
        round_name = round_names[current_round] if current_round < len(round_names) else f"Раунд {current_round+1}"
        round_matches = []
        new_players = []
        
        for i in range(0, len(players_in_round), 2):
            p1 = players_in_round[i]
            p2 = players_in_round[i+1] if i+1 < len(players_in_round) else None
            
            if p1 is None and p2 is None:
                continue
            
            if p1 is None:
                new_players.append(p2)
                continue
            if p2 is None:
                new_players.append(p1)
                continue
            
            match = {
                'player1': p1,
                'player2': p2,
                'round': round_name,
                'score': '0-0'
            }
            round_matches.append(match)
            new_players.append(f"Победитель матча {len(matches)+1}")
        
        matches.extend(round_matches)
        players_in_round = new_players
        current_round += 1
        
        if len(players_in_round) <= 1:
            break
    
    return matches, None

def format_bracket(matches, tournament_name):
    text = f"{get_emoji('rocket')} <b>Турнир: {tournament_name}</b>\n\n"
    
    current_round = None
    
    for i, match in enumerate(matches, 1):
        if match['round'] != current_round:
            current_round = match['round']
            text += f"\n<b>{current_round}</b>\n"
            text += "─" * 20 + "\n"
        
        p1 = match['player1'] if match['player1'] else "⏳ Ожидание"
        p2 = match['player2'] if match['player2'] else "⏳ Ожидание"
        score = match.get('score', '0-0')
        
        text += f"⚽ {p1} vs {p2}  |  {score}\n"
    
    text += f"\n{get_emoji('stars')} <b>Зарегистрировать свой клуб:</b> @username_bota"
    
    return text

# ===== АВТО-ПЕРЕХОД МЕЖДУ РАУНДАМИ =====

def check_and_advance_round(tournament_name):
    matches = get_tournament_matches(tournament_name)
    
    if not matches:
        return False, "Нет матчей"
    
    rounds = []
    for match in matches:
        if match[5] not in rounds:
            rounds.append(match[5])
    
    if not rounds:
        return False, "Нет раундов"
    
    current_round = rounds[-1]
    
    round_matches = [m for m in matches if m[5] == current_round]
    all_finished = all(m[7] == 1 for m in round_matches)
    
    if not all_finished:
        return False, f"Раунд {current_round} еще не завершен"
    
    next_round = get_next_round(current_round)
    if not next_round:
        return False, "🏆 ТУРНИР ЗАВЕРШЕН!"
    
    winners = []
    for match in round_matches:
        score = match[6]
        if score and '-' in score:
            scores = score.split('-')
            try:
                score1 = int(scores[0])
                score2 = int(scores[1])
                if score1 > score2:
                    winners.append(match[3])
                elif score2 > score1:
                    winners.append(match[4])
                else:
                    winners.append(match[3])
            except ValueError:
                winners.append(None)
        else:
            winners.append(None)
    
    winners = [w for w in winners if w is not None]
    
    if len(winners) < 2:
        return False, "Недостаточно победителей для следующего раунда"
    
    next_matches = []
    for i in range(0, len(winners), 2):
        if i+1 < len(winners):
            next_matches.append({
                'player1': winners[i],
                'player2': winners[i+1],
                'round': next_round,
                'score': '0-0'
            })
    
    if not next_matches:
        return False, "Недостаточно пар для следующего раунда"
    
    tournament = get_tournament_by_name(tournament_name)
    if tournament:
        tournament_id = tournament[0]
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        for match in next_matches:
            cursor.execute('''
                INSERT INTO matches (tournament_id, player1, player2, round, score)
                VALUES (?, ?, ?, ?, ?)
            ''', (tournament_id, match['player1'], match['player2'], match['round'], '0-0'))
        conn.commit()
        conn.close()
        
        return True, f"✅ Создан следующий раунд: {next_round}"
    
    return False, "Ошибка"

def update_bracket_message(tournament_name):
    matches = get_tournament_matches(tournament_name)
    tournament = get_tournament_by_name(tournament_name)
    
    if not tournament:
        return False
    
    bracket_text = format_bracket(matches, tournament_name)
    message_id = tournament[6]
    
    if message_id:
        try:
            bot.edit_message_text(
                chat_id=CHAT_ID,
                message_id=message_id,
                text=bracket_text
            )
            return True
        except Exception as e:
            logger.error(f"Ошибка обновления: {e}")
            return False
    return False

# ===== ОБРАБОТЧИКИ КОМАНД =====

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    save_user_id(message.from_user.id, message.from_user.username)
    
    text = f"{get_emoji('hello')} <b>Привет</b> - ты попал в бота, новейшего турнира по FC Mobile\n\n"
    text += f"{get_emoji('championship')} <b>Чемпионат</b> | Мы играем в турниры по типу лиги чемпионов, лиги Европы а также чемпионатов мира - наш чат ({CHAT_LINK})"
    
    await message.answer(text, reply_markup=get_main_keyboard())
    logger.info(f"Пользователь @{message.from_user.username} запустил бота")

@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if message.from_user.id not in ADMINS:
        await message.answer("⛔ Доступ запрещён!")
        return
    
    users = get_all_users()
    clubs = set()
    teams = set()
    
    for user in users:
        if user[2]:
            clubs.add(user[2])
        if user[3]:
            teams.add(user[3])
    
    text = "👑 *Админ-панель*\n"
    text += "═" * 20 + "\n\n"
    text += f"👥 Пользователей: *{len(users)}*\n"
    text += f"🏟 Клубов: *{len(clubs)}*\n"
    text += f"🌍 Сборных: *{len(teams)}*\n"
    text += f"🏆 Турниров: *{len(get_all_tournaments())}*"
    
    await message.answer(text, parse_mode="Markdown", reply_markup=get_admin_keyboard())

@dp.message(Command("turnir"))
async def cmd_turnir(message: types.Message):
    if message.from_user.id not in ADMINS:
        await message.answer("⛔ Доступ запрещён!")
        return
    
    try:
        parts = message.text.split()
        
        if len(parts) < 5:
            await message.answer(
                "❌ *Неверный формат*\n\n"
                "Пример:\n"
                "`/turnir лч @иван @саша 1-0`",
                parse_mode="Markdown"
            )
            return
        
        tournament_parts = []
        i = 1
        while i < len(parts) and not parts[i].startswith('@'):
            tournament_parts.append(parts[i])
            i += 1
        
        if not tournament_parts:
            await message.answer("❌ Введите название турнира!")
            return
        
        tournament_name = ' '.join(tournament_parts)
        
        if i + 2 >= len(parts):
            await message.answer("❌ Неправильный формат!\nПример: `/turnir лч @иван @саша 1-0`")
            return
        
        player1 = parts[i].replace('@', '').strip()
        player2 = parts[i+1].replace('@', '').strip()
        score = parts[i+2].strip()
        
        if not re.match(r'^\d+-\d+$', score):
            await message.answer("❌ Счёт должен быть в формате: `3-1`", parse_mode="Markdown")
            return
        
        tournament = get_tournament_by_name(tournament_name)
        if not tournament:
            await message.answer(f"❌ Турнир *{tournament_name}* не найден!", parse_mode="Markdown")
            return
        
        success = update_match_score(tournament_name, player1, player2, score)
        if not success:
            await message.answer(
                f"❌ Матч не найден!\n"
                f"Проверьте: *{tournament_name}*, @{player1}, @{player2}",
                parse_mode="Markdown"
            )
            return
        
        matches = get_tournament_matches(tournament_name)
        bracket_text = format_bracket(matches, tournament_name)
        message_id = get_tournament_message_id(tournament_name)
        
        if message_id:
            try:
                await bot.edit_message_text(
                    chat_id=CHAT_ID,
                    message_id=message_id,
                    text=bracket_text
                )
            except Exception as e:
                logger.error(f"Ошибка обновления: {e}")
        
        advanced, msg = check_and_advance_round(tournament_name)
        if advanced:
            matches = get_tournament_matches(tournament_name)
            bracket_text = format_bracket(matches, tournament_name)
            if message_id:
                try:
                    await bot.edit_message_text(
                        chat_id=CHAT_ID,
                        message_id=message_id,
                        text=bracket_text
                    )
                except Exception as e:
                    logger.error(f"Ошибка обновления: {e}")
            await message.answer(f"✅ *Счёт обновлён!*\n@{player1} vs @{player2} = {score}\n\n{msg}", parse_mode="Markdown")
        else:
            await message.answer(f"✅ *Счёт обновлён!*\n@{player1} vs @{player2} = {score}", parse_mode="Markdown")
        
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        await message.answer(f"❌ Ошибка: {str(e)}")

@dp.message(Command("getid"))
async def cmd_getid(message: types.Message):
    if message.from_user.id not in ADMINS:
        await message.answer("⛔ Доступ запрещён!")
        return
    
    text = f"📊 ID чата: `{message.chat.id}`"
    await message.answer(text, parse_mode="Markdown")

# ===== ОБРАБОТЧИКИ CALLBACK =====

@dp.callback_query(F.data == "profile")
async def callback_profile(callback: types.CallbackQuery):
    user = get_user_by_id(callback.from_user.id)
    
    text = f"{get_emoji('username')} <b>Юзер:</b> @{callback.from_user.username or 'Не указан'}\n"
    text += f"{get_emoji('id')} <b>Айди:</b> {callback.from_user.id}\n"
    
    if user and user[4]:
        text += f"{get_emoji('world')} <b>Клуб:</b> {user[2] or '—'}\n"
        text += f"Сборная: {user[3] or '—'}\n"
        text += "\n✅ Зарегистрирован"
    else:
        text += f"{get_emoji('world')} <b>Клуб:</b> нету\n"
        text += "\n⚠️ Не зарегистрирован"
    
    await callback.message.edit_text(text, reply_markup=get_back_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "info")
async def callback_info(callback: types.CallbackQuery):
    text = f"{get_emoji('world')} <b>Канал:</b> https://t.me/fcmobile26news\n"
    text += f"{get_emoji('stars')} <b>Чат:</b> {CHAT_LINK}\n"
    text += f"{get_emoji('username')} <b>Владелец:</b> @etodmitryyzz"
    
    await callback.message.edit_text(text, reply_markup=get_back_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "back")
async def callback_back(callback: types.CallbackQuery):
    text = f"{get_emoji('hello')} <b>Привет</b> - ты попал в бота, новейшего турнира по FC Mobile\n\n"
    text += f"{get_emoji('championship')} <b>Чемпионат</b> | Мы играем в турниры по типу лиги чемпионов, лиги Европы а также чемпионатов мира - наш чат ({CHAT_LINK})"
    
    await callback.message.edit_text(text, reply_markup=get_main_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "back_admin")
async def callback_back_admin(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMINS:
        await callback.answer("⛔ Нет доступа!", show_alert=True)
        return
    
    users = get_all_users()
    clubs = set()
    teams = set()
    
    for user in users:
        if user[2]:
            clubs.add(user[2])
        if user[3]:
            teams.add(user[3])
    
    text = "👑 *Админ-панель*\n"
    text += "═" * 20 + "\n\n"
    text += f"👥 Пользователей: *{len(users)}*\n"
    text += f"🏟 Клубов: *{len(clubs)}*\n"
    text += f"🌍 Сборных: *{len(teams)}*\n"
    text += f"🏆 Турниров: *{len(get_all_tournaments())}*"
    
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=get_admin_keyboard())
    await callback.answer()

# ===== АДМИН-ОБРАБОТЧИКИ =====

@dp.callback_query(F.data == "admin_register")
async def callback_admin_register(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMINS:
        await callback.answer("⛔ Нет доступа!", show_alert=True)
        return
    
    await callback.message.edit_text(
        "📝 *Регистрация игрока*\n"
        "═" * 20 + "\n\n"
        "Введите данные:\n"
        "`юзернейм, клуб, сборная`\n\n"
        "Пример:\n"
        "`@theid777, ПСЖ, Италия`",
        parse_mode="Markdown"
    )
    await state.set_state(RegisterState.waiting_for_data)
    await callback.answer()

@dp.message(RegisterState.waiting_for_data)
async def register_player(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS:
        await message.answer("⛔ Доступ запрещён!")
        await state.clear()
        return
    
    try:
        data = message.text.split(',')
        if len(data) != 3:
            await message.answer(
                "❌ *Неверный формат*\n\n"
                "Нужно: `юзернейм, клуб, сборная`\n"
                "Пример: `@theid777, ПСЖ, Италия`",
                parse_mode="Markdown"
            )
            return
        
        username = data[0].strip().replace('@', '')
        club = data[1].strip()
        team = data[2].strip()
        
        if not username or not club or not team:
            await message.answer("❌ Все поля должны быть заполнены!")
            return
        
        existed = register_user(username, club, team)
        
        if existed:
            await message.answer(
                f"✅ *Игрок @{username} обновлён!*\n"
                f"Клуб: {club}\n"
                f"Сборная: {team}",
                parse_mode="Markdown"
            )
        else:
            await message.answer(
                f"✅ *Игрок @{username} зарегистрирован!*\n"
                f"Клуб: {club}\n"
                f"Сборная: {team}",
                parse_mode="Markdown"
            )
        
        await state.clear()
        
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        await message.answer(f"❌ Ошибка: {str(e)}")
        await state.clear()

@dp.callback_query(F.data == "admin_players")
async def callback_admin_players(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMINS:
        await callback.answer("⛔ Нет доступа!", show_alert=True)
        return
    
    users = get_all_users()
    
    if not users:
        await callback.message.edit_text(
            "📋 *Список игроков пуст*",
            parse_mode="Markdown",
            reply_markup=get_back_keyboard()
        )
        await callback.answer()
        return
    
    text = "👥 *Игроки*\n"
    text += "═" * 20 + "\n\n"
    
    for i, user in enumerate(users, 1):
        text += f"*{i}.* @{user[1]}\n"
        text += f"   Клуб: {user[2] or '—'}\n"
        text += f"   Сборная: {user[3] or '—'}\n\n"
    
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=get_back_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "admin_tournaments")
async def callback_admin_tournaments(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMINS:
        await callback.answer("⛔ Нет доступа!", show_alert=True)
        return
    
    await callback.message.edit_text(
        "🏆 *Управление турнирами*\n"
        "═" * 20,
        parse_mode="Markdown",
        reply_markup=get_tournament_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data == "list_tournaments")
async def callback_list_tournaments(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMINS:
        await callback.answer("⛔ Нет доступа!", show_alert=True)
        return
    
    tournaments = get_all_tournaments()
    
    if not tournaments:
        await callback.message.edit_text(
            "📋 *Нет созданных турниров*",
            parse_mode="Markdown",
            reply_markup=get_tournament_keyboard()
        )
        await callback.answer()
        return
    
    text = "📋 *Список турниров*\n"
    text += "═" * 20 + "\n\n"
    
    for t in tournaments:
        type_name = "Команды" if t[2] == 'clubs' else "Сборные"
        status = "🟢 Активен" if t[4] == 'active' else "🔴 Завершён"
        text += f"🏆 *{t[1]}*\n"
        text += f"   Тип: {type_name}\n"
        text += f"   Участников: {t[3]}\n"
        text += f"   Статус: {status}\n\n"
    
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=get_tournament_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "create_tournament")
async def callback_create_tournament(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMINS:
        await callback.answer("⛔ Нет доступа!", show_alert=True)
        return
    
    await callback.message.edit_text(
        "🏆 *Создание турнира*\n"
        "═" * 20 + "\n\n"
        "Введите *название* турнира:",
        parse_mode="Markdown"
    )
    await state.set_state(TournamentState.waiting_for_name)
    await callback.answer()

@dp.message(TournamentState.waiting_for_name)
async def tournament_name(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS:
        await message.answer("⛔ Доступ запрещён!")
        await state.clear()
        return
    
    name = message.text.strip()
    if len(name) < 3:
        await message.answer("❌ Название минимум 3 символа!")
        return
    
    if get_tournament_by_name(name):
        await message.answer("❌ Турнир с таким названием уже существует!")
        return
    
    await state.update_data(name=name)
    await message.answer(
        "📊 Введите *количество участников*:\n"
        "(4, 8, 16, 32)",
        parse_mode="Markdown"
    )
    await state.set_state(TournamentState.waiting_for_count)

@dp.message(TournamentState.waiting_for_count)
async def tournament_count(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS:
        await message.answer("⛔ Доступ запрещён!")
        await state.clear()
        return
    
    try:
        count = int(message.text)
        if count < 2:
            await message.answer("❌ Минимум 2 участника!")
            return
        if count > 64:
            await message.answer("❌ Максимум 64 участника!")
            return
        
        await state.update_data(count=count)
        await message.answer(
            "🏟 Выберите *тип* турнира:\n\n"
            "Введите `команды` или `сборные`",
            parse_mode="Markdown"
        )
        await state.set_state(TournamentState.waiting_for_type)
    except ValueError:
        await message.answer("❌ Введите число!")

@dp.message(TournamentState.waiting_for_type)
async def tournament_type(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS:
        await message.answer("⛔ Доступ запрещён!")
        await state.clear()
        return
    
    type_text = message.text.lower().strip()
    if type_text not in ['команды', 'сборные']:
        await message.answer("❌ Введите `команды` или `сборные`", parse_mode="Markdown")
        return
    
    tournament_type = 'clubs' if type_text == 'команды' else 'teams'
    
    data = await state.get_data()
    name = data['name']
    count = data['count']
    
    users = get_registered_users()
    if len(users) < count:
        await message.answer(
            f"❌ *Недостаточно игроков!*\n"
            f"Нужно: {count}\n"
            f"Зарегистрировано: {len(users)}\n\n"
            f"Сначала зарегистрируйте игроков.",
            parse_mode="Markdown"
        )
        await state.clear()
        return
    
    selected_players = users[:count]
    matches, error = generate_bracket(selected_players, tournament_type)
    
    if error:
        await message.answer(f"❌ {error}")
        await state.clear()
        return
    
    bracket_text = format_bracket(matches, name)
    
    try:
        sent_message = await bot.send_message(CHAT_ID, bracket_text)
        message_id = sent_message.message_id
        
        tournament_id = create_tournament(name, tournament_type, count, message_id)
        save_matches(tournament_id, matches)
        
        await message.answer(
            f"✅ *Турнир '{name}' создан!*\n"
            f"Участников: {count}\n"
            f"Сообщение отправлено в чат!",
            parse_mode="Markdown"
        )
        
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        await message.answer(f"❌ Ошибка: {str(e)}")
    
    await state.clear()

# ===== ЗАПУСК =====

async def main():
    try:
        init_db()
        logger.info("✅ База данных готова")
        
        me = await bot.get_me()
        logger.info(f"✅ Бот запущен: @{me.username}")
        
        try:
            chat = await bot.get_chat(CHAT_ID)
            logger.info(f"✅ Подключен к чату: {chat.title}")
        except Exception as e:
            logger.warning(f"⚠️ Нет доступа к чату: {e}")
            logger.warning("⚠️ Добавьте бота в чат и дайте права!")
        
        logger.info("🚀 Бот готов!")
        await dp.start_polling(bot)
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main())
