import os
import requests
import threading
import concurrent.futures
import asyncio
import random
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
mh_client = magic_hour.Client(token=MAGIC_HOUR_KEY)

# --- Настройки доступа ---
ADMIN_ID = 765863387 
# Здесь твой ID и ID Алёны
ALLOWED_USERS = [765863387, 1331828023] 

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

# --- Умный чат через OpenRouter ---
async def chat_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text:
        return
        
    chat_id = update.effective_chat.id

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

    if not OPENROUTER_API_KEY:
        await update.message.reply_text("⚠️ В настройках Render не добавлен ключ `OPENROUTER_API_KEY`.")
        return

    try:
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "openrouter/free",
            "messages": [
                {"role": "system", "content": "Ты — дружелюбный Telegram-бот. Отвечай коротко (до 2-3 предложений), с юмором и строго по-русски. Не пиши 'User Safety', не используй английский язык в ответах."},
                {"role": "user", "content": text}
            ],
            "temperature": 0.7,
            "max_tokens": 200
        }
        
        response = await asyncio.to_thread(requests.post, url, headers=headers, json=payload, timeout=20)
        
        if response.status_code == 200:
            data = response.json()
            answer = data["choices"][0]["message"]["content"]
            answer = answer.replace("User Safety: safe", "").strip()
            
            if not answer:
                answer = "Я задумался... Давай еще раз? 😅"
            
            await update.message.reply_text(answer)
        else:
            await update.message.reply_text(f"⚠️ Нейросеть выдала ошибку: `{response.status_code}`. Попробуй позже.", parse_mode="Markdown")
            
    except Exception as e:
        await update.message.reply_text(f"⚠️ Ошибка подключения к ИИ: `{e}`", parse_mode="Markdown")

# --- ФУНКЦИЯ ПЕРЕВОДА ---
async def translate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not OPENROUTER_API_KEY:
        await update.message.reply_text("Для перевода нужен ключ OpenRouter.")
        return

    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Пример использования:\n`/translate en Привет мир` (на англ.)\n`/translate ru Hello world` (на рус.)", parse_mode="Markdown")
        return

    lang = args[0]
    text_to_translate = " ".join(args[1:])

    await update.message.reply_text(f"🌍 Перевожу на язык `{lang}`...", parse_mode="Markdown")

    try:
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "openrouter/free",
            "messages": [
                {"role": "system", "content": f"Ты — переводчик. Переведи текст на язык '{lang}'. Выведи ТОЛЬКО перевод."},
                {"role": "user", "content": text_to_translate}
            ],
            "temperature": 0.3,
            "max_tokens": 500
        }
        
        response = await asyncio.to_thread(requests.post, url, headers=headers, json=payload, timeout=20)
        
        if response.status_code == 200:
            data = response.json()
            answer = data["choices"][0]["message"]["content"].strip()
            await update.message.reply_text(f"📝 **Перевод:**\n{answer}", parse_mode="Markdown")
        else:
            await update.message.reply_text(f"⚠️ Ошибка API при переводе: {response.status_code}")
    except Exception as e:
        await update.message.reply_text(f"⚠️ Ошибка при переводе: {e}")

# --- Функции игр ---
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
    keyboard = [
        [InlineKeyboardButton("⬆️ Вверх", callback_data="snake_up")],
        [InlineKeyboardButton("⬅️ Влево", callback_data="snake_left"), InlineKeyboardButton("➡️ Вправо", callback_data="snake_right")],
        [InlineKeyboardButton("⬇️ Вниз", callback_data="snake_down")]
    ]
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

# --- Кулинария, Кино, Музыка, Видео ---
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
        res = requests.get(f"https://www.themealdb.com/api/json/v1/1/search.php?s={found_ingredient}", timeout=10)
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
        res = requests.get(url, headers=headers, timeout=25)
        data = res.json()
        if not data.get("docs"):
            await update.message.reply_text("😔 Ничего не нашлось.")
            return
        movie = data["docs"][0]
        name = movie.get("name") or movie.get("alternativeName") or "Без названия"
        caption = f"🎬 **{name}** ({movie.get('year')})\n⭐ Рейтинг: {movie.get('rating', {}).get('kp', '—')}\n\n📝 {movie.get('description', 'Описание отсутствует.')}"
        poster = movie.get("poster", {}).get("url")
        if poster:
            img_res = requests.get(poster, timeout=10)
            with open("poster_temp.jpg", "wb") as f: f.write(img_res.content)
            with open("poster_temp.jpg", "rb") as f: await update.message.reply_photo(photo=f, caption=caption, parse_mode="Markdown")
            os.remove("poster_temp.jpg")
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
        res = requests.get(f"https://itunes.apple.com/search?term={query}&entity=song&limit=1", timeout=10)
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
    headers = {"Authorization": f"Bearer {MAGIC_HOUR_KEY}", "Content-Type": "application/json"}
    if image_path:
        payload = {"model": "ltx-2.5", "assets": {"image_file_path": image_path}, "end_seconds": 5, "resolution": "480p", "style": {"prompt": prompt}}
        endpoint = f"{MAGIC_HOUR_URL}/image-to-video"
    else:
        payload = {"model": "ltx-2.5", "prompt": prompt, "end_seconds": 5, "resolution": "480p", "aspect_ratio": "16:9", "style": {"prompt": prompt}}
        endpoint = f"{MAGIC_HOUR_URL}/text-to-video"
    try:
        res = requests.post(endpoint, headers=headers, json=payload, timeout=30)
        if res.status_code != 200:
            await update.message.reply_text(f"❌ Ошибка Magic Hour: {res.text}")
            return
        data = res.json()
        project_id = data.get("project_id") or data.get("id")
        for i in range(60):
            await asyncio.sleep(10)
            check = requests.get(f"{MAGIC_HOUR_URL}/projects/{project_id}", headers=headers, timeout=30)
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
    await update.message.reply_text("⏳ Получил фото, начинаю обработку...")
    photo_file = await update.message.photo[-1].get_file()
    temp_image_path = "temp_image.jpg"
    await photo_file.download_to_drive(custom_path=temp_image_path)
    uploaded_file_path = mh_client.v1.files.upload_image(temp_image_path)
    os.remove(temp_image_path)
    await create_video_task(update, prompt, image_path=uploaded_file_path)

async def text_photo_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Чтобы оживить фото, прикрепи его к сообщению и в подписи напиши, что должно произойти.")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    print(f"Ошибка: {context.error}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id): 
        await update.message.reply_text("⛔ У вас нет доступа к этому боту.")
        return
    await update.message.reply_text(
        "Привет, хозяин! Я твой умный помощник.\n\n"
        "🎬 **Видео:** Отправь фото с подписью.\n🍿 **Кино:** /movie Название.\n🎵 **Музыка:** /music Название.\n📺 **ТВ:** /tv.\n🍳 **Еда:** /recipe Ингредиент.\n"
        "🌍 **Перевод:** /translate en Текст.\n🎮 **Игры:** /game, /snake, /guess, /mario.",
        parse_mode="Markdown"
    )

async def send_tv_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id): return
    await update.message.reply_text(f"📺 Ссылка на плейлист:\n\n`https://video-bot-kf62.onrender.com/my_iptv.m3u`", parse_mode="Markdown")

def main():
    threading.Thread(target=run_server, daemon=True).start()
    threading.Thread(target=update_playlist, daemon=True).start()
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("tv", send_tv_link))
    app.add_handler(CommandHandler("movie", search_movie))
    app.add_handler(CommandHandler("music", search_music))
    app.add_handler(CommandHandler("recipe", search_recipe)) 
    app.add_handler(CommandHandler("translate", translate_command))
    app.add_handler(CommandHandler("game", play_game))      
    app.add_handler(CommandHandler("snake", start_snake)) 
    app.add_handler(CommandHandler("guess", start_guess))  
    app.add_handler(CommandHandler("mario", lambda u, c: u.message.reply_text("🍄 Игра Марио временно на тех. работах. Скоро вернется!"))) 
    app.add_handler(CommandHandler("photo", text_photo_prompt))
    
    app.add_handler(CallbackQueryHandler(game_callback, pattern="^(rock|scissors|paper)$"))
    app.add_handler(CallbackQueryHandler(snake_callback, pattern="^snake_")) 
    
    app.add_handler(MessageHandler(filters.PHOTO, photo_to_video))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat_handler)) 
    app.add_error_handler(error_handler)
    
    print("Бот и IPTV сервер запущены!")
    app.run_polling()

if __name__ == "__main__":
    main()
