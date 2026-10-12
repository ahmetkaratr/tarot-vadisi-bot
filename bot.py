import os
import random
import sqlite3
import logging
import asyncio
import traceback
import threading
from datetime import datetime
from flask import Flask

# Flask Ayarları (Render'ın Botu Kapatmaması İçin)
app = Flask(__name__)

@app.route('/')
def home():
    return "🔮 Tarot Vadisi Asenkron Bot Aktif ve Hızlı!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    # Flask asenkron döngüyü bozmamak için threaded=True olmalı
    app.run(host='0.0.0.0', port=port, threaded=True)

# Kütüphaneleri Yükle
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, constants
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
from google import genai
from PIL import Image

# .env içerisindeki şifreleri yükle
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# ===========================================================================
# ⚙️ YÖNETİCİ / İŞLETME AYARLARI & LİMİTLER
# ===========================================================================
YONETICI_ID = 123456789             # Telegram ID'niz (Öğrenmek için bota /id yazabilirsiniz)
YONETICI_KULLANICI_ADI = "ahmetkaratr"  # Telegram kullanıcı adınız
GUNLUK_LIMIT = 2                   # Kullanıcı başına günlük ücretsiz fal hakkı

# Gemini İstemcisi
gemini_client = genai.Client(api_key=GEMINI_API_KEY)

# Logging Ayarları
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Veritabanı kurulumu ve sütun kontrolleri
def init_db():
    conn = sqlite3.connect("tarot_vadisi.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS kullanicilar (
            telegram_id INTEGER PRIMARY KEY,
            durum TEXT DEFAULT 'yok',
            paket TEXT,
            niyet TEXT,
            burc TEXT,
            kullanilan_hak INTEGER DEFAULT 0,
            son_tarih TEXT
        )
    """)
    for col in ["paket TEXT", "niyet TEXT", "burc TEXT", "kullanilan_hak INTEGER DEFAULT 0", "son_tarih TEXT"]:
        try:
            cursor.execute(f"ALTER TABLE kullanicilar ADD COLUMN {col}")
        except sqlite3.OperationalError:
            pass # Sütun zaten varsa hata verme
    conn.commit()
    conn.close()

init_db()

TAROT_CARDS = ["Deli", "Büyücü", "Azize", "İmparatoriçe", "İmparator", "Aziz", "Aşıklar", "Ölüm", "Kule", "Yıldız", "Güneş", "Dünya"]
BURCLAR = ["Koç ♈", "Boğa ♉", "İkizler ♊", "Yengeç ♋", "Aslan ♌", "Başak ♍", "Terazi ♎", "Akrep ♏", "Yay ♐", "Oğlak ♑", "Kova ♒", "Balık ♓"]

# Günlük hak takibi ve düşme fonksiyonu
def hak_kontrol_ve_duser(user_id):
    today = datetime.now().strftime("%Y-%m-%d")
    conn = sqlite3.connect("tarot_vadisi.db")
    cursor = conn.cursor()
    cursor.execute("SELECT kullanilan_hak, son_tarih FROM kullanicilar WHERE telegram_id = ?", (user_id,))
    row = cursor.fetchone()
    
    if not row:
        cursor.execute("INSERT INTO kullanicilar (telegram_id, kullanilan_hak, son_tarih) VALUES (?, 1, ?)", (user_id, today))
        conn.commit()
        conn.close()
        return True, 1
    
    kullanilan_hak, son_tarih = row[0] or 0, row[1]
    
    if son_tarih != today:
        cursor.execute("UPDATE kullanicilar SET kullanilan_hak = 1, son_tarih = ? WHERE telegram_id = ?", (today, user_id))
        conn.commit()
        conn.close()
        return True, 1
    else:
        if kullanilan_hak >= GUNLUK_LIMIT:
            conn.close()
            return False, kullanilan_hak
        else:
            cursor.execute("UPDATE kullanicilar SET kullanilan_hak = kullanilan_hak + 1 WHERE telegram_id = ?", (user_id,))
            conn.commit()
            conn.close()
            return True, kullanilan_hak + 1

# ===========================================================================
# 🚀 MÜTHİŞ GÜNCELLEME: TAM ASENKRON GEMINI İSTEK FONKSİYONU
# ===========================================================================
# Bu fonksiyon botu kilitlemez, arka planda çalışır.
async def gemini_istek_gonder_async(contents, model='gemini-3.8-flash'):
    # Senkron API çağrısını asenkron bir thread'e taşıyoruz
    def sync_call():
        try:
            # Burası senkron kütüphane çağrısı
            response = gemini_client.models.generate_content(
                model=model,
                contents=contents
            )
            return response.text
        except Exception as e:
            logger.error(f"Gemini API senkron çağrı hatası: {e}")
            raise e

    # asyncio.to_thread, kütüphaneyi kilitlemeden arka planda çalıştırır (Python 3.9+)
    # Eğer Render Python sürümü eskiyse run_in_executor kullanılabilir.
    return await asyncio.to_thread(sync_call)

# /start ekranı
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
        f"🎁 *Günlük Ücretsiz Bakım Hakkınız:* {GUNLUK_LIMIT} Adet\n\n"
        "Aşağıdaki menüden dilediğin bakımı seçebilir, enerjini keşfedebilirsin:"
    )
    keyboard = [
        [InlineKeyboardButton("☕ Kahve Falı (AI)", callback_data="kahve_fali"), InlineKeyboardButton("✋ El Falı (AI)", callback_data="el_fali")],
        [InlineKeyboardButton("🟢 Evet / Hayır Tarotu", callback_data="evet_hayir"), InlineKeyboardButton("🌟 Günlük Burç & Aura", callback_data="burc_secim")],
        [InlineKeyboardButton("💎 VIP Detaylı Özel Açılım", callback_data="paket_detayli"), InlineKeyboardButton("🔮 Birebir Canlı Seans", callback_data="canli_bakim")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.message:
        await update.message.reply_text(mesaj, reply_markup=reply_markup, parse_mode=constants.ParseMode.MARKDOWN)
    elif update.callback_query:
        await update.callback_query.message.reply_text(mesaj, reply_markup=reply_markup, parse_mode=constants.ParseMode.MARKDOWN)

# Kullanıcı ID Öğrenme Komutu
async def id_ogren(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    await update.message.reply_text(f"🆔 Telegram ID'niz: `{user_id}`", parse_mode=constants.ParseMode.MARKDOWN)

# 📢 YÖNETİCİ TOPLU DUYURU KOMUTU
async def duyuru_gonder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    
    if user_id != YONETICI_ID:
        await update.message.reply_text("⚠️ Bu komut sadece yetkili yönetici tarafından kullanılabilir.")
        return

    if not context.args:
        await update.message.reply_text(
            "⚠️ *Duyuru Metni Eksik!*\n\nKullanım:\n`/duyuru Mesajınızı buraya yazın...`",
            parse_mode=constants.ParseMode.MARKDOWN
        )
        return

    duyuru_metni = " ".join(context.args)
    
    conn = sqlite3.connect("tarot_vadisi.db")
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT telegram_id FROM kullanicilar")
    kullanicilar = cursor.fetchall()
    conn.close()

    basarili = 0
    basarisiz = 0

    status_msg = await update.message.reply_text(f"🚀 Duyuru {len(kullanicilar)} kayıtlı kullanıcıya gönderiliyor...")

    for (k_id,) in kullanicilar:
        try:
            await context.bot.send_message(chat_id=k_id, text=duyuru_metni, parse_mode=constants.ParseMode.MARKDOWN)
            basarili += 1
            await asyncio.sleep(0.05) # Flood kontrol
        except Exception:
            basarisiz += 1

    await context.bot.edit_message_text(
        chat_id=update.effective_chat.id,
        message_id=status_msg.message_id,
        text=(f"✅ *Duyuru İşlemi Tamamlandı!*\n\n🟢 Başarılı İletilen: {basarili}\n🔴 Başarısız / Engelleyen: {basarisiz}"),
        parse_mode=constants.ParseMode.MARKDOWN
    )

# 🎁 YÖNETİCİ HAK VERME KOMUTU (/hakver <user_id> <ek_hak>)
async def hak_ver(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    
    if user_id != YONETICI_ID:
        await update.message.reply_text("⚠️ Bu komutu sadece yönetici kullanabilir.")
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "⚠️ *Eksik Parametre!*\n\nKullanım Şekli:\n`/hakver <kullanici_id> <verilecek_hak_sayisi>`",
            parse_mode=constants.ParseMode.MARKDOWN
        )
        return

    try:
        hedef_id = int(context.args[0])
        ek_hak = int(context.args[1])
    except ValueError:
        await update.message.reply_text("⚠️ Kullanıcı ID ve hak sayısı sayı olmalıdır!")
        return

    conn = sqlite3.connect("tarot_vadisi.db")
    cursor = conn.cursor()
    cursor.execute("SELECT kullanilan_hak FROM kullanicilar WHERE telegram_id = ?", (hedef_id,))
    row = cursor.fetchone()
    
    if not row:
        cursor.execute("INSERT INTO kullanicilar (telegram_id, kullanilan_hak, son_tarih) VALUES (?, ?, ?)", 
                       (hedef_id, max(0, GUNLUK_LIMIT - ek_hak), datetime.now().strftime("%Y-%m-%d")))
    else:
        mevcut_kullanilan = row[0] or 0
        yeni_kullanilan = max(0, mevcut_kullanilan - ek_hak)
        cursor.execute("UPDATE kullanicilar SET kullanilan_hak = ? WHERE telegram_id = ?", (yeni_kullanilan, hedef_id))
        
    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"✅ *Başarıyla Hak Tanındı!*\n\n👤 Hedef ID: `{hedef_id}`\n🎁 Eklenen Hak: *+{ek_hak}*",
        parse_mode=constants.ParseMode.MARKDOWN
    )
    
    try:
        await context.bot.send_message(
            chat_id=hedef_id,
            text=f"🎁 *Müjde!* Yönetici tarafından hesabınıza *+{ek_hak} adet* ekstra fal hakkı tanımlandı!",
            parse_mode=constants.ParseMode.MARKDOWN
        )
    except Exception: pass

# Menü Tıklamaları ve İnteraktif Akış
async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data
    
    conn = sqlite3.connect("tarot_vadisi.db")
    cursor = conn.cursor()
    
    if data == "main_menu":
        cursor.execute("UPDATE kullanicilar SET durum = 'yok', niyet = NULL, paket = NULL WHERE telegram_id = ?", (user_id,))
        conn.commit()
        conn.close()
        await start(update, context)
        return

    # 1. NİYET TIKLAMA İŞLEYİCİSİ
    elif data.startswith("niyetsec_"):
        parts = data.split("_")
        niyet_konusu = parts[1]
        fal_turu = "_".join(parts[2:]) 
        
        cursor.execute("UPDATE kullanicilar SET durum = ?, niyet = ? WHERE telegram_id = ?", (fal_turu, niyet_konusu, user_id))
        conn.commit()
        conn.close()
        
        tip = "Türk kahvesi fincanı" if fal_turu == "kahve_fali" else "sağ el avuç içi"
        keyboard = [
            [InlineKeyboardButton("🔙 Niyet Değiştir", callback_data=fal_turu)],
            [InlineKeyboardButton("🏠 Ana Menüye Dön", callback_data="main_menu")]
        ]
        
        await query.edit_message_text(
            f"🎯 *Niyetiniz Kaydedildi:* `{niyet_konusu}`\n\n📸 Şimdi lütfen bota net bir *{tip}* fotoğrafı gönderin.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=constants.ParseMode.MARKDOWN
        )
        return

    # 2. FAL NİYET SEÇİM MENÜSÜ
    elif data in ["kahve_fali", "el_fali"]:
        cursor.execute("UPDATE kullanicilar SET durum = ? WHERE telegram_id = ?", (f"niyet_bekliyor_{data}", user_id))
        conn.commit()
        conn.close()
        
        keyboard = [
            [InlineKeyboardButton("❤️ Aşk & İlişkiler", callback_data=f"niyetsec_Aşk_{data}")],
            [InlineKeyboardButton("💼 Kariyer & Para", callback_data=f"niyetsec_Kariyer_{data}")],
            [InlineKeyboardButton("✨ Genel Gelecek", callback_data=f"niyetsec_Genel_{data}")],
            [InlineKeyboardButton("🔙 Geri Dön", callback_data="main_menu")]
        ]
        await query.edit_message_text(
            "🔮 *Bakıma Başlamadan Önce Niyetinizi Seçin:*",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=constants.ParseMode.MARKDOWN
        )

    # Burç Seçimi Menüsü
    elif data == "burc_secim":
        keyboard = []
        row = []
        for b in BURCLAR:
            row.append(InlineKeyboardButton(b, callback_data=f"burcyorum_{b}"))
            if len(row) == 3:
                keyboard.append(row)
                row = []
        if row: keyboard.append(row)
        keyboard.append([InlineKeyboardButton("🔙 Geri Dön", callback_data="main_menu")])
        await query.edit_message_text("🌟 *Lütfen Burcunuzu Seçin:*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=constants.ParseMode.MARKDOWN)

    elif data.startswith("burcyorum_"):
        secilen_burc = data.split("_")[1]
        await query.edit_message_text(f"✨ *{secilen_burc} burcu için enerjiniz okunuyor...* 🔮", parse_mode=constants.ParseMode.MARKDOWN)
        
        prompt = f"Sen Tarot Vadisi astrologusun. {secilen_burc} burcu için bugün geçerli olacak tam 2 cümlelik günlük aura yorumu yaz."
        try:
            # ASENKRON ÇAĞRI
            yorum = await gemini_istek_gonder_async(prompt)
            keyboard = [
                [InlineKeyboardButton("💎 VIP Derin Burç Analizi", url=f"https://t.me/{YONETICI_KULLANICI_ADI}")], 
                [InlineKeyboardButton("🔙 Geri Dön", callback_data="burc_secim"), InlineKeyboardButton("🏠 Ana Menü", callback_data="main_menu")]
            ]
            await query.message.reply_text(
                f"🌟 *{secilen_burc} - Günün Aura Yorumu:*\n\n{yorum}",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=constants.ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Burç hatası: {e}")
            await query.message.reply_text("🔮 Enerjiler şu an çok yoğun, lütfen az sonra tekrar deneyin.")

    # Evet / Hayır Tarotu (Limitli)
    elif data == "evet_hayir":
        hak_var, yeni_hak = hak_kontrol_ve_duser(user_id)
        if not hak_var:
            keyboard = [[InlineKeyboardButton("💎 Sınırsız VIP Bakım Al", url=f"https://t.me/{YONETICI_KULLANICI_ADI}")], [InlineKeyboardButton("🏠 Ana Menü", callback_data="main_menu")]]
            await query.edit_message_text(
                "⚠️ *Günlük 2 Ücretsiz Fal Hakkınızı Doldurdunuz!*\n\nSınırsız bakım için VIP paketlerimizi tercih edebilirsiniz.",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=constants.ParseMode.MARKDOWN
            )
            return

        await query.edit_message_text("🔮 *Kartınız çekiliyor...* 🔮", parse_mode=constants.ParseMode.MARKDOWN)
        kart = random.choice(TAROT_CARDS)
        prompt = f"Kullanıcı {kart} kartını çekti. Sadece 'EVET' veya 'HAYIR' ile başla ve yanına en fazla 1 cümlelik mistik bir ipucu yaz."
        try:
            # ASENKRON ÇAĞRI
            cevap_metni = await gemini_istek_gonder_async(prompt)
            keyboard = [[InlineKeyboardButton("💎 Özel Açılım İstiyorum", url=f"https://t.me/{YONETICI_KULLANICI_ADI}")], [InlineKeyboardButton("🏠 Ana Menü", callback_data="main_menu")]]
            await query.message.reply_text(
                f"🃏 *Seçilen Kart:* {kart}\n\n✨ *Cevap:* {cevap_metni}\n\n*(Kalan Ücretsiz Hakkınız: {GUNLUK_LIMIT - yeni_hak})*",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=constants.ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Evet/Hayir hatası: {e}")
            await query.message.reply_text("🔮 Bir hata oluştu, lütfen tekrar deneyin.")

    # VIP Form Aşaması
    elif data in ["paket_detayli", "canli_bakim"]:
        paket_adi = "VIP Detaylı Açılım" if data == "paket_detayli" else "Birebir Canlı Seans"
        cursor.execute("UPDATE kullanicilar SET durum = 'form_bekliyor', paket = ? WHERE telegram_id = ?", (paket_adi, user_id))
        conn.commit()
        conn.close()
        
        keyboard = [[InlineKeyboardButton("🔙 Geri Dön", callback_data="main_menu")]]
        await query.edit_message_text(
            f"👑 *{paket_adi} Randevu Talebi*\n\nDetaylı analiz için şu bilgileri **tek mesajda yollayın**:\n1️⃣ İsim & Soyisim\n2️⃣ Doğum Tarihi & Burç\n3️⃣ Soru / Niyet",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=constants.ParseMode.MARKDOWN
        )

    conn.close()

# Fotoğraf & Form İşleme
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

    # VIP Form Yanıtı
    if durum == "form_bekliyor" and update.message.text:
        kullanici_bilgisi = update.message.text
        cursor.execute("UPDATE kullanicilar SET durum = 'yok' WHERE telegram_id = ?", (user_id,))
        conn.commit()
        conn.close()
        
        keyboard = [[InlineKeyboardButton("💬 Uzmanımıza Bağlanın", url=f"https://t.me/{YONETICI_KULLANICI_ADI}")], [InlineKeyboardButton("🏠 Ana Menü", callback_data="main_menu")]]
        await update.message.reply_text(
            "✅ *Bilgileriniz alındı!* Randevu saatini netleştirmek için doğrudan baş falcımıza yazabilirsiniz:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=constants.ParseMode.MARKDOWN
        )
        try:
            await context.bot.send_message(
                chat_id=YONETICI_ID,
                text=f"🚨 *YENİ VIP SEANS TALEBİ!*\n👤 @{user_name}\n🆔 `{user_id}`\n📦 Paket: {paket}\n📝 Bilgiler:\n{kullanici_bilgisi}",
                parse_mode=constants.ParseMode.MARKDOWN
            )
        except Exception: pass
        return

    # Fotoğraflı Fal Bakımı (Limit Kontrollü)
    if durum in ["kahve_fali", "el_fali"]:
        hak_var, yeni_hak = hak_kontrol_ve_duser(user_id)
        if not hak_var:
            keyboard = [[InlineKeyboardButton("💎 Sınırsız VIP Seans Al", url=f"https://t.me/{YONETICI_KULLANICI_ADI}")], [InlineKeyboardButton("🏠 Ana Menü", callback_data="main_menu")]]
            await update.message.reply_text(
                "⚠️ *Günlük 2 Ücretsiz Fal Hakkınızı Doldurdunuz!*\n\nDetaylı bakımlar için VIP paketlerimizi inceleyebilirsiniz.",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=constants.ParseMode.MARKDOWN
            )
            conn.close()
            return

        # Yükleme mesajı gönder ve ID'sini sakla
        loading_msg = await update.message.reply_text("🔮 *Fotoğrafınız alındı! Enerji akışı inceleniyor...* (Yaklaşık 30 sn)", parse_mode=constants.ParseMode.MARKDOWN)
        
        try:
            # Fotoğrafı indir
            if update.message.photo:
                photo_file = await update.message.photo[-1].get_file()
            elif update.message.document and update.message.document.mime_type.startswith("image"):
                photo_file = await update.message.document.get_file()
            else:
                conn.close()
                await context.bot.edit_message_text(chat_id=user_id, message_id=loading_msg.message_id, text="⚠️ Lütfen geçerli bir fotoğraf gönderin.")
                return

            os.makedirs("downloads", exist_ok=True)
            img_path = f"downloads/{user_id}.jpg"
            await photo_file.download_to_drive(img_path)
            
            # Gemini Prompt
            prompt = (
                f"Sen Tarot Vadisi falcısısın. Kullanıcı {niyet} konusuyla ilgili fotoğraf yolladı. "
                "Cevabın mistik ama kısa olsun (en fazla 2 cümle). Fotoğraftan öne çıkan 1 sembolü söyle, "
                "ardından 'Çok daha derin detaylar VIP seansımızda...' gibi bir cümleyle bitir."
            )
            
            img = Image.open(img_path)
            
            # 🚀 ASENKRON GEMINI ÇAĞRISI (Bot burada kilitlenmez)
            cevap_metni = await gemini_istek_gonder_async([prompt, img])
            
            keyboard = [[InlineKeyboardButton("💎 Falın Detayını VIP Seansla Öğren", url=f"https://t.me/{YONETICI_KULLANICI_ADI}")], [InlineKeyboardButton("🏠 Ana Menü", callback_data="main_menu")]]
            
            # Yükleme mesajını fal cevabıyla güncelle
            await context.bot.edit_message_text(
                chat_id=user_id,
                message_id=loading_msg.message_id,
                text=f"✨ *Ön Fal Analizi ({niyet}):*\n\n{cevap_metni}\n\n*(Kalan Ücretsiz Hakkınız: {GUNLUK_LIMIT - yeni_hak})*",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=constants.ParseMode.MARKDOWN
            )
            
            # Durumu sıfırla
            cursor.execute("UPDATE kullanicilar SET durum = 'yok', paket = NULL, niyet = NULL WHERE telegram_id = ?", (user_id,))
            conn.commit()
            
            # İndirilen dosyayı temizle
            os.remove(img_path)

        except Exception as e:
            logger.error(f"Fotoğraf işleme hatası: {e}")
            traceback.print_exc()
            await context.bot.edit_message_text(chat_id=user_id, message_id=loading_msg.message_id, text="🔮 Enerjiler şu an çok yoğun, fotoğraf incelenemedi. Lütfen tekrar deneyin.")

    conn.close()

def main():
    if not TELEGRAM_TOKEN or not GEMINI_API_KEY:
        print("HATA: Tokenler eksik!")
        return

    # Flask'ı ayrı bir thread'de başlat
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    # Telegram Uygulamasını Başlat
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # Komut ve Mesaj Yakalayıcılar
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("id", id_ogren))
    application.add_handler(CommandHandler("duyuru", duyuru_gonder))
    application.add_handler(CommandHandler("hakver", hak_ver))
    
    application.add_handler(CallbackQueryHandler(button_click))
    
    # Medya ve Metin İşleme (Asenkron)
    application.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE | filters.TEXT & ~filters.COMMAND, handle_media))

    print("🔮 Tarot Vadisi Yüksek Hızlı Asenkron Sürüm Başlatıldı...")
    
    # Botu çalıştır (Asenkron döngüyü başlatır)
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
