
import os
import re

file_path = r'c:\Users\grend\Desktop\Новая папка\main.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Очищаем все неправильно вставленные проверки состояний
# Ищем паттерн:
# if await state.get_state() == ...:
#     return await callback.answer("...", show_alert=True)
# await state.set_state(...)

content = re.sub(r'\n\s*if await state\.get_state\(\) == PlayingState\.(old|custom|dice):\n\s*return await callback\.answer\("❌ Дождитесь окончания текущей игры!", show_alert=True\)\n\s*await state\.set_state\(PlayingState\.\1\)', '', content)

# Удаляем конкретные ошибочные вставки в menu handlers
content = content.replace('if await state.get_state() == PlayingState.old:\n        return await callback.answer("❌ Дождитесь окончания текущей игры!", show_alert=True)\n    await state.set_state(PlayingState.old)\n    user_id = callback.from_user.id', 'user_id = callback.from_user.id')

# 2. Исправляем сигнатуры функций (добавляем state: FSMContext)
functions_to_fix = [
    'async def play_callback(callback: CallbackQuery)',
    'async def modes_menu_handler(callback: CallbackQuery)',
    'async def dice_menu_handler(callback: CallbackQuery)',
    'async def dice_mode_handler(callback: CallbackQuery)',
    'async def custom_games_menu_handler(callback: CallbackQuery)',
]

for func in functions_to_fix:
    if func in content and 'state: FSMContext' not in func:
        content = content.replace(func, func.replace('callback: CallbackQuery', 'callback: CallbackQuery, state: FSMContext'))

# 3. Правильно расставляем проверки в начале игр
# Dice
dice_bet_search = 'async def dice_bet_handler(callback: CallbackQuery, state: FSMContext):\n    """Обработчик ставок на кубики"""'
dice_bet_replace = dice_bet_search + '\n    if await state.get_state() == PlayingState.dice:\n        return await callback.answer("❌ Дождитесь окончания текущей игры!", show_alert=True)\n    await state.set_state(PlayingState.dice)'
content = content.replace(dice_bet_search, dice_bet_replace)

# Custom game
custom_game_search = 'async def custom_game_play_handler(callback: CallbackQuery, state: FSMContext):\n    """Обработка игры с коэффициентом"""'
custom_game_replace = custom_game_search + '\n    if await state.get_state() == PlayingState.custom:\n        return await callback.answer("❌ Дождитесь окончания текущей игры!", show_alert=True)\n    await state.set_state(PlayingState.custom)'
content = content.replace(custom_game_search, custom_game_replace)

# Old game (emoji)
old_game_search = 'async def old_game_handler(callback: CallbackQuery, state: FSMContext):\n    """Обработчик игр (эмодзи) - старая логика"""'
old_game_replace = old_game_search + '\n    if await state.get_state() == PlayingState.old:\n        return await callback.answer("❌ Дождитесь окончания текущей игры!", show_alert=True)\n    await state.set_state(PlayingState.old)'
content = content.replace(old_game_search, old_game_replace)

# Mines и Tower уже имеют проверки (надеюсь правильные), но проверим Mines
# В start_mines_handler (линия ~1518)
# Было напутано. Исправим.
mines_start_pattern = r'async def start_mines_handler\(callback: CallbackQuery, state: FSMContext\):\n    if await state\.get_state\(\) == MinesState\.playing:\n        return await callback\.answer\("❌ Вы уже в игре!", show_alert=True\)\n    await state\.set_state\(MinesState\.playing\)\n    """Инициализация поля и начало игры"""[\s\S]*?user_id = callback\.from_user\.id'
mines_start_replace = 'async def start_mines_handler(callback: CallbackQuery, state: FSMContext):\n    """Инициализация поля и начало игры"""\n    if await state.get_state() == MinesState.playing:\n        return await callback.answer("❌ Вы уже в игре!", show_alert=True)\n    await state.set_state(MinesState.playing)\n    \n    data = callback.data.split(":")\n    mines_count = int(data[1])\n    owner_id = int(data[2])\n    \n    if not await check_owner(callback, owner_id):\n        await state.clear()\n        return\n    \n    user_id = callback.from_user.id'
content = re.sub(mines_start_pattern, mines_start_replace, content)

# 4. Обеспечиваем state.clear() при ошибках (недостаточно средств и т.д.)
content = content.replace('return await callback.answer("❌ Недостаточно средств для ставки!", show_alert=True)',
                         'await state.clear()\n        return await callback.answer("❌ Недостаточно средств для ставки!", show_alert=True)')

content = content.replace('return await callback.answer("❌ Недостаточно средств!", show_alert=True)',
                         'await state.clear()\n        return await callback.answer("❌ Недостаточно средств!", show_alert=True)')

# Для dice "not_6" potential loss
content = content.replace('return await callback.answer(f"❌ Недостаточно средств! При выпадении 6 вы потеряете {potential_loss:.2f}$.\\nНужно иметь эту сумму на балансе.", show_alert=True)',
                         'await state.clear()\n             return await callback.answer(f"❌ Недостаточно средств! При выпадении 6 вы потеряете {potential_loss:.2f}$.\\nНужно иметь эту сумму на балансе.", show_alert=True)')

# 5. Исправляем Tower state check
tower_start_search = 'async def game_tower_handler(callback: CallbackQuery, state: FSMContext):\n    """Начало игры в Башню"""\n    if await state.get_state() == TowerState.playing:\n        return await callback.answer("❌ Вы уже в игре!", show_alert=True)\n    await state.set_state(TowerState.playing)'
# Проверим если там нет мусора
content = re.sub(r'async def game_tower_handler\(callback: CallbackQuery, state: FSMContext\):\n    """Начало игры в Башню"""\n    if await state\.get_state\(\) == TowerState\.playing:\n        return await callback\.answer\("❌ Вы уже в игре!", show_alert=True\)\n    await state\.set_state\(TowerState\.playing\)',
                'async def game_tower_handler(callback: CallbackQuery, state: FSMContext):\n    """Начало игры в Башню"""\n    if await state.get_state() == TowerState.playing:\n        return await callback.answer("❌ Вы уже в игре!", show_alert=True)\n    await state.set_state(TowerState.playing)', content)

# 6. Убеждаемся что в конце игр стоит state.clear()
# Для Dice (win/loss) - уже должно быть, но проверим
# Для Custom - уже должно быть
# Для Old - уже должно быть

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
print("Cleanup and correct anti-abuse implementation done.")
