import os
import time
import requests
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import magic_hour

# Бот берет ключи из переменных окружения
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
MAGIC_HOUR_KEY = os.getenv("MAGIC_HOUR_KEY")

MAGIC_HOUR_URL = "https://api.magichour.ai/v1"

# Инициализируем клиент Magic Hour
mh_client = magic_hour.Client(token=MAGIC_HOUR_KEY)

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
        # Если видео слишком большое для Telegram, отправляем ссылку
        await update.message.reply_text(f"⚠️ Видео готово, но не удалось отправить файлом (возможно, слишком большое).\nСсылка для скачивания: {video_url}")

async def create_video_task(update: Update, prompt, image_path=None):
    await update.message.reply_text("🎬 Создаю видео через Magic Hour... Жди (до 10 минут)!")

    headers = {"Authorization": f"Bearer {MAGIC_HOUR_KEY}", "Content-Type": "application/json"}
    
    if image_path:
        payload = {
            "model": "ltx-2.5",
            "assets": {
                "image_file_path": image_path
            },
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
        # Увеличено до 10 минут (60 попыток по 10 секунд)
        for i in range(60): 
            time.sleep(10)
            check = requests.get(f"{MAGIC_HOUR_URL}/projects/{project_id}", headers=headers, timeout=30)
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
            await update.message.reply_text("Прошло 10 минут, видео всё еще рендерится. Зайдите на сайт Magic Hour в раздел Library позже.")

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
            temp_image_path = "temp_image.jpg"
            await photo_file.download_to_drive(custom_path=temp_image_path)
            await update.message.reply_text("✅ Фото скачано. Загружаю в Magic Hour...")
            
            # Загружаем файл напрямую в Magic Hour
            uploaded_file_path = mh_client.v1.files.upload_file(temp_image_path)
            os.remove(temp_image_path)
            
            await update.message.reply_text("✅ Фото загружено в Magic Hour! Запускаю генерацию...")
        else:
            await update.message.reply_text("❌ Это не фото.")
            return
    except Exception as e:
        await update.message.reply_text(f"❌ ОШИБКА ПРИ ЗАГРУЗКЕ: {e}")
        return

    await create_video_task(update, prompt, image_path=uploaded_file_path)

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
