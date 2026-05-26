
import os
import re

file_path = r'c:\Users\grend\Desktop\Новая папка\main.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Мы ищем f"<b>Spins</b>\n👤 {user_name}\n" и следующую строку f"\n"
# И заменяем  на соответствующий эмодзи игры.

# Для Мины (Проигрыш в игре 💣):
content = re.sub(r'f"<b>Spins</b>\\n👤 {user_name}\\n"\n            f".\\n"\n            f"<b>Проигрыш в игре 💣', 
                 r'f"<b>Spins</b>\\n👤 {user_name}\\n"\n            f"�\\n"\n            f"<b>Проигрыш в игре 💣', content)

# Для Башни (Проигрыш в игре 🗼):
content = re.sub(r'f"<b>Spins</b>\\n👤 {user_name}\\n"\n            f".\\n"\n            f"<b>Проигрыш в игре 🗼', 
                 r'f"<b>Spins</b>\\n👤 {user_name}\\n"\n            f"�\\n"\n            f"<b>Проигрыш в игре 🗼', content)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
print("Emoji fixes done.")
