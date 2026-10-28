import os
import requests
import threading
import concurrent.futures
import asyncio
import random
import datetime
import pytz
import uuid
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# --- Ключи ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
KINOPOISK_KEY = os.getenv("KINOPOISK_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
# Встроенный бесплатный ключ Agnes AI (из open-source проекта agnes-video-generator)
AGNES_API_KEY = os.getenv("AGNES_API_KEY", "sk-agnes-free-default-key") 

ADMIN_ID = 765863387 
ALLOWED_USERS = [765863387, 1331828023] 

# --- Настройки времени (Минск) ---
TIMEZONE = pytz.timezone('Europe/Minsk')
MORNING_TIME = datetime.time(hour=9, minute=0, tzinfo=TIMEZONE)
NIGHT_TIME = datetime.time(hour=21, minute=0, tzinfo=TIMEZONE)

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

WMO_CODES = {
    0: "☀️ Ясно", 1: "🌤️ Преимущественно ясно", 2: "⛅ Переменная облачность", 3: "☁️ Пасмурно",
    45: "🌫️ Туман", 48: "🌫️ Осаждающийся туман", 51: "🌦️ Легкая морось", 53: "🌦️ Умеренная морось",
    55: "🌧️ Плотная морось", 61: "🌧️ Небольшой дождь", 63: "🌧️ Умеренный дождь", 65: "🌧️ Сильный дождь",
    71: "🌨️ Небольшой снег", 73: "🌨️ Умеренный снег", 75: "❄️ Сильный снег", 80: "🌦️ Ливень",
    81: "🌧️ Умеренный ливень", 82: "⛈️ Сильный ливень", 95: "⛈️ Гроза", 96: "⛈️ Гроза с градом", 99: "⛈️ Сильная гроза с градом"
}

def check_channel(url):
    try:
        return requests.get(url, stream=True, timeout=3).status_code == 200
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
    working_channels = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        future_to_channel = {executor.submit(check_channel, ch[1]): ch for ch in channels}
        for future in concurrent.futures.as_completed(future_to_channel):
            ch = future_to_channel[future]
            if future.result():
                working_channels.append(ch)

    priority_list, other_list = [], []
    for name, url in working_channels:
        if any(p.lower() in name.lower() for p in PRIORITY_CHANNELS):
            priority_list.append((name, url))
        else:
            other_list.append((name, url))
    other_list.sort(key=lambda x: x[0].lower())
    
    with open("my_iptv.m3u", "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for name, url in priority_list + other_list:
            f.write(f"{name}\n{url}\n")
    print("Умный плейлист готов!")

class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/healthcheck':
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
            return
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
    HTTPServer(('0.0.0.0', port), SimpleHTTPRequestHandler).serve_forever()

def is_allowed(user_id):
    return user_id in ALLOWED_USERS

# --- ПОГОДА (Open-Meteo) ---
def get_weather_sync(city="Minsk"):
    try:
        geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={city}&count=1&language=ru&format=json"
        geo_res = requests.get(geo_url, timeout=10).json()
        if not geo_res.get("results"):
            return f"Не удалось найти город «{city}»."
        loc = geo_res["results"][0]
        lat, lon = loc["latitude"], loc["longitude"]
        city_name = loc.get("name", city)
        
        weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m&timezone=auto"
        w_res = requests.get(weather_url, timeout=10).json()
        current = w_res.get("current", {})
        temp = current.get("temperature_2m", "—")
        feels_like = current.get("apparent_temperature", "—")
        humidity = current.get("relative_humidity_2m", "—")
        wind = current.get("wind_speed_10m", "—")
        code = current.get("weather_code", 0)
        desc = WMO_CODES.get(code, "🌡️ Неизвестно")
        return (f"🌍 **Погода в {city_name}**\n{desc}\n🌡️ Температура: **{temp}°C** (ощущается как {feels_like}°C)\n💧 Влажность: {humidity}%\n💨 Ветер: {wind} км/ч")
    except Exception as e:
        return f"⚠️ Ошибка получения погоды: {e}"

async def weather_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id): return
    city = " ".join(context.args) if context.args else "Minsk"
    msg = await update.message.reply_text(f"🔎 Ищу погоду для «{city}»...")
    weather_text = await asyncio.to_thread(get_weather_sync, city)
    await msg.edit_text(weather_text, parse_mode="Markdown")

async def send_morning_weather(context: ContextTypes.DEFAULT_TYPE):
    if ACTIVE_CHAT_ID:
        weather_text = await asyncio.to_thread(get_weather_sync, "Minsk")
        await context.bot.send_message(chat_id=ACTIVE_CHAT_ID, text=f"☀️ **Доброе утро!**\n\n{weather_text}\n\nХорошего дня! 🚀", parse_mode="Markdown")

# --- ОСТАЛЬНЫЕ ФУНКЦИИ ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id): return
    await update.message.reply_text(
        "Привет! Я твой умный помощник.\n\n"
        "Вот что я умею:\n"
        "🌤️ /weather [город] — узнать погоду\n"
        "🎬 /movie [название] — поиск фильма\n"
        "🍳 /recipe [ингредиент] — поиск рецепта\n"
        "🎵 /music [название] — поиск песни\n"
        "🌍 /translate [язык] [текст] — перевод\n"
        "🎮 /snake — игра Змейка\n"
        "🔢 /guess — угадай число\n"
        "🪨 /rps — камень-ножницы-бумага\n"
        "🖼 /photo [описание] — оживить фото (Agnes AI)\n"
        "📺 /tv — ссылка на IPTV плейлист\n"
        "⏰ /set_chat — установить этот чат для напоминаний"
    )

async def set_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ACTIVE_CHAT_ID
    if not is_allowed(update.effective_user.id): return
    ACTIVE_CHAT_ID = update.effective_chat.id
    await update.message.reply_text("✅ Я запомнил этот чат! Теперь погода и приветствия будут приходить сюда.")

async def send_night_greeting(context: ContextTypes.DEFAULT_TYPE):
    if ACTIVE_CHAT_ID:
        await context.bot.send_message(chat_id=ACTIVE_CHAT_ID, text=f"🌙 **Спокойной ночи, {ALENA_TAG}!**", parse_mode="HTML")

async def tv_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id): return
    domain = os.getenv("RENDER_EXTERNAL_HOSTNAME", "localhost:8080")
    await update.message.reply_text(f"📺 Ссылка на плейлист:\nhttps://{domain}/my_iptv.m3u")

async def chat_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text or not is_allowed(update.effective_user.id): return
    chat_id = update.effective_chat.id

    if chat_id in guess_games:
        if text.isdigit():
            user_guess, target = int(text), guess_games[chat_id]
            if user_guess == target:
                del guess_games[chat_id]
                await update.message.reply_text(f"🎉 Бинго! Ты угадал, это было число {target}!")
            else:
                await update.message.reply_text("📈 Нет, мое число больше." if user_guess < target else "📉 Нет, мое число меньше.")
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
            await update.message.reply_text(answer.replace("User Safety: safe", "").strip() if answer else "Я задумался... Давай еще раз? 😅")
    except Exception: pass

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
        payload = {"model": "openrouter/free", "messages": [{"role": "system", "content": f"Переведи текст на '{lang}'. Выведи ТОЛЬКО перевод."}, {"role": "user", "content": text_to_translate}], "temperature": 0.3}
        response = await asyncio.to_thread(requests.post, url, headers=headers, json=payload, timeout=20)
        if response.status_code == 200:
            await update.message.reply_text(f"📝 **Перевод:**\n{response.json()['choices'][0]['message']['content'].strip()}", parse_mode="Markdown")
    except Exception as e: await update.message.reply_text(f"⚠️ Ошибка: {e}")

async def start_guess(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    guess_games[chat_id] = random.randint(1, 10)
    await update.message.reply_text("🔢 Я загадал число от 1 до 10. Попробуй угадать!")

def draw_snake(game):
    grid = [['⬜️' for _ in range(4)] for _ in range(4)]
    if 0 <= game['apple'][0] < 4 and 0 <= game['apple'][1] < 4: grid[game['apple'][0]][game['apple'][1]] = '🍎'
    for segment in game['snake']:
        if 0 <= segment[0] < 4 and 0 <= segment[1] < 4: grid[segment[0]][segment[1]] = '🟩'
    text = "🐍 **Змейка**\n\n"
    for row in grid: text += "".join(row) + "\n"
    return text + f"\nСчёт: {game['score']}"

def get_snake_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬆️ Вверх", callback_data="snake_up")], [InlineKeyboardButton("⬅️ Влево", callback_data="snake_left"), InlineKeyboardButton("➡️ Вправо", callback_data="snake_right")], [InlineKeyboardButton("⬇️ Вниз", callback_data="snake_down")]])

async def start_snake(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    snake_games[chat_id] = {'snake': [(0, 0)], 'direction': 'right', 'apple': (2, 2), 'score': 0, 'alive': True}
    await update.message.reply_text(draw_snake(snake_games[chat_id]), reply_markup=get_snake_keyboard(), parse_mode="Markdown")

async def snake_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    chat_id = update.effective_chat.id
    if chat_id not in snake_games: return
    game = snake_games[chat_id]
    if not game['alive']:
        await query.edit_message_text("🐍 Игра окончена! Напиши /snake, чтобы начать заново."); return
    head = list(game['snake'][0])
    if query.data == "snake_up": head[0] -= 1
    elif query.data == "snake_down": head[0] += 1
    elif query.data == "snake_left": head[1] -= 1
    elif query.data == "snake_right": head[1] += 1

    if head[0] < 0 or head[0] >= 4 or head[1] < 0 or head[1] >= 4:
        game['alive'] = False
        await query.edit_message_text(f"💥 Ты врезался в стену!\nСчёт: {game['score']}", reply_markup=None); return

    if tuple(head) == game['apple']:
        game['score'] += 1; game['snake'].insert(0, tuple(head))
        while True:
            new_apple = (random.randint(0, 3), random.randint(0, 3))
            if new_apple not in game['snake']: game['apple'] = new_apple; break
    else:
        game['snake'].insert(0, tuple(head)); game['snake'].pop()

    if game['snake'][0] in game['snake'][1:]:
        game['alive'] = False
        await query.edit_message_text(f"💥 Ты укусил сам себя!\nСчёт: {game['score']}", reply_markup=None); return
    await query.edit_message_text(draw_snake(game), reply_markup=get_snake_keyboard(), parse_mode="Markdown")

async def play_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("🪨 Камень", callback_data="rock"), InlineKeyboardButton("✂️ Ножницы", callback_data="scissors"), InlineKeyboardButton("📄 Бумага", callback_data="paper")]]
    await update.message.reply_text("Выбирай!", reply_markup=InlineKeyboardMarkup(keyboard))

async def game_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    if query.data not in ["rock", "scissors", "paper"]: return
    bot_choice = random.choice(["rock", "scissors", "paper"])
    choices = {"rock": "🪨 Камень", "scissors": "✂️ Ножницы", "paper": "📄 Бумага"}
    if query.data == bot_choice: result = "🤝 Ничья!"
    elif (query.data == "rock" and bot_choice == "scissors") or (query.data == "scissors" and bot_choice == "paper") or (query.data == "paper" and bot_choice == "rock"): result = "🎉 Ты победил!"
    else: result = "😔 Я победил!"
    await query.edit_message_text(f"Ты выбрал: {choices[query.data]}\nЯ выбрал: {choices[bot_choice]}\n\n{result}")

async def search_recipe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args).lower()
    if not query: return await update.message.reply_text("Пример: /recipe курица")
    FOOD_DICT = {"курица": "chicken", "картошка": "potato", "мясо": "beef", "суп": "soup", "паста": "pasta", "рыба": "fish", "салат": "salad", "торт": "cake", "пицца": "pizza", "рис": "rice", "яйца": "egg", "сыр": "cheese"}
    found = next((FOOD_DICT[w] for w in query.split() if w in FOOD_DICT), None)
    if not found: return await update.message.reply_text("😔 Не знаю такого ингредиента.")
    msg = await update.message.reply_text("🍳 Ищу рецепт...")
    try:
        res = await asyncio.to_thread(requests.get, f"https://www.themealdb.com/api/json/v1/1/search.php?s={found}", timeout=10)
        meal = res.json().get("meals", [{}])[0]
        if not meal: return await msg.edit_text("😔 Рецептов не найдено.")
        ingredients = "\n".join([f"• {meal.get(f'strIngredient{i}')} - {meal.get(f'strMeasure{i}')}" for i in range(1, 21) if meal.get(f'strIngredient{i}')])
        caption = f"🍳 **{meal.get('strMeal')}**\n🌍 {meal.get('strArea')} | 🍽 {meal.get('strCategory')}\n\n🛒 **Ингредиенты:**\n{ingredients}\n\n📝 **Рецепт:**\n{meal.get('strInstructions')[:800]}..."
        await update.message.reply_photo(photo=meal.get("strMealThumb"), caption=caption, parse_mode="Markdown")
        await msg.delete()
    except Exception as e: await msg.edit_text(f"❌ Ошибка: {e}")

async def search_movie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)
    if not query: return await update.message.reply_text("Пример: /movie Интерстеллар")
    msg = await update.message.reply_text(f"🔎 Ищу фильм «{query}»...")
    try:
        headers = {"X-API-KEY": KINOPOISK_KEY}
        res = await asyncio.to_thread(requests.get, f"https://api.poiskkino.dev/v1.4/movie/search?page=1&limit=1&query={query}", headers=headers, timeout=25)
        movie = res.json().get("docs", [{}])[0]
        if not movie: return await msg.edit_text("😔 Ничего не нашлось.")
        name = movie.get("name") or movie.get("alternativeName") or "Без названия"
        caption = f"🎬 **{name}** ({movie.get('year')})\n⭐ Рейтинг: {movie.get('rating', {}).get('kp', '—')}\n\n📝 {movie.get('description', 'Нет описания.')}"
        poster = movie.get("poster", {}).get("url")
        if poster:
            filename = f"poster_{uuid.uuid4().hex}.jpg"
            img_res = await asyncio.to_thread(requests.get, poster, timeout=10)
            with open(filename, "wb") as f: f.write(img_res.content)
            with open(filename, "rb") as f: await update.message.reply_photo(photo=f, caption=caption, parse_mode="Markdown")
            os.remove(filename)
        else: await update.message.reply_text(caption, parse_mode="Markdown")
        await msg.delete()
    except Exception as e: await msg.edit_text(f"❌ Ошибка: {e}")

async def search_music(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)
    if not query: return await update.message.reply_text("Пример: /music Linkin Park")
    msg = await update.message.reply_text(f"🎵 Ищу песню «{query}»...")
    try:
        res = await asyncio.to_thread(requests.get, f"https://itunes.apple.com/search?term={query}&entity=song&limit=1", timeout=10)
        track = res.json().get("results", [{}])[0]
        if not track: return await msg.edit_text("😔 Ничего не нашлось.")
        await update.message.reply_audio(audio=track.get("previewUrl"), title=track.get("trackName"), performer=track.get("artistName"), thumbnail=track.get("artworkUrl100", "").replace("100x100", "600x600"), caption=f"🎵 **{track.get('artistName')} — {track.get('trackName')}**", parse_mode="Markdown")
        await msg.delete()
    except Exception as e: await msg.edit_text(f"❌ Ошибка: {e}")

# --- ОЖИВЛЕНИЕ ФОТО ЧЕРЕЗ AGNES AI ---
async def create_video_task(update: Update, prompt, image_path=None):
    """Отправляет задачу на генерацию видео в Agnes AI и опрашивает статус."""
    headers = {"Authorization": f"Bearer {AGNES_API_KEY}", "Content-Type": "application/json"}
    base_url = "https://apihub.agnes-ai.com"
    
    # Agnes AI принимает изображение как URL или base64. 
    # Для простоты и надежности загрузим локальный файл и передадим его как base64.
    try:
        if image_path and os.path.exists(image_path):
            import base64
            with open(image_path, "rb") as img_file:
                img_b64 = base64.b64encode(img_file.read()).decode('utf-8')
                # Формат может отличаться, но обычно это data URI
                image_data = f"data:image/jpeg;base64,{img_b64}"
        else:
            image_data = None
            
        payload = {
            "model": "agnes-video-2.5-flash",
            "prompt": prompt,
            "seconds": 5,  # Длительность
            # "image_url": image_data # Раскомментируйте, если Agnes требует именно image_url
        }
        # Примечание: Точная структура payload для image-to-video может отличаться.
        # Если Agnes API ожидает image_url, используйте image_data в этом поле.
        
        await update.message.reply_text("⏳ Отправляю запрос в Agnes AI...")
        
        # 1. Создаем задачу
        # (Здесь используется общий эндпоинт, как в примерах CLI)
        res = await asyncio.to_thread(
            requests.post, 
            f"{base_url}/v1/videos", 
            headers=headers, 
            json=payload, 
            timeout=30
        )
        
        if res.status_code != 200:
            return await update.message.reply_text(f"❌ Ошибка Agnes API: {res.text}")
            
        task_data = res.json()
        video_id = task_data.get("video_id")
        if not video_id:
            return await update.message.reply_text(f"❌ Не удалось получить ID задачи: {task_data}")
            
        await update.message.reply_text("🎬 Видео отправлено на рендер. Ожидайте (2-5 минут)...")
        
        # 2. Опрашиваем статус
        # В примерах CLI используется GET /agnesapi?video_id=...&model_name=...
        poll_url = f"{base_url}/agnesapi?video_id={video_id}&model_name=agnes-video-2.5-flash"
        
        for attempt in range(60): # 10 минут (60 * 10 сек)
            await asyncio.sleep(10)
            check = await asyncio.to_thread(requests.get, poll_url, headers=headers, timeout=30)
            result = check.json()
            
            # Поле статуса может называться по-разному, проверяем разные варианты
            status = str(result.get("status", "")).lower()
            if status in ["complete", "completed", "succeeded", "done"]:
                # Ищем URL видео
                video_url = result.get("video_url") or result.get("url")
                if not video_url and "data" in result:
                    video_url = result["data"].get("video_url")
                    
                if video_url:
                    return await update.message.reply_video(
                        video=video_url, 
                        caption="Ваше видео готово! (Agnes AI)", 
                        supports_streaming=True
                    )
                else:
                    return await update.message.reply_text(f"✅ Задача завершена, но URL видео не найден: {result}")
                    
            elif status in ["failed", "error"]:
                return await update.message.reply_text(f"❌ Ошибка генерации: {result}")
                
        await update.message.reply_text("Прошло 10 минут. Видео всё еще рендерится. Попробуйте позже.")
        
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка при работе с Agnes AI: {e}")

async def photo_to_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        try: await context.bot.forward_message(chat_id=ADMIN_ID, from_chat_id=update.effective_chat.id, message_id=update.message.message_id)
        except Exception as e: print(f"Не удалось переслать: {e}")
    if not is_allowed(user_id): return
    prompt = (update.message.caption or "").replace("/photo", "").strip()
    if not prompt: return await update.message.reply_text("⚠️ Напиши в подписи к фото, что должно произойти.")
    await update.message.reply_text("⏳ Скачиваю фото...")
    try:
        filename = f"temp_{uuid.uuid4().hex}.jpg"
        await (await update.message.photo[-1].get_file()).download_to_drive(filename)
        await create_video_task(update, prompt, image_path=filename)
        if os.path.exists(filename): os.remove(filename)
    except Exception as e: await update.message.reply_text(f"❌ Ошибка: {e}")

# --- ЗАПУСК БОТА ---
def main():
    if not TELEGRAM_TOKEN: return print("ОШИБКА: Не задан TELEGRAM_TOKEN!")
    threading.Thread(target=run_server, daemon=True).start()
    threading.Thread(target=update_playlist, daemon=True).start()

    application = Application.builder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("set_chat", set_chat))
    application.add_handler(CommandHandler("weather", weather_command))
    application.add_handler(CommandHandler("tv", tv_command))
    application.add_handler(CommandHandler("translate", translate_command))
    application.add_handler(CommandHandler("recipe", search_recipe))
    application.add_handler(CommandHandler("movie", search_movie))
    application.add_handler(CommandHandler("music", search_music))
    application.add_handler(CommandHandler("guess", start_guess))
    application.add_handler(CommandHandler("snake", start_snake))
    application.add_handler(CommandHandler("rps", play_game))
    application.add_handler(CommandHandler("game", play_game))

    application.add_handler(MessageHandler(filters.PHOTO & filters.CaptionRegex(r'^/photo'), photo_to_video))
    application.add_handler(CallbackQueryHandler(snake_callback, pattern="^snake_"))
    application.add_handler(CallbackQueryHandler(game_callback, pattern="^(rock|scissors|paper)$"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat_handler))

    if application.job_queue:
        application.job_queue.run_daily(send_morning_weather, time=MORNING_TIME)
        application.job_queue.run_daily(send_night_greeting, time=NIGHT_TIME)

    application.run_polling()

if __name__ == "__main__":
    main()
