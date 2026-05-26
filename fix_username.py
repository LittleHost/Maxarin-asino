
import os
import re

file_path = r'c:\Users\grend\Desktop\Новая папка\main.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Шаблон для поиска блоков Spins
# Мы ищем f"<b>Spins</b>\n" и вставляем f"👤 {user_name}\n" после него (или emoji)
# Согласно запросу, нужно чтобы ПИСАЛО @USERNAME

# Заменяем во всех местах, где есть Spins
# Мы ищем f"<b>Spins</b>\n" и заменяем на f"<b>Spins</b>\n👤 {user_name}\n"
# Но в некоторых местах user_name может называться по-разному (owner_name и т.д.), 
# хотя я старался везде использовать user_name.
# Давайте проверим.

# В dice_bet_handler: user_name
# В mine_click_handler: user_name
# В mine_cashout_handler: user_name
# В tower_click_handler: user_name
# В custom_game_play_handler: user_name
# В old_game_handler: user_name

new_content = content.replace('f"<b>Spins</b>\\n"', 'f"<b>Spins</b>\\n👤 {user_name}\\n"')

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(new_content)
print("Username inclusion done.")
