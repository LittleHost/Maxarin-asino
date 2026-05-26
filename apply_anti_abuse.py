
import os
import re

file_path = r'c:\Users\grend\Desktop\Новая папка\main.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Добавляем PlayingState
if 'class PlayingState(StatesGroup):' not in content:
    content = content.replace('class TowerState(StatesGroup):\n    playing = State()', 
                             'class TowerState(StatesGroup):\n    playing = State()\n\nclass PlayingState(StatesGroup):\n    dice = State()\n    custom = State()\n    old = State()')

# 2. Обновляем start_mines_handler (линия ~1450)
start_mines_search = 'async def start_mines_handler(callback: CallbackQuery, state: FSMContext):'
start_mines_replace = start_mines_search + '\n    if await state.get_state() == MinesState.playing:\n        return await callback.answer("❌ Вы уже в игре!", show_alert=True)\n    await state.set_state(MinesState.playing)'
content = content.replace(start_mines_search, start_mines_replace)

# 3. Обновляем game_tower_handler (линия ~1643)
game_tower_search = 'async def game_tower_handler(callback: CallbackQuery, state: FSMContext):'
game_tower_replace = game_tower_search + '\n    if await state.get_state() == TowerState.playing:\n        return await callback.answer("❌ Вы уже в игре!", show_alert=True)\n    await state.set_state(TowerState.playing)'
content = content.replace(game_tower_search, game_tower_replace)

# 4. Обновляем dice_bet_handler (нужно добавить state: FSMContext в аргументы)
dice_bet_search = 'async def dice_bet_handler(callback: CallbackQuery):'
dice_bet_replace = 'async def dice_bet_handler(callback: CallbackQuery, state: FSMContext):'
# И добавляем проверку
dice_bet_logic_search = '    user_id = callback.from_user.id'
dice_bet_logic_replace = '    if await state.get_state() == PlayingState.dice:\n        return await callback.answer("❌ Дождитесь окончания текущей игры!", show_alert=True)\n    await state.set_state(PlayingState.dice)\n    user_id = callback.from_user.id'
# Сначала заменяем сигнатуру
content = content.replace(dice_bet_search, dice_bet_replace)
# Затем логику (но только в dice_bet_handler)
# Используем более специфичный поиск
content = content.replace('async def dice_bet_handler(callback: CallbackQuery, state: FSMContext):\n    """Обработка ставки в кости"""\n    parts = callback.data.split(":")\n    bet_type = parts[1]\n    \n    # Проверка владельца если есть :user_id\n    if len(parts) > 2:\n        owner_id = int(parts[2])\n        if not await check_owner(callback, owner_id):\n            return\n    \n    user_id = callback.from_user.id',
                         'async def dice_bet_handler(callback: CallbackQuery, state: FSMContext):\n    """Обработка ставки в кости"""\n    if await state.get_state() == PlayingState.dice:\n        return await callback.answer("❌ Дождитесь окончания текущей игры!", show_alert=True)\n    await state.set_state(PlayingState.dice)\n    parts = callback.data.split(":")\n    bet_type = parts[1]\n    \n    # Проверка владельца если есть :user_id\n    if len(parts) > 2:\n        owner_id = int(parts[2])\n        if not await check_owner(callback, owner_id):\n            return\n    \n    user_id = callback.from_user.id')

# 5. Очистка состояния в dice_bet_handler (перед return или в конце)
# Нужно найти все места где игра заканчивается
content = content.replace('return await callback.message.answer(text, parse_mode=ParseMode.HTML)',
                         'await state.clear()\n            return await callback.message.answer(text, parse_mode=ParseMode.HTML)')
# И для победы/проигрыша в конце
content = content.replace('await callback.message.answer(text, parse_mode=ParseMode.HTML)\n        if win_amount >= 50:',
                         'await state.clear()\n        await callback.message.answer(text, parse_mode=ParseMode.HTML)\n        if win_amount >= 50:')
content = content.replace('await callback.message.answer(text, parse_mode=ParseMode.HTML)\n\nasync def old_game_handler',
                         'await state.clear()\n        await callback.message.answer(text, parse_mode=ParseMode.HTML)\n\nasync def old_game_handler')

# 6. Обновляем custom_game_play_handler
custom_game_search = 'async def custom_game_play_handler(callback: CallbackQuery):'
custom_game_replace = 'async def custom_game_play_handler(callback: CallbackQuery, state: FSMContext):'
content = content.replace(custom_game_search, custom_game_replace)
# Логика проверки
custom_game_logic_search = '    if not await check_owner(callback, owner_id):\n        return'
custom_game_logic_replace = '    if not await check_owner(callback, owner_id):\n        return\n        \n    if await state.get_state() == PlayingState.custom:\n        return await callback.answer("❌ Дождитесь окончания текущей игры!", show_alert=True)\n    await state.set_state(PlayingState.custom)'
content = content.replace(custom_game_logic_search, custom_game_logic_replace)
# Очистка состояния
content = content.replace('await callback.message.answer(text, parse_mode=ParseMode.HTML)\n    \n    # Обновляем сообщение с меню',
                         'await state.clear()\n    await callback.message.answer(text, parse_mode=ParseMode.HTML)\n    \n    # Обновляем сообщение с меню')

# 7. Обновляем old_game_handler
old_game_search = 'async def old_game_handler(callback: CallbackQuery):'
old_game_replace = 'async def old_game_handler(callback: CallbackQuery, state: FSMContext):'
content = content.replace(old_game_search, old_game_replace)
# Логика проверки
old_game_logic_search = '    user_id = callback.from_user.id'
old_game_logic_replace = '    if await state.get_state() == PlayingState.old:\n        return await callback.answer("❌ Дождитесь окончания текущей игры!", show_alert=True)\n    await state.set_state(PlayingState.old)\n    user_id = callback.from_user.id'
content = content.replace(old_game_logic_search, old_game_logic_replace)
# Очистка состояния (уже сделана выше в шаге 5 частично, но проверим)
# В old_game_handler есть два места: win и loss
# win_amount >= 50:
content = content.replace('await send_alert(callback.bot, user_id, win_amount, "win")',
                         'await state.clear()\n                await send_alert(callback.bot, user_id, win_amount, "win")')
# И в конце блока else (loss)
content = content.replace('await msg.reply(text, parse_mode=ParseMode.HTML)\n\n@dp.callback_query(F.data.startswith("coming_soon"))',
                         'await state.clear()\n            await msg.reply(text, parse_mode=ParseMode.HTML)\n\n@dp.callback_query(F.data.startswith("coming_soon"))')

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
print("Anti-abuse fixes applied.")
