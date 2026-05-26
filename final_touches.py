
import os
import re

file_path = r'c:\Users\grend\Desktop\Новая папка\main.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Фикс отступов и двойного state.clear()
content = content.replace('        if win_amount >= 50:\n            await state.clear()\n                await send_alert(callback.bot, user_id, win_amount, "win")',
                         '        if win_amount >= 50:\n            await send_alert(callback.bot, user_id, win_amount, "win")')

# 2. Инициализация win_coef
if '    dice_count = 1' in content and '    win_coef = 0' not in content:
    content = content.replace('    dice_count = 1', '    dice_count = 1\n    win_coef = 0')

# 3. Добавляем state.clear() в check_owner ранние выходы
pattern_owner = r'if not await check_owner\(callback, owner_id\):\n\s*return'
content = re.sub(pattern_owner, 'if not await check_owner(callback, owner_id):\n        await state.clear()\n        return', content)

# 4. Фикс для Mines (был напутан start_mines_handler)
# Удаляем лишние проверки
content = content.replace('    if await state.get_state() == PlayingState.custom:\n        return await callback.answer("❌ Дождитесь окончания текущей игры!", show_alert=True)\n    await state.set_state(PlayingState.custom)\n        \n    if await state.get_state() == PlayingState.old:\n        return await callback.answer("❌ Дождитесь окончания текущей игры!", show_alert=True)\n    await state.set_state(PlayingState.old)', '')

# 5. Проверим TowerState check
content = content.replace('if await state.get_state() == TowerState.playing:\n        return await callback.answer("❌ Вы уже в игре!", show_alert=True)\n    await state.set_state(TowerState.playing)',
                         'if await state.get_state() == TowerState.playing:\n        return await callback.answer("❌ Вы уже в игре!", show_alert=True)\n    await state.set_state(TowerState.playing)')

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
print("Final touches applied.")
