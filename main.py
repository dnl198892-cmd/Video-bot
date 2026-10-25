import os
import time
import requests
import threading
import concurrent.futures
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import magic_hour

# --- Ключи ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
MAGIC_HOUR_KEY = os.getenv("MAGIC_HOUR_KEY")
MAGIC_HOUR_URL = "https://api.magichour.ai/v1"
mh_client = magic_hour.Client(token=MAGIC_HOUR_KEY)

# --- Ссылки на IPTV плейлисты ---
IPTV_URLS = [
    "https://iptv-org.github.io/iptv/languages/rus.m3u",
    "https://iptv-org.github.io/iptv/categories/movies.m3u",
    "https://iptv-org.github.io/iptv/categories/sports.m3u"
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
                        channels.append((current_name, line.strip()))
        except Exception as e:
            pass

    print(f"Всего каналов до проверки: {len(channels)}. Проверяю (займет пару минут)...")
    working_channels = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        future_to_channel = {executor.submit(check_channel, ch[1]): ch for ch in channels}
        for future in concurrent.futures.as_completed(future_to_channel):
            ch = future_to_channel[future]
            if future.result():
                working_channels.append(ch)

    print(f"Рабочих каналов: {len(working_channels)}. Сохраняю файл...")
    with open("my_iptv.m3u", "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for name, url in working_channels:
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

# --- Логика Telegram Бота ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я универсальный бот.\n\n"
        "🎬 **Создание видео:** Отправь фото с подписью `/photo текст`, и я оживлю его.\n\n"
        "📺 **Телевидение:** Введи команду /tv, чтобы получить ссылку на твой личный (и уже отфильтрованный!) плейлист."
    )

async def send_tv_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ВАЖНО: Замените адрес на свой актуальный адрес Render
    playlist_url = "https://video-bot-kf62.onrender.com/my_iptv.m3u"
    
    await update.message.reply_text(
        f"📺 Вот ссылка на твой плейлист:\n\n"
        f"`{playlist_url}`\n\n"
        f"Скопируй её и вставь в OTT Navigator. Я регулярно обновляю этот файл, оставляя только рабочие каналы!",
        parse_mode="Markdown"
    )

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
    
    # Добавляем команды
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("tv", send_tv_link)) # <--- НОВАЯ КОМАНДА!
    app.add_handler(MessageHandler(filters.PHOTO, photo_to_video))
    
    print("Бот и IPTV сервер запущены!")
    app.run_polling()

if __name__ == "__main__":
    main()
