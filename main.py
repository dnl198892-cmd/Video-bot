import os
import time
import requests
import threading
import concurrent.futures
import random
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import magic_hour

# --- Ключи ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
MAGIC_HOUR_KEY = os.getenv("MAGIC_HOUR_KEY")
KINOPOISK_KEY = os.getenv("KINOPOISK_KEY")
MAGIC_HOUR_URL = "https://api.magichour.ai/v1"
mh_client = magic_hour.Client(token=MAGIC_HOUR_KEY)

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
                self.send_response(404)
                self.end_headers()
        else:
            self.send_response(501)
            self.end_headers()

def run_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), SimpleHTTPRequestHandler)
    server.serve_forever()

# --- Telegram Бот ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я универсальный бот.\n\n"
        "🎬 **Видео:** Отправь фото с подписью `/photo текст`, и я оживлю его.\n"
        "🍿 **Кино:** Напиши `/movie Название фильма`, чтобы найти информацию.\n"
        "🎵 **Музыка:** Напиши `/music Название песни`, и я пришлю аудио.\n"
        "📺 **ТВ:** Введи `/tv`, чтобы получить ссылку на твой личный плейлист каналов.",
        parse_mode="Markdown"
    )

async def send_tv_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    playlist_url = "https://video-bot-kf62.onrender.com/my_iptv.m3u"
    await update.message.reply_text(
        f"📺 Вот ссылка на твой плейлист:\n\n`{playlist_url}`\n\n"
        f"Скопируй её и вставь в OTT Navigator. Я регулярно обновляю этот файл!",
        parse_mode="Markdown"
    )

async def search_movie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("Напиши название фильма после команды. Пример: /movie Интерстеллар")
        return
    await update.message.reply_text(f"🔎 Ищу фильм «{query}»...")
    try:
        headers = {"X-API-KEY": KINOPOISK_KEY}
        url = f"https://api.poiskkino.dev/v1.4/movie/search?page=1&limit=1&query={query}"
        res = requests.get(url, headers=headers, timeout=15)
        res.raise_for_status()
        data = res.json()
        if not data.get("docs"):
            await update.message.reply_text("😔 Ничего не нашлось. Попробуй другое название.")
            return
        movie = data["docs"][0]
        name = movie.get("name") or movie.get("alternativeName") or "Без названия"
        year = movie.get("year", "—")
        rating = movie.get("rating", {}).get("kp", "—")
        description = movie.get("description", "Описание отсутствует.")
        poster = movie.get("poster", {}).get("url")
        caption = f"🎬 **{name}** ({year})\n⭐ Рейтинг: {rating}\n\n📝 {description}"
        if poster:
            await update.message.reply_photo(photo=poster, caption=caption, parse_mode="Markdown")
        else:
            await update.message.reply_text(caption, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка при поиске: {e}")

# --- Новая функция поиска музыки через Invidious (без yt-dlp) ---
INVIDIOUS_INSTANCES = [
    "https://inv.nadeko.net",
    "https://invidious.nerdvpn.de",
    "https://yewtu.be",
    "https://invidious.f5.si",
    "https://inv.tux.pizza",
    "https://invidious.privacyredirect.com"
]

def download_music(query):
    instances = INVIDIOUS_INSTANCES.copy()
    random.shuffle(instances)
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    for instance in instances:
        try:
            search_url = f"{instance}/api/v1/search?q={query}&type=video"
            print(f"Пробую сервер: {instance}")
            res = requests.get(search_url, headers=headers, timeout=10)
            if res.status_code != 200:
                continue
            
            search_data = res.json()
            if not search_data:
                continue
            
            video_id = search_data[0].get("videoId")
            if not video_id:
                continue

            stream_url = f"{instance}/api/v1/videos/{video_id}"
            stream_res = requests.get(stream_url, headers=headers, timeout=10)
            if stream_res.status_code != 200:
                continue
                
            stream_data = stream_res.json()
            adaptive_formats = stream_data.get("adaptiveFormats", [])
            
            audio_streams = [f for f in adaptive_formats if f.get("type", "").startswith("audio")]
            if not audio_streams:
                continue

            best_audio = max(audio_streams, key=lambda x: int(x.get("bitrate", 0)))
            audio_url = best_audio.get("url")
            
            if audio_url:
                audio_res = requests.get(audio_url, headers=headers, timeout=30)
                with open("music_temp.mp3", "wb") as f:
                    f.write(audio_res.content)
                
                title = search_data[0].get("title", "Неизвестный трек")
                performer = search_data[0].get("author", "Неизвестный исполнитель")
                return title, performer, "music_temp.mp3"

        except Exception as e:
            print(f"Ошибка на сервере {instance}: {e}")
            continue

    return None, None, None

async def search_music(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("Напиши название песни или исполнителя. Пример: /music Imagine Dragons Believer")
        return

    await update.message.reply_text(f"🎵 Ищу песню «{query}»... Это может занять 10-20 секунд.")

    try:
        title, performer, file_path = download_music(query)
        
        if not file_path or not os.path.exists(file_path):
            await update.message.reply_text("😔 Не удалось найти или скачать эту песню. Попробуй другое название.")
            return

        await update.message.reply_text("📤 Отправляю аудио...")
        
        with open(file_path, "rb") as audio_file:
            await update.message.reply_audio(
                audio=audio_file,
                title=title,
                performer=performer,
                caption=f"🎵 {title} — {performer}"
            )
        
        os.remove(file_path)

    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка при поиске музыки: {e}")
        if os.path.exists("music_temp.mp3"):
            os.remove("music_temp.mp3")

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
            time.sleep(10)
            check = requests.get(f"{MAGIC_HOUR_URL}/projects/{project_id}", headers=headers, timeout=30)
            result = check.json()
            if str(result.get("status", "")).lower() in ["complete", "completed", "succeeded"]:
                video_url = result["downloads"][0].get("url")
                await update.message.reply_video(video=video_url, caption="Ваше видео готово!")
                return
            elif str(result.get("status", "")).lower() in ["failed", "error"]:
                await update.message.reply_text(f"❌ Ошибка генерации: {result}")
                return
        await update.message.reply_text("Прошло 10 минут. Видео всё еще рендерится.")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

async def photo_to_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Получил фото...")
    caption = update.message.caption or ""
    prompt = caption.replace("/photo", "").strip()
    if not prompt: return
    photo_file = await update.message.photo[-1].get_file()
    temp_image_path = "temp_image.jpg"
    await photo_file.download_to_drive(custom_path=temp_image_path)
    uploaded_file_path = mh_client.v1.files.upload_file(temp_image_path)
    os.remove(temp_image_path)
    await create_video_task(update, prompt, image_path=uploaded_file_path)

def main():
    threading.Thread(target=run_server, daemon=True).start()
    threading.Thread(target=update_playlist, daemon=True).start()
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("tv", send_tv_link))
    app.add_handler(CommandHandler("movie", search_movie))
    app.add_handler(CommandHandler("music", search_music))
    app.add_handler(MessageHandler(filters.PHOTO, photo_to_video))
    
    print("Бот и IPTV сервер запущены!")
    app.run_polling()

if __name__ == "__main__":
    main()
