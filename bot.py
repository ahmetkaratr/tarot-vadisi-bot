import os
import random
import sqlite3
import logging
import asyncio
import threading
from datetime import datetime
from flask import Flask

app = Flask(__name__)

@app.route('/')
def home():
    return "🔮 Tarot Vadisi Optimize Edilmiş Sürüm Aktif!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port, threaded=True)

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, constants
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
from google import genai
from PIL import Image

load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# ===========================================================================
# ⚙️ YÖNETİCİ / İŞLETME AYARLARI & LİMİTLER
# ===========================================================================
YONETICI_ID = 943811337             # Telegram ID'niz
YONETICI_KULLANICI_ADI = "ahmetkaratr"  # Telegram kullanıcı adınız
GUNLUK_LIMIT = 2                   # Varsayılan günlük ücretsiz hak

gemini_client = genai.Client(api_key=GEMINI_API_KEY)

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# Veritabanı kurulumu ve eksik sütunların eklenmesi
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
            ekstra_hak INTEGER DEFAULT 0,
            son_tarih TEXT
        )
    """)
    for col in ["paket TEXT", "niyet TEXT", "burc TEXT", "kullanilan_hak INTEGER DEFAULT 0", "ekstra_hak INTEGER DEFAULT 0", "son_tarih TEXT"]:
        try:
            cursor.execute(f"ALTER TABLE kullanicilar ADD COLUMN {col}")
        except sqlite3.OperationalError:
            pass
    conn.commit()
    conn.close()

init_db()

TAROT_CARDS = ["Deli", "Büyücü", "Azize", "İmparatoriçe", "İmparator", "Aziz", "Aşıklar", "Ölüm", "Kule", "Yıldız", "Güneş", "Dünya"]
BURCLAR = ["Koç ♈", "Boğa ♉", "İkizler ♊", "Yengeç ♋", "Aslan ♌", "Başak ♍", "Terazi ♎", "Akrep ♏", "Yay ♐", "Oğlak ♑", "Kova ♒", "Balık ♓"]

# ===========================================================================
# 🔢 GERÇEKÇİ HAK HESAPLAMA ALGORİTMASI
# ===========================================================================
def kullanici_hak_durumu(user_id):
    today = datetime.now().strftime("%Y-%m-%d")
    conn = sqlite3.connect("tarot_vadisi.db")
    cursor = conn.cursor()
    cursor.execute("SELECT kullanilan_hak, ekstra_hak, son_tarih FROM kullanicilar WHERE telegram_id = ?", (user_id,))
    row = cursor.fetchone()
    
    if not row:
        cursor.execute("INSERT INTO kullanicilar (telegram_id, kullanilan_hak, ekstra_hak, son_tarih) VALUES (?, 0, 0, ?)", (user_id, today))
        conn.commit()
        conn.close()
        return GUNLUK_LIMIT, 0
    
    kullanilan_hak, ekstra_hak, son_tarih = row[0] or 0, row[1] or 0, row[2]
    
    # Yeni güne geçildiyse kullanılan hakları sıfırla ama ekstra hakları koru!
    if son_tarih != today:
        cursor.execute("UPDATE kullanicilar SET kullanilan_hak = 0, son_tarih = ? WHERE telegram_id = ?", (today, user_id))
        conn.commit()
        kullanilan_hak = 0
    
    toplam_hak = GUNLUK_LIMIT + ekstra_hak
    kalan_hak = max(0, toplam_hak - kullanilan_hak)
    conn.close()
    return kalan_hak, toplam_hak

def hak_dus(user_id):
    conn = sqlite3.connect("tarot_vadisi.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE kullanicilar SET kullanilan_hak = kullanilan_hak + 1 WHERE telegram_id = ?", (user_id,))
    conn.commit()
    conn.close()

# Asenkron Gemini İstek Gönderici
async def gemini_istek_gonder_async(contents, model='gemini-3.8-flash'):
    def sync_call():
        response = gemini_client.models.generate_content(model=model, contents=contents)
        return response.text
    return await asyncio.to_thread(sync_call)

# ===========================================================================
# 🛡️ YAPAY ZEKA GÖRSEL DOĞRULAMA (FİNCAN / EL KONTROLÜ)
# ===========================================================================
async def görsel_gecerli_mi(img_path, fal_turu):
    try:
        img = Image.open(img_path)
        if fal_turu == "kahve_fali":
            prompt = "Bu fotoğrafta bir Türk kahvesi fincanı, fincan içi veya telvesi var mı? Sadece EVET veya HAYIR yaz."
        else:
            prompt = "Bu fotoğrafta insan eli veya avuç içi var mı? Sadece EVET veya HAYIR yaz."
        
        yanit = await gemini_istek_gonder_async([prompt, img])
        return "EVET" in yanit.upper()
    except Exception as e:
        logger.error(f"Görsel doğrulama hatası: {e}")
        return True

# /start ekranı
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = sqlite3.connect("tarot_vadisi.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO kullanicilar (telegram_id, durum) VALUES (?, 'yok')", (user.id,))
    cursor.execute("UPDATE kullanicilar SET durum = 'yok', paket = NULL, niyet = NULL WHERE telegram_id = ?", (user.id,))
    conn.commit()
    conn.close()

    kalan_hak, _ = kullanici_hak_durumu(user.id)

    mesaj = (
        f"✨ *Hoş Geldin, {user.first_name}!* ✨\n\n"
        "🔮 *Tarot Vadisi Ruhsal Rehberlik ve Kehanet Alanına Adım Attın.*\n\n"
        f"🎁 *Bugünkü Kalan Ücretsiz Hakkınız:* `{kalan_hak} Adet`\n\n"
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

async def id_ogren(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    await update.message.reply_text(f"🆔 Telegram ID'niz: `{user_id}`", parse_mode=constants.ParseMode.MARKDOWN)

async def duyuru_gonder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != YONETICI_ID: return
    if not context.args:
        await update.message.reply_text("⚠️ Kullanım: `/duyuru Mesajınız...`", parse_mode=constants.ParseMode.MARKDOWN)
        return
    duyuru_metni = " ".join(context.args)
    conn = sqlite3.connect("tarot_vadisi.db")
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT telegram_id FROM kullanicilar")
    kullanicilar = cursor.fetchall()
    conn.close()

    basarili = 0
    for (k_id,) in kullanicilar:
        try:
            await context.bot.send_message(chat_id=k_id, text=duyuru_metni, parse_mode=constants.ParseMode.MARKDOWN)
            basarili += 1
            await asyncio.sleep(0.05)
        except Exception: pass
    await update.message.reply_text(f"✅ Duyuru {basarili} kişiye gönderildi.")

async def hak_ver(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != YONETICI_ID: return
    if len(context.args) < 2:
        await update.message.reply_text("⚠️ Kullanım: `/hakver <id> <ek_hak>`", parse_mode=constants.ParseMode.MARKDOWN)
        return
    try:
        hedef_id, ek_hak = int(context.args[0]), int(context.args[1])
    except ValueError:
        await update.message.reply_text("⚠️ Sayısal değer girin.")
        return

    conn = sqlite3.connect("tarot_vadisi.db")
    cursor = conn.cursor()
    cursor.execute("SELECT ekstra_hak FROM kullanicilar WHERE telegram_id = ?", (hedef_id,))
    row = cursor.fetchone()
    if not row:
        cursor.execute("INSERT INTO kullanicilar (telegram_id, ekstra_hak, son_tarih) VALUES (?, ?, ?)", (hedef_id, ek_hak, datetime.now().strftime("%Y-%m-%d")))
    else:
        mevcut_ekstra = row[0] or 0
        cursor.execute("UPDATE kullanicilar SET ekstra_hak = ? WHERE telegram_id = ?", (mevcut_ekstra + ek_hak, hedef_id))
    conn.commit()
    conn.close()

    kalan, _ = kullanici_hak_durumu(hedef_id)
    await update.message.reply_text(f"✅ ID `{hedef_id}` kullanıcısına `+{ek_hak}` hak eklendi. Güncel Kalan Hakkı: {kalan}", parse_mode=constants.ParseMode.MARKDOWN)
    try:
        await context.bot.send_message(chat_id=hedef_id, text=f"🎁 Yönetici tarafından hesabınıza *+{ek_hak} fal hakkı* tanımlandı!", parse_mode=constants.ParseMode.MARKDOWN)
    except Exception: pass

# Menü Tıklamaları
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

    elif data.startswith("niyetsec_"):
        parts = data.split("_")
        niyet_konusu, fal_turu = parts[1], "_".join(parts[2:])
        cursor.execute("UPDATE kullanicilar SET durum = ?, niyet = ? WHERE telegram_id = ?", (fal_turu, niyet_konusu, user_id))
        conn.commit()
        conn.close()
        
        tip = "Türk kahvesi fincanı" if fal_turu == "kahve_fali" else "sağ el avuç içi"
        keyboard = [[InlineKeyboardButton("🔙 Niyet Değiştir", callback_data=fal_turu)], [InlineKeyboardButton("🏠 Ana Menü", callback_data="main_menu")]]
        await query.edit_message_text(
            f"🎯 *Niyet:* `{niyet_konusu}`\n\n📸 Lütfen net bir *{tip}* fotoğrafı gönderin.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=constants.ParseMode.MARKDOWN
        )
        return

    elif data in ["kahve_fali", "el_fali"]:
        kalan, _ = kullanici_hak_durumu(user_id)
        if kalan <= 0:
            keyboard = [[InlineKeyboardButton("💎 VIP Paket Al", url=f"https://t.me/{YONETICI_KULLANICI_ADI}")], [InlineKeyboardButton("🏠 Ana Menü", callback_data="main_menu")]]
            await query.edit_message_text("⚠️ *Günlük hakkınız kalmadı!* VIP paketlerimizi inceleyebilirsiniz.", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=constants.ParseMode.MARKDOWN)
            conn.close()
            return

        cursor.execute("UPDATE kullanicilar SET durum = ? WHERE telegram_id = ?", (f"niyet_bekliyor_{data}", user_id))
        conn.commit()
        conn.close()
        
        keyboard = [
            [InlineKeyboardButton("❤️ Aşk & İlişkiler", callback_data=f"niyetsec_Aşk_{data}")],
            [InlineKeyboardButton("💼 Kariyer & Para", callback_data=f"niyetsec_Kariyer_{data}")],
            [InlineKeyboardButton("✨ Genel Gelecek", callback_data=f"niyetsec_Genel_{data}")],
            [InlineKeyboardButton("🔙 Geri Dön", callback_data="main_menu")]
        ]
        await query.edit_message_text("🔮 *Niyetinizi Seçin:*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=constants.ParseMode.MARKDOWN)

    elif data == "burc_secim":
        formatted_kb = []
        row = []
        for b in BURCLAR:
            row.append(InlineKeyboardButton(b, callback_data=f"burcyorum_{b}"))
            if len(row) == 3:
                formatted_kb.append(row)
                row = []
        if row: formatted_kb.append(row)
        formatted_kb.append([InlineKeyboardButton("🔙 Geri Dön", callback_data="main_menu")])
        await query.edit_message_text("🌟 *Burcunuzu Seçin:*", reply_markup=InlineKeyboardMarkup(formatted_kb), parse_mode=constants.ParseMode.MARKDOWN)

    elif data.startswith("burcyorum_"):
        secilen_burc = data.split("_")[1]
        await query.edit_message_text(f"✨ *{secilen_burc} burcu yorumlanıyor...*", parse_mode=constants.ParseMode.MARKDOWN)
        prompt = f"Sen astrologusun. {secilen_burc} burcu için 2 cümlelik gizemli günlük aura yorumu yaz."
        try:
            yorum = await gemini_istek_gonder_async(prompt)
            keyboard = [[InlineKeyboardButton("🔙 Geri Dön", callback_data="burc_secim"), InlineKeyboardButton("🏠 Ana Menü", callback_data="main_menu")]]
            await query.message.reply_text(f"🌟 *{secilen_burc}*: {yorum}", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=constants.ParseMode.MARKDOWN)
        except Exception:
            await query.message.reply_text("🔮 Enerjiler yoğun, tekrar deneyin.")

    elif data == "evet_hayir":
        kalan, _ = kullanici_hak_durumu(user_id)
        if kalan <= 0:
            keyboard = [[InlineKeyboardButton("💎 VIP Paket Al", url=f"https://t.me/{YONETICI_KULLANICI_ADI}")], [InlineKeyboardButton("🏠 Ana Menü", callback_data="main_menu")]]
            await query.edit_message_text("⚠️ Hakkınız bitti.", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=constants.ParseMode.MARKDOWN)
            return

        hak_dus(user_id)
        kalan_sonra, _ = kullanici_hak_durumu(user_id)
        kart = random.choice(TAROT_CARDS)
        prompt = f"Kullanıcı {kart} çekti. Sadece EVET veya HAYIR ile başla ve 1 cümlelik mistik ipucu yaz."
        try:
            cevap = await gemini_istek_gonder_async(prompt)
            keyboard = [[InlineKeyboardButton("🏠 Ana Menü", callback_data="main_menu")]]
            await query.edit_message_text(f"🃏 *Kart:* {kart}\n\n✨ *Cevap:* {cevap}\n\n*(Kalan Hak: {kalan_sonra})*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=constants.ParseMode.MARKDOWN)
        except Exception:
            await query.message.reply_text("🔮 Hata oluştu.")

    elif data in ["paket_detayli", "canli_bakim"]:
        paket_adi = "VIP Detaylı Açılım" if data == "paket_detayli" else "Birebir Canlı Seans"
        cursor.execute("UPDATE kullanicilar SET durum = 'form_bekliyor', paket = ? WHERE telegram_id = ?", (paket_adi, user_id))
        conn.commit()
        conn.close()
        keyboard = [[InlineKeyboardButton("🔙 Geri Dön", callback_data="main_menu")]]
        await query.edit_message_text(f"👑 *{paket_adi}*\n\nBilgilerinizi tek mesajda yazın (İsim, Burç, Soru):", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=constants.ParseMode.MARKDOWN)

    conn.close()

# Fotoğraf & Form İşleme + Fincan/El Doğrulama Filtresi
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

    if durum == "form_bekliyor" and update.message.text:
        kullanici_bilgisi = update.message.text
        cursor.execute("UPDATE kullanicilar SET durum = 'yok' WHERE telegram_id = ?", (user_id,))
        conn.commit()
        conn.close()
        keyboard = [[InlineKeyboardButton("💬 Uzmanımıza Yazın", url=f"https://t.me/{YONETICI_KULLANICI_ADI}")], [InlineKeyboardButton("🏠 Ana Menü", callback_data="main_menu")]]
        await update.message.reply_text("✅ Bilgileriniz alındı! Uzmanımıza bağlanabilirsiniz:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=constants.ParseMode.MARKDOWN)
        try:
            await context.bot.send_message(chat_id=YONETICI_ID, text=f"🚨 *YENİ VIP TALEBİ!*\n👤 @{user_name}\n🆔 `{user_id}`\n📦 {paket}\n📝 {kullanici_bilgisi}", parse_mode=constants.ParseMode.MARKDOWN)
        except Exception: pass
        return

    if durum in ["kahve_fali", "el_fali"]:
        kalan, _ = kullanici_hak_durumu(user_id)
        if kalan <= 0:
            keyboard = [[InlineKeyboardButton("💎 VIP Paket Al", url=f"https://t.me/{YONETICI_KULLANICI_ADI}")], [InlineKeyboardButton("🏠 Ana Menü", callback_data="main_menu")]]
            await update.message.reply_text("⚠️ Günlük hakkınız doldu.", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=constants.ParseMode.MARKDOWN)
            conn.close()
            return

        loading_msg = await update.message.reply_text("🔮 Fotoğrafınız taranıyor...", parse_mode=constants.ParseMode.MARKDOWN)
        
        try:
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
            
            # 🛡️ GÖRSEL DOĞRULAMA (Fincan veya El dışı resimleri reddet)
            gecerli_mi = await görsel_gecerli_mi(img_path, durum)
            if not gecerli_mi:
                if os.path.exists(img_path): os.remove(img_path)
                conn.close()
                red_mesaj = "☕ Gönderdiğiniz fotoğrafta Türk kahvesi fincanı tespit edilemedi!" if durum == "kahve_fali" else "✋ Gönderdiğiniz fotoğrafta insan eli tespit edilemedi!"
                await context.bot.edit_message_text(chat_id=user_id, message_id=loading_msg.message_id, text=f"⚠️ {red_mesaj}\n\nLütfen uygun bir fotoğraf yükleyin (Hakkınız düşülmedi).")
                return

            # Hak düş ve analizi başlat
            hak_dus(user_id)
            kalan_sonra, _ = kullanici_hak_durumu(user_id)

            prompt = f"Sen falcısın. Kullanıcı {niyet} konusunda fotoğraf yolladı. En fazla 2 cümlelik mistik ve kısa bir ön yorum yap."
            img = Image.open(img_path)
            cevap_metni = await gemini_istek_gonder_async([prompt, img])
            
            keyboard = [[InlineKeyboardButton("💎 VIP Detaylı Fal Al", url=f"https://t.me/{YONETICI_KULLANICI_ADI}")], [InlineKeyboardButton("🏠 Ana Menü", callback_data="main_menu")]]
            
            await context.bot.edit_message_text(
                chat_id=user_id,
                message_id=loading_msg.message_id,
                text=f"✨ *Fal Analizi ({niyet}):*\n\n{cevap_metni}\n\n*(Kalan Hak: {kalan_sonra})*",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=constants.ParseMode.MARKDOWN
            )
            
            cursor.execute("UPDATE kullanicilar SET durum = 'yok', paket = NULL, niyet = NULL WHERE telegram_id = ?", (user_id,))
            conn.commit()
            if os.path.exists(img_path): os.remove(img_path)

        except Exception as e:
            logger.error(f"Hata: {e}")
            await context.bot.edit_message_text(chat_id=user_id, message_id=loading_msg.message_id, text="🔮 Hata oluştu, lütfen tekrar deneyin.")

    conn.close()

def main():
    if not TELEGRAM_TOKEN or not GEMINI_API_KEY:
        print("HATA: Tokenler eksik!")
        return

    threading.Thread(target=run_flask, daemon=True).start()

    application = Application.builder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("id", id_ogren))
    application.add_handler(CommandHandler("duyuru", duyuru_gonder))
    application.add_handler(CommandHandler("hakver", hak_ver))
    
    application.add_handler(CallbackQueryHandler(button_click))
    application.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE | filters.TEXT & ~filters.COMMAND, handle_media))

    print("🔮 Tarot Vadisi Tam ve Eksiksiz Sürüm Çalışmaya Başladı...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
