
import os

file_path = r'c:\Users\grend\Desktop\Новая папка\main.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Заменяем все вхождения неправильной строки баланса на правильную
# Мы ищем строку с "Баланс" и "💰", где перед "Баланс" стоит какой-то странный символ
import re
new_content = re.sub(r'f"<b>. Баланс {new_balance:.2f} 💰</b>"', r'f"<b>📋 Баланс {new_balance:.2f} 💰</b>"', content)

# Также уберем лишние user_name = get_user_display_name которые я мог наплодить
# И исправим другие мелкие недочеты

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(new_content)
print("Replacement done.")
