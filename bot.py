import os
import random
import sqlite3
import logging
import asyncio
import traceback
import threading
from flask import Flask

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# Flask sunucusunu arka planda başlat (Render port hatasını önlemek için)
threading.Thread(target=run_flask, daemon=True).start()

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
from google import genai
from PIL import Image

# .env içerisindeki şifreleri yükle
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# ===========================================================================
# ⚙️ YÖNETİCİ / İŞLETME AYARLARI
# ===========================================================================
YONETICI_ID = 123456789             # @userinfobot'tan aldığın ID numaran
YONETICI_KULLANICI_ADI = "ahmetkaratr"  # Yönlendirilecek Telegram kullanıcı adın

# Resmi Gemini istemcisi
gemini_client = genai.Client(api_key=GEMINI_API_KEY)

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# Veritabanını ve eksik sütunları otomatik hazırla
def init_db():
    conn = sqlite3.connect("tarot_vadisi.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS kullanicilar (
            telegram_id INTEGER PRIMARY KEY,
            durum TEXT DEFAULT 'yok',
            paket TEXT,
            niyet TEXT,
            burc TEXT
        )
    """)
    # Eksik sütunları güvenle ekle
    for col in ["paket TEXT", "niyet TEXT", "burc TEXT"]:
        try:
            cursor.execute(f"ALTER TABLE kullanicilar ADD COLUMN {col}")
        except sqlite3.OperationalError:
            pass
    conn.commit()
    conn.close()

init_db()

TAROT_CARDS = ["Deli", "Büyücü", "Azize", "İmparatoriçe", "İmparator", "Aziz", "Aşıklar", "Ölüm", "Kule", "Yıldız", "Güneş", "Dünya"]
BURCLAR = ["Koç ♈", "Boğa ♉", "İkizler ♊", "Yengeç ♋", "Aslan ♌", "Başak ♍", "Terazi ♎", "Akrep ♏", "Yay ♐", "Oğlak ♑", "Kova ♒", "Balık ♓"]

# Asenkron Gemini istek fonksiyonu
async def gemini_istek_gonder_sdk(contents, model='gemini-2.5-flash'):
    loop = asyncio.get_running_loop()
    def call_gemini():
        return gemini_client.models.generate_content(
            model=model,
            contents=contents
        )
    response = await loop.run_in_executor(None, call_gemini)
    return response.text

# /start ekranı (VIP Animatik Deneyim)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = sqlite3.connect("tarot_vadisi.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO kullanicilar (telegram_id, durum) VALUES (?, 'yok')", (user.id,))
    cursor.execute("UPDATE kullanicilar SET durum = 'yok', paket = NULL, niyet = NULL WHERE telegram_id = ?", (user.id,))
    conn.commit()
    conn.close()

    mesaj = (
        f"✨ *Hoş Geldin, {user.first_name}!* ✨\n\n"
        "🔮 *Tarot Vadisi Ruhsal Rehberlik ve Kehanet Alanına Adım Attın.*\n\n"
        "Aşağıdaki interaktif menüden dilediğin bakımı seçebilir, kişisel enerjini keşfedebilirsin:\n\n"
        "💫 *Sana Nasıl Rehberlik Etmemi İstersin?*"
    )
    keyboard = [
        [InlineKeyboardButton("☕ Kahve Falı Bakımı (AI)", callback_data="kahve_fali"), InlineKeyboardButton("✋ El Falı Analizi (AI)", callback_data="el_fali")],
        [InlineKeyboardButton("🟢 Evet / Hayır Tarotu", callback_data="evet_hayir"), InlineKeyboardButton("🌟 Günlük Burç & Aura Yorumu", callback_data="burc_secim")],
        [InlineKeyboardButton("💎 VIP Detaylı Özel Açılım", callback_data="paket_detayli")],
        [InlineKeyboardButton("🔮 Birebir Canlı Seans / Özel Bakım", callback_data="canli_bakim")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.message:
        await update.message.reply_text(mesaj, reply_markup=reply_markup, parse_mode="Markdown")
    elif update.callback_query:
        await update.callback_query.message.reply_text(mesaj, reply_markup=reply_markup, parse_mode="Markdown")

# Menü Tıklamaları ve İnteraktif Akış
async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data
    
    conn = sqlite3.connect("tarot_vadisi.db")
    cursor = conn.cursor()
    
    if data == "main_menu":
        cursor.execute("UPDATE kullanicilar SET durum = 'yok' WHERE telegram_id = ?", (user_id,))
        conn.commit()
        conn.close()
        await start(update, context)
        return

    # --- 1. GÜNLÜK BURÇ SEÇİM MENÜSÜ ---
    elif data == "burc_secim":
        keyboard = []
        row = []
        for index, b in enumerate(BURCLAR):
            row.append(InlineKeyboardButton(b, callback_data=f"burcyorum_{b}"))
            if len(row) == 3:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        keyboard.append([InlineKeyboardButton("🏠 Ana Menüye Dön", callback_data="main_menu")])
        
        await query.edit_message_text("🌟 *Lütfen Burcunuzu Seçin:*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data.startswith("burcyorum_"):
        secilen_burc = data.split("_")[1]
        await query.edit_message_text(f"✨ *{secilen_burc} burcu için günün enerjisi ve aura haritası çıkarılıyor...* 🔮", parse_mode="Markdown")
        
        prompt = f"Sen Tarot Vadisi'nin usta astrologusun. {secilen_burc} burcu için bugün geçerli olacak 3 cümlelik gizemli, etkileyici ve motivasyon dolu bir aura yorumu yaz."
        try:
            yorum = await gemini_istek_gonder_sdk(prompt)
            keyboard = [[InlineKeyboardButton("🏠 Ana Menüye Dön", callback_data="main_menu")]]
            await query.message.reply_text(
                f"🌟 *{secilen_burc} - Günün Aura Yorumu:*\n\n{yorum}\n\n✨ *Günün Şanslı Rengi:* {random.choice(['Safir Mavisi', 'Zümrüt Yeşili', 'Kehribar', 'Gümüş', 'Mistik Mor'])}\n🔢 *Şanslı Sayın:* {random.randint(1, 99)}",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
        except Exception as e:
            await query.message.reply_text("🔮 Burç enerjileri şu an çok yoğun, lütfen az sonra tekrar deneyin.")

    # --- 2. EVET / HAYIR TAROTU ---
    elif data == "evet_hayir":
        cursor.execute("UPDATE kullanicilar SET durum = 'yok' WHERE telegram_id = ?", (user_id,))
        conn.commit()
        conn.close()
        
        await query.edit_message_text("🔮 *Zihninizi boşaltın, sorunuza odaklanın... Sizin için 1 kart çekiliyor...* 🔮", parse_mode="Markdown")
        kart = random.choice(TAROT_CARDS)
        prompt = f"Sen Tarot Vadisi'nin gizemli yorumcususun. Kullanıcı bir soru sordu ve {kart} kartını seçti. Sorusuna çok kısa, uzatmadan net bir EVET veya HAYIR cevabı ver ve mistik bir cümleyle bitir. En fazla 3 cümle olsun."
        try:
            cevap_metni = await gemini_istek_gonder_sdk(prompt)
            keyboard = [
                [InlineKeyboardButton("💎 Detaylı Birebir Seans Al", url=f"https://t.me/{YONETICI_KULLANICI_ADI}")],
                [InlineKeyboardButton("🏠 Ana Menüye Dön", callback_data="main_menu")]
            ]
            await query.message.reply_text(
                f"🃏 *Seçilen Kart:* {kart}\n\n✨ *Yorum:* {cevap_metni}",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            traceback.print_exc()
            await query.message.reply_text("🔮 Yoğun mistik enerjiler nedeniyle şu an hat kapandı, lütfen birkaç saniye sonra tekrar deneyin.")

    # --- 3. NİYET SEÇİM AŞAMASI (FAL ÖNCESİ) ---
    elif data in ["kahve_fali", "el_fali"]:
        cursor.execute("UPDATE kullanicilar SET durum = ? WHERE telegram_id = ?", (f"niyet_bekliyor_{data}", user_id))
        conn.commit()
        conn.close()
        
        keyboard = [
            [InlineKeyboardButton("❤️ Aşk & İlişkiler", callback_data=f"niyetsec_Aşk_{data}")],
            [InlineKeyboardButton("💼 Kariyer & Para", callback_data=f"niyetsec_Kariyer_{data}")],
            [InlineKeyboardButton("✨ Genel Gelecek & Aura", callback_data=f"niyetsec_Genel_{data}")]
        ]
        await query.edit_message_text(
            "🔮 *Bakıma başlamadan önce niyetini belirleyelim...*\n\n"
            "Odaklanmak istediğin özel bir konu var mı?",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

    elif data.startswith("niyetsec_"):
        _, niyet_konusu, fal_turu = data.split("_")
        cursor.execute("UPDATE kullanicilar SET durum = ?, niyet = ? WHERE telegram_id = ?", (fal_turu, niyet_konusu, user_id))
        conn.commit()
        conn.close()
        
        tip = "Türk kahvesi fincanı/telve" if fal_turu == "kahve_fali" else "sağ el avuç içi"
        await query.edit_message_text(
            f"🎯 *Niyetin Alındı:* {niyet_konusu}\n\n"
            f"📸 Şimdi lütfen bota net bir *{tip}* fotoğrafı gönderin.",
            parse_mode="Markdown"
        )

    # --- 4. VIP SEANS FORMU ---
    elif data in ["paket_detayli", "canli_bakim"]:
        paket_adi = "VIP Detaylı Açılım" if data == "paket_detayli" else "Birebir Canlı Seans"
        cursor.execute("UPDATE kullanicilar SET durum = 'form_bekliyor', paket = ? WHERE telegram_id = ?", (paket_adi, user_id))
        conn.commit()
        conn.close()
        
        await query.edit_message_text(
            f"👑 *{paket_adi} Randevu Talebi*\n\n"
            "Özel analizinizi hazırlayabilmemiz için lütfen aşağıdaki bilgileri **tek bir mesajda yazıp yollayın**:\n\n"
            "1️⃣ İsim & Soyisim\n"
            "2️⃣ Doğum Tarihi & Burç\n"
            "3️⃣ Odaklanmak İstediğiniz Konu / Soru",
            parse_mode="Markdown"
        )

# Fotoğraf ve Form İşleme
async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_name = update.message.from_user.username or update.message.from_user.first_name or "Bilinmeyen"
    
    conn = sqlite3.connect("tarot_vadisi.db")
    cursor = conn.cursor()
    cursor.execute("SELECT durum, paket, niyet FROM kullanicilar WHERE telegram_id = ?", (user_id,))
    row = cursor.fetchone()
    
    durum = row[0] if row else 'yok'
    paket = row[1] if row and len(row) > 1 else None
    niyet = row[2] if row and len(row) > 2 else "Genel"

    # --- FORM YANITLARI (VIP SEANS İÇİN) ---
    if durum == "form_bekliyor" and update.message.text:
        kullanici_bilgisi = update.message.text
        cursor.execute("UPDATE kullanicilar SET durum = 'yok' WHERE telegram_id = ?", (user_id,))
        conn.commit()
        conn.close()
        
        keyboard = [[InlineKeyboardButton("💬 Doğrudan Uzmanımıza Yazın", url=f"https://t.me/{YONETICI_KULLANICI_ADI}")]]
        await update.message.reply_text(
            "✅ *Bilgileriniz başarıyla alındı!*\n\n"
            "Seans saatinizi netleştirmek ve detayları görüşmek için doğrudan baş falcımıza yazabilirsiniz:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        
        try:
            await context.bot.send_message(
                chat_id=YONETICI_ID,
                text=f"🚨 *YENİ VIP SEANS TALEBİ!*\n\n👤 Kullanıcı: @{user_name}\n🆔 ID: `{user_id}`\n📦 Paket: {paket}\n\n📝 *Kullanıcı Bilgileri:*\n{kullanici_bilgisi}",
                parse_mode="Markdown"
            )
        except Exception as e:
            print(f"Yöneticiye form bildirimi atılamadı: {e}")
        return

    # --- FOTOĞRAFLI FAL İŞLEME ---
    if durum in ["kahve_fali", "el_fali"]:
        await update.message.reply_text(
            f"🔮 *Fotoğrafınız alındı! Enerji akışı ({niyet} odağında) inceleniyor...*\n\n"
            f"⏳ Yoğunluğa bağlı olarak bu işlem *1-2 dakika* sürebilir. Lütfen bekleyin, falınız hazır olduğunda buradan iletilecektir.",
            parse_mode="Markdown"
        )
        
        try:
            if update.message.photo:
                photo_file = await update.message.photo[-1].get_file()
            elif update.message.document:
                photo_file = await update.message.document.get_file()
            else:
                conn.close()
                return

            os.makedirs("downloads", exist_ok=True)
            img_path = f"downloads/{user_id}.jpg"
            await photo_file.download_to_drive(img_path)
            
            prompt = f"Sen Tarot Vadisi'nin usta ve net konuşan falcısısın. Kullanıcı özellikle {niyet} konusunu merak ediyor. Çok fazla uzatmadan, en fazla 3-4 cümleyle nokta atışı yorum yap. "
            if durum == "kahve_fali":
                prompt += "Sana gönderilen Türk kahvesi telvesi fotoğrafını eğlenceli ve mistik şekilde Türkçe yorumla."
            else:
                prompt += "Sana gönderilen el avuç içi çizgilerini olumlu ve mistik şekilde Türkçe yorumla."
            
            img = Image.open(img_path)
            
            async def ara_mesaj_gonder():
                await asyncio.sleep(20)
                await update.message.reply_text("✨ *Falınız hazırlanıyor, az sonra geliyor...* 🔮", parse_mode="Markdown")

            ara_gorev = asyncio.create_task(ara_mesaj_gonder())
            
            cevap_metni = await gemini_istek_gonder_sdk([prompt, img])
            
            ara_gorev.cancel()
            
            sans_rengi = random.choice(["Lapis Lazuli Mavi", "Zümrüt Yeşili", "Yakut Kırmızı", "Gümüş Gri"])
            sans_sayisi = random.randint(1, 99)
            dogal_tas = random.choice(["Ametist", "Sitrin", "Kuvars", "Kaplan Gözü"])
            
            ek_bilgi = f"\n\n💫 *Günün Şans Sembolleri:*\n🎨 *Enerji Rengin:* {sans_rengi}\n🔢 *Şanslı Sayın:* {sans_sayisi}\n💎 *Uğurlu Taşın:* {dogal_tas}"
            
            keyboard = [
                [InlineKeyboardButton("💎 Detaylı Özel Fal Al (Birebir Seans)", url=f"https://t.me/{YONETICI_KULLANICI_ADI}")],
                [InlineKeyboardButton("🏠 Ana Menüye Dön", callback_data="main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"✨ *Falınız Hazır ({niyet} Odağında):*\n\n{cevap_metni}{ek_bilgi}",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
            
            cursor.execute("UPDATE kullanicilar SET durum = 'yok', paket = NULL, niyet = NULL WHERE telegram_id = ?", (user_id,))
            conn.commit()
        except Exception as e:
            traceback.print_exc()
            await update.message.reply_text("🔮 Yoğunluk nedeniyle fotoğrafınız incelenemedi, lütfen birkaç saniye sonra tekrar deneyin.")

    conn.close()

# Yönetici komutları
async def onay_ver(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != YONETICI_ID:
        return
    await update.message.reply_text("✅ Komut işlendi.")

def main():
    if not TELEGRAM_TOKEN or not GEMINI_API_KEY:
        print("HATA: Token eksik!")
        return

    application = Application.builder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("onay", onay_ver))
    application.add_handler(CallbackQueryHandler(button_click))
    
    # Fotoğraflar ve belgeler için
    application.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_media))
    
    # Kullanıcı "merhaba", "selam" vb. düz bir metin yazdığında doğrudan /start menüsünü açması için:
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, start))

    print("🔮 Tarot Vadisi Animatik & VIP sürümüyle çalışmaya başladı...")
    application.run_polling()

if __name__ == "__main__":
    main()
