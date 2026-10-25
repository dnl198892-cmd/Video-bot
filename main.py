import os
import time
import requests
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Бот берет ключи из переменных окружения сервера
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
MAGIC_HOUR_KEY = os.getenv("MAGIC_HOUR_KEY")
IMGBB_KEY = os.getenv("IMGBB_KEY")

MAGIC_HOUR_URL = "https://api.magichour.ai/v1"

# --- Фейковый веб-сервер для Render ---
def run_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), BaseHTTPRequestHandler)
    server.serve_forever()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я создаю видео и отправляю его прямо сюда.\n\n"
        "🎬 /video текст — видео из текста\n"
        "🖼️ Отправь фото с подписью /photo текст — оживить фото"
    )

def upload_to_imgbb(image_bytes):
    url = "https://api.imgbb.com/1/upload"
    payload = {"key": IMGBB_KEY}
    files = {"image": image_bytes}
    # Маскируемся под браузер, чтобы ImgBB не блокировал сервер
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        response = requests.post(url, data=payload, files=files, headers=headers, timeout=30)
        data = response.json()
        if data.get("success"):
            return data["data"]["url"]
        else:
            print(f"Ошибка ImgBB: {data}")
            return None
    except Exception as e:
        print(f"Ошибка ImgBB: {e}")
        return None

async def send_video_to_user(update: Update, video_url):
    await update.message.reply_text("📥 Скачиваю видео, чтобы отправить вам в Telegram...")
    try:
        video_data = requests.get(video_url, timeout=60).content
        temp_file = "temp_video.mp4"
        with open(temp_file, "wb") as f:
            f.write(video_data)
        
        with open(temp_file, "rb") as f:
            await update.message.reply_video(video=f, caption="Ваше видео готово! 🎉")
        
        os.remove(temp_file)
    except Exception as e:
        await update.message.reply_text(f"❌ Не удалось отправить видео: {e}\nСсылка: {video_url}")

async def create_video_task(update: Update, prompt, image_url=None):
    await update.message.reply_text("🎬 Создаю видео через Magic Hour... Жди (до 5 минут)!")

    headers = {"Authorization": f"Bearer {MAGIC_HOUR_KEY}", "Content-Type": "application/json"}
    
    if image_url:
        payload = {
            "model": "ltx-2.5",
            "image_url": image_url,
            "end_seconds": 5,
            "resolution": "480p",
            "style": {"prompt": prompt}
        }
        endpoint = f"{MAGIC_HOUR_URL}/image-to-video"
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
        res = requests.post(endpoint, headers=headers, json=payload, timeout=30)
        
        if res.status_code != 200:
            await update.message.reply_text(f"❌ Ошибка Magic Hour: {res.status_code}\n{res.text}")
            return

        data = res.json()
        project_id = data.get("project_id") or data.get("id")
        
        if not project_id:
            await update.message.reply_text(f"Ошибка: сервер не выдал ID. Ответ: {data}")
            return

        final_url = None
        for i in range(30): 
            time.sleep(10)
            check = requests.get(
                f"{MAGIC_HOUR_URL}/projects/{project_id}",
                headers=headers,
                timeout=30
            )
            if check.status_code != 200:
                continue
                
            result = check.json()
            status = str(result.get("status", "")).lower()
            
            if status in ["complete", "completed", "succeeded"]:
                downloads = result.get("downloads")
                if downloads and isinstance(downloads, list) and len(downloads) > 0:
                    final_url = downloads[0].get("url")
                break
            elif status in ["failed", "error"]:
                await update.message.reply_text(f"❌ Ошибка генерации: {result}")
                return

        if final_url:
            await send_video_to_user(update, final_url)
        else:
            await update.message.reply_text("Превышено время ожидания (5 минут). Сервер все еще рендерит видео.")

    except Exception as e:
        await update.message.reply_text(f"Критическая ошибка: {e}")

async def text_to_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = " ".join(context.args)
    if not prompt:
        await update.message.reply_text("Напиши текст после команды. Пример: /video кот танцует")
        return
    await create_video_task(update, prompt)

async def photo_to_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Тест: получил фото...")
    
    caption = update.message.caption or ""
    prompt = caption.replace("/photo", "").strip()
    
    if not prompt:
        await update.message.reply_text("⚠️ Напиши текст после /photo в подписи к фото.")
        return

    try:
        if update.message.photo:
            photo_file = await update.message.photo[-1].get_file()
            file_url = photo_file.file_path
            await update.message.reply_text("✅ Ссылка получена. Пробую скачать...")
        else:
            await update.message.reply_text("❌ Это не фото.")
            return

        try:
            response = requests.get(file_url, timeout=20)
            response.raise_for_status()
            image_bytes = response.content
            await update.message.reply_text(f"✅ Фото скачано ({len(image_bytes)} байт). Отправляю в ImgBB...")
        except Exception as download_err:
            await update.message.reply_text(f"❌ Ошибка скачивания: {download_err}")
            return
            
        image_url = upload_to_imgbb(image_bytes)
        
        if not image_url:
            await update.message.reply_text("❌ ImgBB не принял фото (проверь ключ).")
            return
            
        await update.message.reply_text("✅ Фото на ImgBB! Запускаю Magic Hour...")
        
    except Exception as e:
        await update.message.reply_text(f"❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")
        return

    await create_video_task(update, prompt, image_url=image_url)

async def text_photo_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Чтобы оживить фото, прикрепи его к сообщению и в подписи напиши /photo и текст.")

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("video", text_to_video))
    app.add_handler(MessageHandler(filters.PHOTO, photo_to_video))
    app.add_handler(CommandHandler("photo", text_photo_prompt))
    
    async def fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("Используй команды /video (текст) или отправь фото с подписью /photo.")
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback))

    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        print(f"Ошибка: {context.error}")
        if isinstance(update, Update) and update.effective_message:
            await update.effective_message.reply_text(f"⚠️ Ошибка: {context.error}")
    
    app.add_error_handler(error_handler)

    print("Бот на Magic Hour запущен!")
    app.run_polling()

if __name__ == "__main__":
    threading.Thread(target=run_dummy_server, daemon=True).start()
    main()
