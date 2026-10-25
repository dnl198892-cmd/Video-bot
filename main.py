async def photo_to_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Тест: получил фото...")
    
    prompt = " ".join(context.args)
    if not prompt:
        await update.message.reply_text("⚠️ Нет текста после /photo.")
        return

    try:
        if update.message.photo:
            # Берем самый большой размер фото
            photo_file = await update.message.photo[-1].get_file()
            await update.message.reply_text("✅ Фото найдено, скачиваю из Telegram...")
        else:
            await update.message.reply_text("❌ Это не фото.")
            return

        # Скачиваем фото в память (без запроса ссылки)
        image_bytes = await photo_file.download_as_bytearray()
        await update.message.reply_text(f"✅ Фото скачано ({len(image_bytes)} байт). Отправляю на ImgBB...")
        
        # Загружаем на ImgBB
        image_url = upload_to_imgbb(image_bytes)
        
        if not image_url:
            await update.message.reply_text("❌ ImgBB не принял фото. Проверь ключ ImgBB.")
            return
            
        await update.message.reply_text("✅ Фото на ImgBB! Передаю в Magic Hour...")
        
    except Exception as e:
        await update.message.reply_text(f"❌ ОШИБКА ПРИ СКАЧИВАНИИ: {e}")
        return

    # Запускаем генерацию
    await create_video_task(update, prompt, image_url=image_url)
