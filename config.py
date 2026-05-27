# --- Основные настройки ---
# Токен бота
BOT_TOKEN = "8367454287:AAHCXNDVf1GZ3v5sfNFD_Ic_nD2XDIC_cQs"

# Список ID администраторов
ADMINS = [8981561272]

# --- API Ключи (Заполните свои данные) ---
CRYPTO_PAY_TOKEN = "587134:AAlpkFGA1iy9YDJGt0t7tCqcWmdeMRbsFau" # Токен от @CryptoBot (Crypto Pay API)

# --- Лимиты ---
MIN_DEPOSIT = 0.1  # Минимальное пополнение в USDT
MIN_WITHDRAW = 1   # Минимальный вывод в USDT
MAX_BET = 10000.0  # Максимальная ставка в USDT

# --- Ссылки ---
CHANNEL_URL = "https://t.me/MaxarinCas"           # Ссылка на канал
SUPPORT_URL = "t.me/qwhatss"                      # Ссылка на поддержку/помощь
SITE_URL = "https://t.me/MaxarinCas"              # Ссылка на сайт
CHAT_URL = "https://t.me/+ejlKwLm3lGY0ZjMy"       # Ссылка на чат
ALERTS_CHANNEL = "https://t.me/MaxarinoCasWins"   # Канал для крупных выигрышей/выводов
REFERRAL_LINK_TEMPLATE = "t.me/MaxarinCasinoBot?start=invite_3mCfBuOatgwy" # Пример реф ссылки
OWN_CASINO_LINK = "https://t.me/MandarinProjectt" # Ссылка на "Хочу свое казино"

# --- Тексты ---
TEXTS = {
    "ru": {
        "welcome": (
            f"<b>Привет, добро пожаловать в Maxarin Casino</b>\n\n"
            f"<blockquote>Подписывайся на <a href='{CHANNEL_URL}'>наш канал</a> чтобы следить за новостями и конкурсами.</blockquote>\n\n"
            f"<i>Хочешь свое казино? - @MandarinProjectt</i>"
        ),
        "profile": (
            "<b>#{player_id} {name}</b>\n\n"
            "<blockquote><b>💳 Баланс — {balance:.2f} USDT\n"
            "Ваш VIP прогресс — {rank_progress:.0f}%\n"
            "{progress_bar}\n"
            "{current_rank} → {next_rank}\n\n"
            "📊 Оборот — {turnover:.2f} USDT\n"
            "🎮 Сыграно — {bets} ставок\n"
            "🕒 Аккаунту — {days}</b></blockquote>"
        ),
        "chats": "<blockquote>🗨 Игровые чаты это отличное место чтобы найти друзей, обсудить игру или поднять денег в конкурсах и раздачах!</blockquote>",
        "referral": (
            "<blockquote>🐈‍⬛ <b>Реф. система — 3 уровня</b> ❞</blockquote>\n\n"
            "1 📈 60% | 0 👤 | 0.00 USDT | 0.00 USDT\n"
            "2 📈 30% | 0 👤 | 0.00 USDT | 0.00 USDT\n"
            "3 📈 10% | 0 👤 | 0.00 USDT | 0.00 USDT\n\n"
            "<b>Ваша ссылка</b>\n"
            f"<code>{REFERRAL_LINK_TEMPLATE}</code>\n\n"
            "<b>Общий доход</b>\n"
            "0.00 USDT"
        ),
        "play": (
            "<b>💣 Выбирайте мини-игру!</b>\n\n"
            "<blockquote>Баланс — {balance:.2f} USDT\n"
            "Ставка — {bet:.2f} USDT</blockquote>\n\n"
            "<i>Пополняй и сыграй на реальные деньги</i>"
        ),
        "modes_menu": (
            "<b>💣 Режимы игры</b>\n\n"
            "<blockquote>Баланс — {balance:.2f} USDT\n"
            "Ставка — {bet:.2f} USDT</blockquote>\n\n"
            "<i>Выбери игру и испытай удачу</i>"
        ),
        "mines_main": (
            "<b>💣 Мины</b>\n\n"
            "Игрок #{player_id}\n"
            "<blockquote>👛 Баланс — {balance:,.2f} USDT\n"
            "Ставка — {bet:,.2f} USDT</blockquote>\n\n"
            "Выбрано — {mines} 💣"
        ),
        "mines_select": (
            "💣 <b>Выберите количество мин</b>\n\n"
            "Выбрано — <b>{mines} 💣</b>\n\n"
            "<blockquote>{coefs}</blockquote>"
        ),
        "mines_playing": (
            "<blockquote><b>💣 Мины · {mines} 💣</b></blockquote>\n\n"
            "<b>{bet:,.2f} USDT × {coef:.2f} ➔ {win:,.2f} USDT</b>\n\n"
            "<blockquote>{coefs}</blockquote>"
        ),
        "deposit_method": "💳 Выберите способ пополнения",
        "enter_deposit_amount": "💰 Введите сумму пополнения в <b>USDT</b>\n\n<i>Минимальная сумма: {min_amount:.2f} USDT</i>",
        "enter_withdraw_amount": "📥 Введите сумму вывода в <b>USDT</b>\n\n<i>Минимальная сумма: {min_amount:.2f} USDT</i>",
        "deposit_created": "👇 Нажмите ниже, чтобы пополнить баланс",
        "check_payment": "✅ Проверить оплату",
        "payment_success": "✅ Баланс успешно пополнен на <b>{amount:.2f} USDT</b>!",
        "payment_not_found": "❌ Оплата не найдена. Пожалуйста, оплатите счет и нажмите кнопку еще раз.",
        "error_min_deposit": "❌ Минимальная сумма пополнения — {min_amount:.2f} USDT",
        "error_min_withdraw": "❌ Минимальная сумма вывода — {min_amount:.2f} USDT",
        "language_select": "🌐 Выберите язык бота",
        "privacy": (
            "<b>🥷 Приватность</b>\n\n"
            "— <i>Крупные ставки и победы в канале</i>\n"
            "— <i>Топ игроков по обороту и балансу</i>\n"
            "— <i>Ставки в чатах</i>\n\n"
            "Отображается: {display_mode}"
        ),
        "privacy_set_nickname": "📝 Введите ваш новый псевдоним (до 15 символов):",
        "nickname_updated": "✅ Псевдоним успешно обновлен!",
        "privacy_updated": "✅ Настройки приватности обновлены!",
        "stats_text": (
            "📊 <b>Статистика {name}</b>\n\n"
            "🎮 Сыграно — {bets} ставок\n"
            "📊 Оборот — {turnover:.2f} USDT\n"
            "🕒 Аккаунту — {days} {days_label}\n\n"
            "📥 Пополнений — {deposits:.2f} USDT\n"
            "📤 Выводов — {withdrawals:.2f} USDT"
        ),
        "buttons": {
            "play": "🎮 Играть",
            "chats": "💬 Игровые чаты",
            "profile": "👤 Профиль",
            "referral": "👥 Реф. программа",
            "language": "🌐 Язык",
            "back": "⬅️ Назад",
            "deposit": "💸 Пополнить",
            "withdraw": "📥 Вывести",
            "stats": "📊 Статистика",
            "privacy": "🥷 Приватность",
            "bonuses": "🍬 Бонусы",
            "main_chat": "🇷🇺 Основной чат",
            "claim_ref": "💰 Забрать реферальные",
            "invite_friend": "👥 Пригласить друга",
            "details": "📖 Подробнее",
            "game_dice": "🎲",
            "game_soccer": "⚽",
            "game_slots": "🎰",
            "provider_tg": "🎲 Telegram",
            "provider_custom": "🐳 Авторские",
            "site": "🌐 Сайт",
            "change_bet": "✏️ Изменить ставку",
            "crypto_bot": "🤖 Crypto Bot",
            "lang_ru": "🇷🇺 Русский",
            "lang_en": "🇺🇸 English",
            "pay": "💸 Пополнить · {amount:.2f} USDT",
            "change_amount": "🔄 Изменить сумму",
            "settings": "⚙️ Настройки",
            "transactions": "📋 Транзакции",
            "game_history": "📜 История игр",
            "modes": "🎮 Режимы",
            "game_mines": "💣 Мины",
            "game_tower": "🗼 Башня",
            "own_casino": "🎰 Хочу свое казино,
            "checks": "🎫 Чеки",
            "create_check": "✨ Создать чек", 
            "my_checks": "📋 Мои чеки"
        }
    },
    "en": {
        "welcome": (
            f"<b>Hello, welcome to Maxarin Casino</b>\n\n"
            f"<blockquote>Subscribe to <a href='{CHANNEL_URL}'>our channel</a> to follow news and contests.</blockquote>\n\n"
            f"<i>Want your own casino? - @MandarinProjectt</i>"
        ),
        "profile": (
            "<b>#{player_id} {name}</b>\n\n"
            "<blockquote>💳 Balance — {balance:.2f} USDT\n\n"
            "Your VIP progress — {rank_progress:.0f}%\n"
            "{progress_bar}\n"
            "{current_rank} → {next_rank}\n\n"
            "📊 Turnover — {turnover:.2f} USDT\n"
            "🎮 Played — {bets} bets\n"
            "🕒 Account — {days}</blockquote>"
        ),
        "chats": "<blockquote>🗨 Game chats are a great place to find friends, discuss the game or make money in contests and giveaways!</blockquote>",
        "referral": (
            "<blockquote>🐈‍⬛ <b>Ref. system — 3 levels</b> ❞</blockquote>\n\n"
            "1 📈 60% | 0 👤 | 0.00 USDT | 0.00 USDT\n"
            "2 📈 30% | 0 👤 | 0.00 USDT | 0.00 USDT\n"
            "3 📈 10% | 0 👤 | 0.00 USDT | 0.00 USDT\n\n"
            "<b>Your link</b>\n"
            f"<code>{REFERRAL_LINK_TEMPLATE}</code>\n\n"
            "<b>Total income</b>\n"
            "0.00 USDT"
        ),
        "play": (
            "<b>💣 Choose a mini-game!</b>\n\n"
            "<blockquote>Balance — {balance:.2f} USDT\n"
            "Bet — {bet:.2f} USDT</blockquote>\n\n"
            "<i>Deposit and play for real money</i>"
        ),
        "modes_menu": (
            "<b>💣 Game modes</b>\n\n"
            "<blockquote>Balance — {balance:.2f} USDT\n"
            "Bet — {bet:.2f} USDT</blockquote>\n\n"
            "<i>Choose your game and try your luck</i>"
        ),
        "deposit_method": "💳 Choose deposit method",
        "enter_deposit_amount": "💰 Enter deposit amount in <b>USDT</b>\n\n<i>Minimum amount: {min_amount:.2f} USDT</i>",
        "enter_withdraw_amount": "📥 Enter withdrawal amount in <b>USDT</b>\n\n<i>Minimum amount: {min_amount:.2f} USDT</i>",
        "deposit_created": "👇 Click below to top up your balance",
        "check_payment": "✅ Check Payment",
        "payment_success": "✅ Balance successfully topped up by <b>{amount:.2f} USDT</b>!",
        "payment_not_found": "❌ Payment not found. Please pay the invoice and click the button again.",
        "error_min_deposit": "❌ Minimum deposit amount is {min_amount:.2f} USDT",
        "error_min_withdraw": "❌ Minimum withdrawal amount is {min_amount:.2f} USDT",
        "language_select": "🌐 Choose bot language",
        "privacy": (
            "<b>🥷 Privacy</b>\n\n"
            "— <i>Big bets and wins in channel</i>\n"
            "— <i>Top players by turnover and balance</i>\n"
            "— <i>Bets in chats</i>\n\n"
            "Displayed: {display_mode}"
        ),
        "privacy_set_nickname": "📝 Enter your new nickname (up to 15 characters):",
        "nickname_updated": "✅ Nickname successfully updated!",
        "privacy_updated": "✅ Privacy settings updated!",
        "stats_text": (
            "📊 <b>Statistics {name}</b>\n\n"
            "🎮 Played — {bets} bets\n"
            "📊 Turnover — {turnover:.2f} USDT\n"
            "🕒 Account — {days} {days_label}\n\n"
            "📥 Deposits — {deposits:.2f} USDT\n"
            "📤 Withdrawals — {withdrawals:.2f} USDT"
        ),
        "buttons": {
            "play": "🎮 Play",
            "chats": "💬 Game Chats",
            "profile": "👤 Profile",
            "referral": "👥 Referral Program",
            "language": "🌐 Language",
            "back": "⬅️ Back",
            "deposit": "💸 Deposit",
            "withdraw": "📥 Withdraw",
            "stats": "📊 Statistics",
            "privacy": "🥷 Privacy",
            "bonuses": "🍬 Bonuses",
            "main_chat": "🇺🇸 Main Chat",
            "claim_ref": "💰 Claim referral",
            "invite_friend": "👥 Invite a friend",
            "details": "📖 Details",
            "game_dice": "🎲",
            "game_soccer": "⚽",
            "game_slots": "🎰",
            "provider_tg": "🎲 Telegram",
            "provider_custom": "🐳 Custom",
            "site": "🌐 Site",
            "change_bet": "✏️ Change bet",
            "crypto_bot": "🤖 Crypto Bot",
            "lang_ru": "🇷🇺 Russian",
            "lang_en": "🇺🇸 English",
            "pay": "💸 Deposit · {amount:.2f} USDT",
            "change_amount": "🔄 Change amount",
            "settings": "⚙️ Settings",
            "transactions": "📋 Transactions",
            "game_history": "📜 Game History",
            "modes": "🎮 Modes",
            "game_mines": "💣 Mines",
            "game_tower": "🗼 Tower",
            "own_casino": "🎰 Want your own casino"
        }
    }
}
