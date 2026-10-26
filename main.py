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
MAGIC_HOUR_URL = "https://api.magichour.ai/v1"
mh_client = magic_hour.Client(token=MAGIC_HOUR_KEY)

# --- Настройки безопасности ---
# Ваш ID (админ)
ADMIN_ID = 765863387 
# Сюда можно добавлять ID доверенных лиц через запятую: [765863387, 123456789]
ALLOWED_USERS = [ADMIN_ID] 

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

# --- Проверка доступа ---
def is_allowed(user_id):
    return user_id in ALLOWED_USERS

# --- Кулинария ---
async def search_recipe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id): return
    query = " ".join(context.args).lower()
    if not query:
        await update.message.reply_text("Напиши название блюда или главный ингредиент. Пример: /recipe курица")
        return

    FOOD_DICT = {
        "курица": "chicken", "курицы": "chicken", "курицу": "chicken", "курицей": "chicken", "цыпленок": "chicken",
        "картошка": "potato", "картошки": "potato", "картошку": "potato", "картофель": "potato",
        "мясо": "beef", "мяса": "beef", "говядина": "beef",
        "свинина": "pork", "свинины": "pork",
        "суп": "soup", "супа": "soup", "бульон": "soup", "фасоль": "beans", "фасолевый": "beans",
        "паста": "pasta", "макароны": "pasta", "спагетти": "pasta",
        "рыба": "fish", "рыбы": "fish", "лосось": "salmon",
        "салат": "salad", "салата": "salad",
        "торт": "cake", "пирог": "cake", "кекс": "cake",
        "пицца": "pizza", "рис": "rice", "яйца": "egg", "сыр": "cheese"
    }

    found_ingredient = None
    for word in query.replace(",", " ").replace(".", " ").split():
        if word in FOOD_DICT:
            found_ingredient = FOOD_DICT[word]
            break

    if not found_ingredient:
        await update.message.reply_text(
            f"😔 Я не знаю такого ингредиента.\n"
            f"Попробуй: курица, картошка, мясо, суп, фасоль, паста, рыба."
        )
        return

    await update.message.reply_text(f"🍳 Ищу рецепт...")

    try:
        url = f"https://www.themealdb.com/api/json/v1/1/search.php?s={found_ingredient}"
        res = requests.get(url, timeout=10)
        data = res.json()

        if not data.get("meals"):
            await update.message.reply_text(f"😔 Рецептов с «{found_ingredient}» не найдено.")
            return
            
        meal = data["meals"][0]
        name = meal.get("strMeal", "Блюдо")
        category = meal.get("strCategory", "")
        area = meal.get("strArea", "")
        instructions = meal.get("strInstructions", "Инструкции отсутствуют.")
        image_url = meal.get("strMealThumb")
        
        ingredients = []
        for i in range(1, 21):
            ing = meal.get(f"strIngredient{i}")
            meas = meal.get(f"strMeasure{i}")
            if ing and ing.strip():
                ingredients.append(f"• {ing} - {meas}")
                
        ing_text = "\n".join(ingredients)
        
        caption = f"🍳 **{name}**\n🌍 Кухня: {area} | 🍽 Категория: {category}\n\n🛒 **Ингредиенты:**\n{ing_text}\n\n📝 **Рецепт (на англ.):**\n{instructions[:800]}..."
        
        await update.message.reply_photo(photo=image_url, caption=caption, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка при поиске рецепта: {e}")

# --- Текстовый Марио ---
async def start_mario(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id): return
    
    keyboard = [
        [InlineKeyboardButton("🏃 Идти вперёд", callback_data="mario_forward")],
        [InlineKeyboardButton("🪙 Собирать монеты", callback_data="mario_coins")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("🍄 **Добро пожаловать в Текстового Марио!**\n\nТы на зеленой поляне. Перед тобой замок, а вокруг разбросаны монеты. Что будешь делать?", reply_markup=reply_markup)

async def mario_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data == "mario_forward":
        keyboard = [
            [InlineKeyboardButton("🍄 Съесть гриб", callback_data="mario_eat")],
            [InlineKeyboardButton("💥 Прыгнуть на Гумбу", callback_data="mario_jump")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("🏰 Ты подошел к замку. Вдруг из трубы вылезает Гумба! Рядом лежит странный гриб. Что делаешь?", reply_markup=reply_markup)
        
    elif data == "mario_coins":
        keyboard = [
            [InlineKeyboardButton("🏰 Всё равно идти к замку", callback_data="mario_forward")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("🪙 Ты собрал 100 монет и получил +1 жизнь! Но монеты кончились. Пора двигаться к замку.", reply_markup=reply_markup)
        
    elif data == "mario_eat":
        await query.edit_message_text("🍄 Ты съел гриб и стал супер-Марио! Одним прыжком ты сносишь Гумбу и спасаешь принцессу. **Ты победил!** 🎉")
        
    elif data == "mario_jump":
        await query.edit_message_text("💥 Ты прыгнул на Гумбу и раздавил его! Ворота замка открыты. Принцесса спасена! **Ты победил!** 🎉")

# --- Игры ---
async def play_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id): return
    keyboard = [
        [
            InlineKeyboardButton("🪨 Камень", callback_data="rock"),
            InlineKeyboardButton("✂️ Ножницы", callback_data="scissors"),
            InlineKeyboardButton("📄 Бумага", callback_data="paper"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Выбирай!", reply_markup=reply_markup)

async def game_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_choice = query.data
    bot_choice = random.choice(["rock", "scissors", "paper"])
    choices = {"rock": "🪨 Камень", "scissors": "✂️ Ножницы", "paper": "📄 Бумага"}
    if user_choice == bot_choice:
        result = "🤝 Ничья!"
    elif (user_choice == "rock" and bot_choice == "scissors") or \
         (user_choice == "scissors" and bot_choice == "paper") or \
         (user_choice == "paper" and bot_choice == "rock"):
        result = "🎉 Ты победил!"
    else:
        result = "😔 Я победил!"
    await query.edit_message_text(f"Ты выбрал: {choices[user_choice]}\nЯ выбрал: {choices[bot_choice]}\n\n{result}")

# --- Базовые функции ---
async def search_movie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id): return
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("Напиши название фильма. Пример: /movie Интерстеллар")
        return
    await update.message.reply_text(f"🔎 Ищу фильм «{query}»...")
    try:
        headers = {"X-API-KEY": KINOPOISK_KEY}
        url = f"https://api.poiskkino.dev/v1.4/movie/search?page=1&limit=1&query={query}"
        res = requests.get(url, headers=headers, timeout=25)
        res.raise_for_status()
        data = res.json()
        
        if not data.get("docs"):
            await update.message.reply_text("😔 Ничего не нашлось.")
            return
            
        movie = data["docs"][0]
        name = movie.get("name") or movie.get("alternativeName") or "Без названия"
        year = movie.get("year", "—")
        rating = movie.get("rating", {}).get("kp", "—")
        description = movie.get("description", "Описание отсутствует.")
        poster = movie.get("poster", {}).get("url")
        caption = f"🎬 **{name}** ({year})\n⭐ Рейтинг: {rating}\n\n📝 {description}"
        
        if poster:
            try:
                img_res = requests.get(poster, timeout=10)
                img_res.raise_for_status()
                with open("poster_temp.jpg", "wb") as f:
                    f.write(img_res.content)
                with open("poster_temp.jpg", "rb") as f:
                    await update.message.reply_photo(photo=f, caption=caption, parse_mode="Markdown")
                os.remove("poster_temp.jpg")
            except Exception:
                await update.message.reply_text(caption, parse_mode="Markdown")
        else:
            await update.message.reply_text(caption, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")

async def search_music(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id): return
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("Напиши название песни. Пример: /music Linkin Park")
        return
    await update.message.reply_text(f"🎵 Ищу песню «{query}»...")
    try:
        url = f"https://itunes.apple.com/search?term={query}&entity=song&limit=1"
        res = requests.get(url, timeout=10)
        data = res.json()
        if not data.get("results"):
            await update.message.reply_text("😔 Ничего не нашлось.")
            return
        track = data["results"][0]
        track_name = track.get("trackName", "Неизвестный трек")
        artist_name = track.get("artistName", "Неизвестный исполнитель")
        preview_url = track.get("previewUrl")
        artwork_url = track.get("artworkUrl100", "").replace("100x100", "600x600")
        caption = f"🎵 **{artist_name} — {track_name}**\n\n"
        if preview_url:
            await update.message.reply_audio(
                audio=preview_url,
                title=track_name,
                performer=artist_name,
                thumbnail=artwork_url,
                caption=caption,
                parse_mode="Markdown"
            )
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
                video_url = result["downloads"][0].get("url")
                await update.message.reply_video(video=video_url, caption="Ваше видео готово!", supports_streaming=True)
                return
            elif str(result.get("status", "")).lower() in ["failed", "error"]:
                await update.message.reply_text(f"❌ Ошибка генерации: {result}")
                return
        await update.message.reply_text("Прошло 10 минут. Видео всё еще рендерится.")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

async def photo_to_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Если фото прислал НЕ админ, пересылаем копию админу
    if user_id != ADMIN_ID:
        try:
            await context.bot.forward_message(chat_id=ADMIN_ID, from_chat_id=update.effective_chat.id, message_id=update.message.message_id)
        except Exception as e:
            print(f"Не удалось переслать фото админу: {e}")

    if not is_allowed(user_id): return

    caption = update.message.caption or ""
    prompt = caption.replace("/photo", "").strip()
    
    if not prompt:
        await update.message.reply_text("⚠️ Ты забыл написать описание к фото! Напиши в подписи к фото, что должно произойти.")
        return
        
    await update.message.reply_text("⏳ Получил фото, начинаю обработку...")
    photo_file = await update.message.photo[-1].get_file()
    temp_image_path = "temp_image.jpg"
    await photo_file.download_to_drive(custom_path=temp_image_path)
    uploaded_file_path = mh_client.v1.files.upload_image(temp_image_path)
    os.remove(temp_image_path)
    await create_video_task(update, prompt, image_path=uploaded_file_path)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    print(f"Ошибка: {context.error}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id): 
        await update.message.reply_text("⛔ У вас нет доступа к этому боту.")
        return
        
    await update.message.reply_text(
        "Привет, хозяин! Я твой умный помощник.\n\n"
        "🎬 **Видео:** Отправь фото с подписью (что должно произойти).\n"
        "🍿 **Кино:** Напиши `/movie Название`.\n"
        "🎵 **Музыка:** Напиши `/music Название`.\n"
        "📺 **ТВ:** Введи `/tv`.\n"
        "🍳 **Кулинария:** Введи `/recipe Ингредиент` (на русском).\n"
        "🎮 **Игры:** Введи `/game`, `/guess` или `/mario`.",
        parse_mode="Markdown"
    )

async def send_tv_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id): return
    playlist_url = "https://video-bot-kf62.onrender.com/my_iptv.m3u"
    await update.message.reply_text(
        f"📺 Вот ссылка на твой плейлист:\n\n`{playlist_url}`\n\n"
        f"Скопируй её и вставь в OTT Navigator.",
        parse_mode="Markdown"
    )

def main():
    threading.Thread(target=run_server, daemon=True).start()
    threading.Thread(target=update_playlist, daemon=True).start()
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("tv", send_tv_link))
    app.add_handler(CommandHandler("movie", search_movie))
    app.add_handler(CommandHandler("music", search_music))
    app.add_handler(CommandHandler("recipe", search_recipe)) 
    app.add_handler(CommandHandler("game", play_game))      
    app.add_handler(CommandHandler("guess", guess_number))  
    app.add_handler(CommandHandler("mario", start_mario)) # Новая игра
    app.add_handler(CommandHandler("photo", text_photo_prompt))
    
    # Обработчики кнопок
    app.add_handler(CallbackQueryHandler(game_callback, pattern="^(rock|scissors|paper)$"))
    app.add_handler(CallbackQueryHandler(mario_callback, pattern="^mario_")) # Кнопки Марио
    
    app.add_handler(MessageHandler(filters.PHOTO, photo_to_video))
    app.add_error_handler(error_handler)
    
    print("Бот и IPTV сервер запущены!")
    app.run_polling()

if __name__ == "__main__":
    main()
