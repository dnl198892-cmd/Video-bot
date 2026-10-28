import os
import requests
import threading
import concurrent.futures
import asyncio
import random
import datetime
import pytz
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
import magic_hour

# --- Ключи ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
MAGIC_HOUR_KEY = os.getenv("MAGIC_HOUR_KEY")
KINOPOISK_KEY = os.getenv("KINOPOISK_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
MAGIC_HOUR_URL = "https://api.magichour.ai/v1"

# Безопасная инициализация клиента Magic Hour
mh_client = magic_hour.Client(token=MAGIC_HOUR_KEY) if MAGIC_HOUR_KEY else None

ADMIN_ID = 765863387 
ALLOWED_USERS = [765863387, 1331828023] 

# --- Настройки напоминалки ---
TIMEZONE = pytz.timezone('Europe/Minsk')
MORNING_TIME = datetime.time(hour=9, minute=0, tzinfo=TIMEZONE)
NIGHT_TIME = datetime.time(hour=21, minute=0, tzinfo=TIMEZONE)

# ID Алёны и ссылка для тегания
ALENA_ID = 1331828023
ALENA_TAG = f"<a href='tg://user?id={ALENA_ID}'>Алёна</a>"
ACTIVE_CHAT_ID = None 

# --- Игры ---
snake_games = {}
guess_games = {}

# --- IPTV настройки ---
IPTV_URLS = [
    "https://iptv-org.github.io/iptv/countries/by.m3u",
    "https://iptv-org.github.io/iptv/countries/ru.m3u",
    "https://iptv-org.github.io/iptv/categories/movies.m3u",
    "https://iptv-org.github.io/iptv/categories/sports.m3u"
]

PRIORITY_CHANNELS = [
    "Беларусь 1", "Беларусь 2", "Беларусь 3", "Беларусь 4", "Беларусь 5", 
    "ОНТ", "НТВ", "Мир", "СТВ", "РТР-Беларусь", "Первый канал", "Россия 1", "Матч ТВ"
]

def check_channel(url):
    try:
        response = requests.get(url, stream=True, timeout=3)
        return response.status_code == 200
    except:
        return False

def update_playlist():
    print("Начинаю умную сборку IPTV плейлиста...")
    channels = []
    for url in IPTV_URLS:
        try:
            res = requests.get(url, timeout=20)
            if res.status_code == 200:
                lines = res.text.split('\n')
                current_name = ""
                for line in lines:
                    if line.startswith('#EXTINF'):
                        current_name = line
                    elif line.startswith('http'):
                        if 'categories' in url:
                            if any(c in current_name for c in "абвгдеёжзийклмнопрстуфхцчшщъыьэюяАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"):
                                channels.append((current_name, line.strip()))
                        else:
                            channels.append((current_name, line.strip()))
        except Exception:
            pass

    channels = list(dict.fromkeys(channels))
    print(f"Всего каналов: {len(channels)}. Проверяю...")

    working_channels = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        future_to_channel = {executor.submit(check_channel, ch[1]): ch for ch in channels}
        for future in concurrent.futures.as_completed(future_to_channel):
            ch = future_to_channel[future]
            if future.result():
                working_channels.append(ch)

    priority_list = []
    other_list = []
    for name, url in working_channels:
        if any(p.lower() in name.lower() for p in PRIORITY_CHANNELS):
            priority_list.append((name, url))
        else:
            other_list.append((name, url))
    other_list.sort(key=lambda x: x[0].lower())
    final_channels = priority_list + other_list

    with open("my_iptv.m3u", "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for name, url in final_channels:
            f.write(f"{name}\n{url}\n")
    print("Умный плейлист готов!")

class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/my_iptv.m3u':
            self.send_response(200)
            self.send_header('Content-type', 'application/vnd.apple.mpegurl')
            self.end_headers()
            try:
                with open("my_iptv.m3u", "rb") as f:
                    self.wfile.write(f.read())
            except FileNotFoundError:
                pass
        else:
            self.send_response(200)
            self.end_headers()

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

def run_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), SimpleHTTPRequestHandler)
    server.serve_forever()

def is_allowed(user_id):
    return user_id in ALLOWED_USERS

async def set_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ACTIVE_CHAT_ID
    if not is_allowed(update.effective_user.id): return
    ACTIVE_CHAT_ID = update.effective_chat.id
    await update.message.reply_text("✅ Я запомнил этот чат! Теперь утренние и вечерние приветствия будут приходить сюда.")

async def send_morning_greeting(context: ContextTypes.DEFAULT_TYPE):
    if ACTIVE_CHAT_ID:
        await context.bot.send_message(
            chat_id=ACTIVE_CHAT_ID, 
            text=f"☀️ **Доброе утро, {ALENA_TAG}!**\nПросыпайся, нас ждут великие дела! ☕",
            parse_mode="HTML"
        )

async def send_night_greeting(context: ContextTypes.DEFAULT_TYPE):
    if ACTIVE_CHAT_ID:
        await context.bot.send_message(
            chat_id=ACTIVE_CHAT_ID, 
            text=f"🌙 **Спокойной ночи, {ALENA_TAG}!**\nСладких снов и отдыхай! 💤",
            parse_mode="HTML"
        )

async def chat_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text: return
        
    chat_id = update.effective_chat.id
    if not is_allowed(update.effective_user.id): return

    if chat_id in guess_games:
        if text.isdigit():
            user_guess = int(text)
            target = guess_games[chat_id]
            if user_guess == target:
                del guess_games[chat_id]
                await update.message.reply_text(f"🎉 Бинго! Ты угадал, это было число {target}!")
            elif user_guess < target:
                await update.message.reply_text("📈 Нет, мое число больше.")
            else:
                await update.message.reply_text("📉 Нет, мое число меньше.")
            return
        else:
            await update.message.reply_text("Пожалуйста, напиши число от 1 до 10.")
            return

    if not OPENROUTER_API_KEY: return

    try:
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": "openrouter/free",
            "messages": [
                {"role": "system", "content": "Ты — дружелюбный Telegram-бот. Отвечай коротко (до 2-3 предложений), с юмором и строго по-русски."},
                {"role": "user", "content": text}
            ],
            "temperature": 0.7, "max_tokens": 200
        }
        response = await asyncio.to_thread(requests.post, url, headers=headers, json=payload, timeout=20)
        
        if response.status_code == 200:
            data = response.json()
            answer = data.get("choices", [{}])[0].get("message", {}).get("content")
            answer = answer.replace("User Safety: safe", "").strip() if answer else "Я задумался... Давай еще раз? 😅"
            await update.message.reply_text(answer)
    except Exception as e:
        print(f"Ошибка ИИ: {e}")

async def translate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not OPENROUTER_API_KEY: return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Пример: `/translate en Привет мир`", parse_mode="Markdown")
        return
    lang, text_to_translate = args[0], " ".join(args[1:])
    await update.message.reply_text(f"🌍 Перевожу на язык `{lang}`...", parse_mode="Markdown")
    try:
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": "openrouter/free",
            "messages": [{"role": "system", "content": f"Ты — переводчик. Переведи текст на язык '{lang}'. Выведи ТОЛЬКО перевод."}, {"role": "user", "content": text_to_translate}],
            "temperature": 0.3, "max_tokens": 500
        }
        response = await asyncio.to_thread(requests.post, url, headers=headers, json=payload, timeout=20)
        if response.status_code == 200:
            await update.message.reply_text(f"📝 **Перевод:**\n{response.json()['choices'][0]['message']['content'].strip()}", parse_mode="Markdown")
        else:
            await update.message.reply_text(f"⚠️ Ошибка API: {response.status_code}")
    except Exception as e:
        await update.message.reply_text(f"⚠️ Ошибка: {e}")

async def start_guess(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    guess_games[chat_id] = random.randint(1, 10)
    await update.message.reply_text("🔢 Я загадал число от 1 до 10. Попробуй угадать! Просто напиши число.")

def draw_snake(game):
    grid = [['⬜️' for _ in range(4)] for _ in range(4)]
    if 0 <= game['apple'][0] < 4 and 0 <= game['apple'][1] < 4: grid[game['apple'][0]][game['apple'][1]] = '🍎'
    for segment in game['snake']:
        if 0 <= segment[0] < 4 and 0 <= segment[1] < 4: grid[segment[0]][segment[1]] = '🟩'
    text = "🐍 **Змейка**\n\n"
    for row in grid: text += "".join(row) + "\n"
    text += f"\nСчёт: {game['score']}"
    return text

def get_snake_keyboard():
    keyboard = [[InlineKeyboardButton("⬆️ Вверх", callback_data="snake_up")], [InlineKeyboardButton("⬅️ Влево", callback_data="snake_left"), InlineKeyboardButton("➡️ Вправо", callback_data="snake_right")], [InlineKeyboardButton("⬇️ Вниз", callback_data="snake_down")]]
    return InlineKeyboardMarkup(keyboard)

async def start_snake(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    snake_games[chat_id] = {'snake': [(0, 0)], 'direction': 'right', 'apple': (2, 2), 'score': 0, 'alive': True}
    await update.message.reply_text(draw_snake(snake_games[chat_id]), reply_markup=get_snake_keyboard(), parse_mode="Markdown")

async def snake_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = update.effective_chat.id
    if chat_id not in snake_games: return
    game = snake_games[chat_id]
    if not game['alive']:
        await query.edit_message_text("🐍 Игра окончена! Напиши /snake, чтобы начать заново.")
        return
    head = list(game['snake'][0])
    action = query.data
    if action == "snake_up": head[0] -= 1
    elif action == "snake_down": head[0] += 1
    elif action == "snake_left": head[1] -= 1
    elif action == "snake_right": head[1] += 1

    if head[0] < 0 or head[0] >= 4 or head[1] < 0 or head[1] >= 4:
        game['alive'] = False
        await query.edit_message_text(f"💥 Ты врезался в стену! Игра окончена.\nСчёт: {game['score']}", reply_markup=None)
        return

    if tuple(head) == game['apple']:
        game['score'] += 1
        game['snake'].insert(0, tuple(head))
        while True:
            new_apple = (random.randint(0, 3), random.randint(0, 3))
            if new_apple not in game['snake']:
                game['apple'] = new_apple
                break
    else:
        game['snake'].insert(0, tuple(head))
        game['snake'].pop()

    if game['snake'][0] in game['snake'][1:]:
        game['alive'] = False
        await query.edit_message_text(f"💥 Ты укусил сам себя! Игра окончена.\nСчёт: {game['score']}", reply_markup=None)
        return
    await query.edit_message_text(draw_snake(game), reply_markup=get_snake_keyboard(), parse_mode="Markdown")

async def play_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("🪨 Камень", callback_data="rock"), InlineKeyboardButton("✂️ Ножницы", callback_data="scissors"), InlineKeyboardButton("📄 Бумага", callback_data="paper")]]
    await update.message.reply_text("Выбирай!", reply_markup=InlineKeyboardMarkup(keyboard))

async def game_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_choice = query.data
    if user_choice not in ["rock", "scissors", "paper"]: return
    bot_choice = random.choice(["rock", "scissors", "paper"])
    choices = {"rock": "🪨 Камень", "scissors": "✂️ Ножницы", "paper": "📄 Бумага"}
    if user_choice == bot_choice: result = "🤝 Ничья!"
    elif (user_choice == "rock" and bot_choice == "scissors") or (user_choice == "scissors" and bot_choice == "paper") or (user_choice == "paper" and bot_choice == "rock"): result = "🎉 Ты победил!"
    else: result = "😔 Я победил!"
    await query.edit_message_text(f"Ты выбрал: {choices[user_choice]}\nЯ выбрал: {choices[bot_choice]}\n\n{result}")

async def search_recipe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args).lower()
    if not query:
        await update.message.reply_text("Напиши ингредиент. Пример: /recipe курица")
        return
    FOOD_DICT = {"курица": "chicken", "картошка": "potato", "мясо": "beef", "суп": "soup", "фасоль": "beans", "паста": "pasta", "рыба": "fish", "салат": "salad", "торт": "cake", "пицца": "pizza", "рис": "rice", "яйца": "egg", "сыр": "cheese"}
    found_ingredient = next((FOOD_DICT[word] for word in query.replace(",", " ").replace(".", " ").split() if word in FOOD_DICT), None)
    if not found_ingredient:
        await update.message.reply_text(f"😔 Не знаю такого. Попробуй: курица, картошка, мясо, суп.")
        return
    await update.message.reply_text(f"🍳 Ищу рецепт...")
    try:
        res = await asyncio.to_thread(requests.get, f"https://www.themealdb.com/api/json/v1/1/search.php?s={found_ingredient}", timeout=10)
        data = res.json()
        if not data.get("meals"):
            await update.message.reply_text(f"😔 Рецептов не найдено.")
            return
        meal = data["meals"][0]
        ingredients = "\n".join([f"• {meal.get(f'strIngredient{i}')} - {meal.get(f'strMeasure{i}')}" for i in range(1, 21) if meal.get(f'strIngredient{i}')])
        caption = f"🍳 **{meal.get('strMeal')}**\n🌍 {meal.get('strArea')} | 🍽 {meal.get('strCategory')}\n\n🛒 **Ингредиенты:**\n{ingredients}\n\n📝 **Рецепт (на англ.):**\n{meal.get('strInstructions')[:800]}..."
        await update.message.reply_photo(photo=meal.get("strMealThumb"), caption=caption, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")

async def search_movie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("Напиши название фильма. Пример: /movie Интерстеллар")
        return
    await update.message.reply_text(f"🔎 Ищу фильм «{query}»...")
    try:
        headers = {"X-API-KEY": KINOPOISK_KEY}
        url = f"https://api.poiskkino.dev/v1.4/movie/search?page=1&limit=1&query={query}"
        res = await asyncio.to_thread(requests.get, url, headers=headers, timeout=25)
        data = res.json()
        if not data.get("docs"):
            await update.message.reply_text("😔 Ничего не нашлось.")
            return
        movie = data["docs"][0]
        name = movie.get("name") or movie.get("alternativeName") or "Без названия"
        caption = f"🎬 **{name}** ({movie.get('year')})\n⭐ Рейтинг: {movie.get('rating', {}).get('kp', '—')}\n\n📝 {movie.get('description', 'Описание отсутствует.')}"
        poster = movie.get("poster", {}).get("url")
        
        if poster:
            filename = f"poster_{uuid.uuid4().hex}.jpg"
            img_res = await asyncio.to_thread(requests.get, poster, timeout=10)
            with open(filename, "wb") as f: 
                f.write(img_res.content)
            with open(filename, "rb") as f: 
                await update.message.reply_photo(photo=f, caption=caption, parse_mode="Markdown")
            os.remove(filename)
        else:
            await update.message.reply_text(caption, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")

async def search_music(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("Напиши название песни. Пример: /music Linkin Park")
        return
    await update.message.reply_text(f"🎵 Ищу песню «{query}»...")
    try:
        res = await asyncio.to_thread(requests.get, f"https://itunes.apple.com/search?term={query}&entity=song&limit=1", timeout=10)
        data = res.json()
        if not data.get("results"):
            await update.message.reply_text("😔 Ничего не нашлось.")
            return
        track = data["results"][0]
        caption = f"🎵 **{track.get('artistName')} — {track.get('trackName')}**\n\n"
        if track.get("previewUrl"):
            await update.message.reply_audio(audio=track.get("previewUrl"), title=track.get("trackName"), performer=track.get("artistName"), thumbnail=track.get("artworkUrl100", "").replace("100x100", "600x600"), caption=caption, parse_mode="Markdown")
        else:
            await update.message.reply_text("Нашел песню, но нет отрывка.")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")

async def create_video_task(update: Update, prompt, image_path=None):
    if not mh_client:
        await update.message.reply_text("❌ Ошибка: Клиент Magic Hour не инициализирован (проверьте MAGIC_HOUR_KEY).")
        return

    headers = {"Authorization": f"Bearer {MAGIC_HOUR_KEY}", "Content-Type": "application/json"}
    
    if image_path:
        await update.message.reply_text("⏳ Загружаю фото в облако Magic Hour...")
        try:
            # ШАГ 1: Загружаем файл через SDK, чтобы получить валидный путь
            # Оборачиваем в to_thread, так как SDK синхронный
            uploaded_file_path = await asyncio.to_thread(
                mh_client.v1.files.upload_file,
                file=image_path
            )
            
            # ШАГ 2: Формируем запрос с ПРАВИЛЬНЫМ путем
            payload = {
                "model": "ltx-2.5", 
                "assets": {"image_file_path": uploaded_file_path}, 
                "end_seconds": 5, 
                "resolution": "480p", 
                "style": {"prompt": prompt}
            }
            endpoint = f"{MAGIC_HOUR_URL}/image-to-video"
            
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка при загрузке фото в Magic Hour: {e}")
            return
    else:
        payload = {
            "model": "ltx-2.5", 
            "prompt": prompt, 
            "end_seconds": 5, 
            "resolution": "480p", 
            "aspect_ratio": "16:9", 
            "style": {"prompt": prompt}
        }
        endpoint = f"{MAGIC_HOUR_URL}/text-to-video"
        
    try:
        res = await asyncio.to_thread(requests.post, endpoint, headers=headers, json=payload, timeout=30)
        if res.status_code != 200:
            await update.message.reply_text(f"❌ Ошибка Magic Hour API: {res.text}")
            return
        data = res.json()
        project_id = data.get("project_id") or data.get("id")
        
        await update.message.reply_text("🎬 Видео отправлено на рендер. Ожидайте (это может занять несколько минут)...")
        
        for i in range(60):
            await asyncio.sleep(10)
            check = await asyncio.to_thread(requests.get, f"{MAGIC_HOUR_URL}/projects/{project_id}", headers=headers, timeout=30)
            result = check.json()
            if str(result.get("status", "")).lower() in ["complete", "completed", "succeeded"]:
                await update.message.reply_video(video=result["downloads"][0].get("url"), caption="Ваше видео готово!", supports_streaming=True)
                return
            elif str(result.get("status", "")).lower() in ["failed", "error"]:
                await update.message.reply_text(f"❌ Ошибка генерации: {result}")
                return
        await update.message.reply_text("Прошло 10 минут. Видео всё еще рендерится.")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

async def photo_to_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        try: await context.bot.forward_message(chat_id=ADMIN_ID, from_chat_id=update.effective_chat.id, message_id=update.message.message_id)
        except Exception as e: print(f"Не удалось переслать фото: {e}")
    if not is_allowed(user_id): return
    
    caption = update.message.caption or ""
    prompt = caption.replace("/photo", "").strip()
    if not prompt:
        await update.message.reply_text("⚠️ Напиши в подписи к фото, что должно произойти.")
        return
        
    await update.message.reply_text("⏳ Скачиваю фото...")
    try:
        photo_file = await update.message.photo[-1].get_file()
        filename = f"temp_{uuid.uuid4().hex}.jpg"
        await photo_file.download_to_drive(filename)
        
        await create_video_task(update, prompt, image_path=filename)
        
        if os.path.exists(filename):
            os.remove(filename)
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка при скачивании/отправке фото: {e}")


# --- ЗАПУСК БОТА (Main) ---
def main():
    if not TELEGRAM_TOKEN:
        print("ОШИБКА: Не задан TELEGRAM_TOKEN!")
        return

    # Запуск IPTV сервера в фоне
    threading.Thread(target=run_server, daemon=True).start()
    # Обновление плейлиста в фоне
    threading.Thread(target=update_playlist, daemon=True).start()

    print("Запускаю Telegram-бота...")
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # Регистрация команд
    application.add_handler(CommandHandler("set_chat", set_chat))
    application.add_handler(CommandHandler("translate", translate_command))
    application.add_handler(CommandHandler("recipe", search_recipe))
    application.add_handler(CommandHandler("movie", search_movie))
    application.add_handler(CommandHandler("music", search_music))
    application.add_handler(CommandHandler("guess", start_guess))
    application.add_handler(CommandHandler("snake", start_snake))
    application.add_handler(CommandHandler("rps", play_game))

    # Обработчик фото (с командой /photo в подписи)
    application.add_handler(MessageHandler(filters.PHOTO & filters.CaptionRegex(r'^/photo'), photo_to_video))

    # Обработчики кнопок (Callback)
    application.add_handler(CallbackQueryHandler(snake_callback, pattern="^snake_"))
    application.add_handler(CallbackQueryHandler(game_callback, pattern="^(rock|scissors|paper)$"))

    # Обработчик обычных текстовых сообщений
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat_handler))

    # Ежедневные задачи (напоминалки)
    if application.job_queue:
        application.job_queue.run_daily(send_morning_greeting, time=MORNING_TIME)
        application.job_queue.run_daily(send_night_greeting, time=NIGHT_TIME)

    application.run_polling()

if __name__ == "__main__":
    main()
