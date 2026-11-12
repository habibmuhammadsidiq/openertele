import time
import os
import sys
import re
import requests
import uuid
import threading
import json
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.microsoft import EdgeChromiumDriverManager

# Library Telegram Bot
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler

os.system('')

# ==========================================
# ⚙️ KONFIGURASI UTAMA (SUDAH TERPASANG)
# ==========================================
SMSCODE_API_KEY = "e437a6db9eb025db574a3b4823a75675d924184435537fec31a83be1987c15f5"

TELEGRAM_BOT_TOKEN = "8934114427:AAFpvkeRiLKLBW7HbCfqC89mhjifEgr2jMk"
ADMIN_ID = 8910596126

# 💰 KONFIGURASI SALDO & HARGA PER AKUN
BIAYA_PER_AKUN = 500  # Saldo terpotong setiap 1 akun sukses

FILE_KEYS = "keys.json"
FILE_USERS = "users_active.json"

DAFTAR_TARGET_OTP = [
    {"product_id": 1369239445, "max_retry": 3, "nama": "Target Utama"},
    {"product_id": 1369643203, "max_retry": 3, "nama": "Target Cadangan"}
]

file_lock = threading.Lock()
stats_lock = threading.Lock()

# ==========================================
# 📡 FUNGSI HELPER KIRIM NOTIFIKASI TELEGRAM
# ==========================================
def kirim_pesan_tele(chat_id, text):
    if not chat_id:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"[!] Gagal kirim notif Telegram: {e}")

def kirim_file_tele(chat_id, file_path, caption=""):
    if not chat_id or not os.path.exists(file_path):
        return
    if os.path.getsize(file_path) == 0:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
    try:
        with open(file_path, "rb") as f:
            requests.post(
                url,
                data={"chat_id": chat_id, "caption": caption},
                files={"document": f},
                timeout=20
            )
    except Exception as e:
        print(f"[!] Gagal kirim file Telegram: {e}")

# ==========================================
# 📂 MANAJEMEN DATABASE & FILE
# ==========================================
def load_json(filename):
    with file_lock:
        if not os.path.exists(filename):
            return {}
        try:
            with open(filename, "r") as f:
                return json.load(f)
        except:
            return {}

def save_json(filename, data):
    with file_lock:
        with open(filename, "w") as f:
            json.dump(data, f, indent=4)

def simpan_ke_file(nama_file, data):
    with file_lock:
        with open(nama_file, "a", encoding="utf-8") as f:
            f.write(data + "\n")

def hapus_akun_dari_list(email_target, nama_file="sukses.txt"):
    with file_lock:
        try:
            with open(nama_file, 'r', encoding="utf-8") as f:
                lines = f.readlines()
            with open(nama_file, 'w', encoding="utf-8") as f:
                for line in lines:
                    if not line.strip():
                        continue
                    data = line.strip().split()
                    if len(data) > 0 and data[0] != email_target:
                        f.write(line)
        except Exception as e:
            print(f"[!] Gagal menghapus akun dari list: {e}")

def cek_halaman_pindah(driver, waktu_tunggu=5):
    try:
        url_awal = driver.current_url
        teks_awal = driver.find_element(By.TAG_NAME, "body").text[:500]
    except:
        return False
    time.sleep(waktu_tunggu)
    try:
        url_akhir = driver.current_url
        teks_akhir = driver.find_element(By.TAG_NAME, "body").text[:500]
    except:
        return True
    return not (url_awal == url_akhir and teks_awal == teks_akhir)

# ==========================================
# 🚀 LOGIKA UTAMA SELENIUM WORKER
# ==========================================
def worker_thread(thread_id, daftar_akun, chat_id, is_admin, stats):
    thread_name = f"Thread-{thread_id}"
    profile_dir = os.path.abspath(f"edge_profile_{thread_id}")

    options = EdgeOptions()
    options.add_argument(f"user-data-dir={profile_dir}")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    options.add_argument("--start-maximized")
    
    try:
        service = EdgeService(EdgeChromiumDriverManager().install())
        driver = webdriver.Edge(service=service, options=options)
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        })
        driver.execute_cdp_cmd('Network.clearBrowserCache', {})
        driver.execute_cdp_cmd('Network.clearBrowserCookies', {})
    except Exception as e:
        kirim_pesan_tele(chat_id, f"❌ `[{thread_name}]` Gagal membuka browser Edge: `{e}`")
        return

    for baris_asli in daftar_akun:
        data = baris_asli.split(' ')
        if len(data) < 2:
            continue

        email_full = data[0]
        password = data[1]

        if not is_admin:
            users_data = load_json(FILE_USERS)
            saldo_sekarang = users_data.get(str(chat_id), {}).get("saldo", 0)
            if saldo_sekarang < BIAYA_PER_AKUN:
                kirim_pesan_tele(
                    chat_id,
                    f"⚠️ `[{thread_name}]` **Proses Dihentikan!**\nSaldo Anda tidak mencukupi (`Rp {saldo_sekarang:,}`). Minimal saldo per akun: `Rp {BIAYA_PER_AKUN:,}`."
                )
                break

        try:
            url_login = "https://accounts.google.com/v3/signin/identifier?continue=https://mail.google.com/mail/?service%3Dmail%26flowName%3DGlifWebSignIn%26flowEntry%3DAccountChooser%26ec%3Dasw-gmail-globalnav-signin&uj=gafb-gmail_asw-globalnav-id&flowName=GlifWebSignIn&flowEntry=ServiceLogin&hl=id"
            driver.get(url_login)
            time.sleep(4) 

            try:
                btn_cookie = driver.find_element(By.XPATH, "//button[contains(text(), 'Terima semua')]")
                btn_cookie.click()
                time.sleep(2)
            except:
                pass
            
            wait = WebDriverWait(driver, 20)
            email_input = wait.until(EC.presence_of_element_located((By.ID, "identifierId")))
            email_input.send_keys(email_full)
            time.sleep(1)
            driver.find_element(By.XPATH, "//button[contains(., 'Berikutnya') or contains(., 'Next')]").click()
            time.sleep(4)

            if "Verifikasi diri Anda" in driver.page_source or "Tidak dapat" in driver.page_source:
                raise Exception("Terkena Captcha / Verifikasi diri Anda")

            try:
                pass_input = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='password']")))
                pass_input.send_keys(password)
                time.sleep(1)
                driver.find_element(By.XPATH, "//button[contains(., 'Berikutnya') or contains(., 'Next')]").click()
                time.sleep(5)
            except TimeoutException:
                raise Exception("Input password tidak muncul / Email salah")

            time.sleep(3)
            source = driver.page_source
            if "Login lebih cepat" in source or "kunci sandi" in source:
                body = driver.find_element(By.TAG_NAME, "body")
                body.click(); time.sleep(0.5)
                for _ in range(3):
                    body.send_keys(Keys.TAB); time.sleep(0.3)
                body.send_keys(Keys.ENTER); time.sleep(4)

            source = driver.page_source
            if "Pastikan Anda selalu dapat login" in source or "Tambah nomor telepon pemulihan" in source:
                try:
                    btn_batal = driver.find_element(By.XPATH, "//*[text()='Batal' or text()='Cancel' or contains(text(), 'Batal')]")
                    driver.execute_script("arguments[0].click();", btn_batal)
                except: pass
                time.sleep(4)

            source = driver.page_source
            if "Tetapkan alamat rumah" in source or "Alamat rumah" in source:
                try:
                    btn_lewati = driver.find_element(By.XPATH, "//*[text()='Lewati' or text()='Skip' or contains(text(), 'Lewati')]")
                    driver.execute_script("arguments[0].click();", btn_lewati)
                except: pass
                time.sleep(4)

            source = driver.page_source
            if "selfie" in source or "Verifikasi video" in source:
                try:
                    btn_skip_selfie = driver.find_element(By.XPATH, "//*[text()='Lain kali' or text()='Not now' or text()='Lewati' or contains(text(), 'Lain kali')]")
                    driver.execute_script("arguments[0].click();", btn_skip_selfie)
                except: pass
                time.sleep(4)

            source = driver.page_source
            if "Pilih 1 cara untuk memverifikasi" in source or "Lakukan pemeriksaan perangkat" in source:
                try:
                    driver.find_element(By.XPATH, "//*[contains(text(), 'Verifikasi nomor telepon Anda')]").click()
                except: pass
                time.sleep(4)

            status_akun = "STUCK"
            for _ in range(10):
                time.sleep(3)
                source = driver.page_source
                if "Terima kode SMS" in source or "Masukkan nomor telepon" in source or len(driver.find_elements(By.CSS_SELECTOR, "input[type='tel']")) > 0:
                    status_akun = "BUTUH_OTP"
                    break
                elif driver.current_url.startswith("https://mail.google.com") or driver.current_url.startswith("https://myaccount.google.com"):
                    status_akun = "SUKSES_LANGSUNG"
                    break

            if status_akun == "STUCK":
                raise Exception("Halaman STUCK / Gagal masuk halaman OTP")

            if status_akun == "BUTUH_OTP":
                HEADERS = {"Authorization": f"Bearer {SMSCODE_API_KEY}", "Content-Type": "application/json"}
                otp_sukses = False
                
                for target in DAFTAR_TARGET_OTP:
                    product_id = target["product_id"]
                    max_retry = target["max_retry"]
                    
                    for attempt in range(max_retry):
                        payload_order = {"product_id": product_id, "quantity": 1}
                        HEADERS_ORDER = HEADERS.copy()
                        HEADERS_ORDER["Idempotency-Key"] = str(uuid.uuid4())
                        
                        order_id = None
                        nomor_hp = None
                        try:
                            req_beli = requests.post("https://api.smscode.gg/v1/orders/create", headers=HEADERS_ORDER, json=payload_order, timeout=10)
                            resp = req_beli.json()
                            if resp.get('success'):
                                data_order = resp['data']['orders'][0]
                                order_id = data_order['id']
                                nomor_hp = data_order['phone_number']
                            else:
                                break
                        except:
                            continue

                        if not order_id:
                            continue

                        try:
                            nomor_input = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[name='phoneNumber'], input[type='tel']")))
                            nomor_input.clear(); time.sleep(0.5)
                            nomor_input.click(); time.sleep(0.5)
                            nomor_input.send_keys("+" + str(nomor_hp))
                            time.sleep(1)
                            driver.find_element(By.XPATH, "//button[contains(., 'Berikutnya') or contains(., 'Next')]").click()
                        except:
                            continue

                        if not cek_halaman_pindah(driver, 5):
                            try:
                                driver.back(); time.sleep(3)
                            except: pass
                            continue

                        otp_code = None
                        for i in range(10): 
                            time.sleep(5)
                            try:
                                req_cek = requests.get(f"https://api.smscode.gg/v1/orders/{order_id}", headers=HEADERS, timeout=10)
                                cek_data = req_cek.json()
                                if cek_data.get('success') and cek_data.get('data', {}).get('otp_code'):
                                    otp_code = cek_data.get('data', {}).get('otp_code')
                                    break
                            except: pass

                        if otp_code:
                            try:
                                wait.until(EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'Masukkan kode')]")))
                                time.sleep(2)
                                otp_input = driver.find_element(By.CSS_SELECTOR, "input[name='code'], input[id='code'], input[aria-label='Masukkan kode']")
                                otp_input.clear(); time.sleep(0.5)
                                otp_input.click(); time.sleep(0.5)
                                otp_input.send_keys(str(otp_code))
                                time.sleep(1)
                                driver.find_element(By.XPATH, "//button[contains(., 'Berikutnya') or contains(., 'Next')]").click()
                                
                                if not cek_halaman_pindah(driver, 5):
                                    try:
                                        driver.back(); time.sleep(3)
                                    except: pass
                                    continue
                            except:
                                try:
                                    driver.back(); time.sleep(3)
                                except: pass
                                continue

                            requests.post("https://api.smscode.gg/v1/orders/finish", headers=HEADERS, json={"id": order_id})
                            otp_sukses = True
                            break
                        else:
                            try:
                                driver.back(); time.sleep(3)
                            except: pass
                            continue

                    if otp_sukses:
                        break
                if not otp_sukses:
                    raise Exception("Gagal mendapatkan / memasukkan OTP")

            simpan_ke_file("siapjual.txt", baris_asli)
            hapus_akun_dari_list(email_full, "sukses.txt")

            with stats_lock:
                stats["sukses"] += 1
                stats["list_sukses"].append(email_full)

            sisa_saldo_info = "Unlimited (Admin)"
            if not is_admin:
                users_data = load_json(FILE_USERS)
                str_uid = str(chat_id)
                if str_uid in users_data:
                    users_data[str_uid]["saldo"] = max(0, users_data[str_uid].get("saldo", 0) - BIAYA_PER_AKUN)
                    save_json(FILE_USERS, users_data)
                    sisa_saldo_info = f"Rp {users_data[str_uid]['saldo']:,}"

            kirim_pesan_tele(
                chat_id,
                f"✅ **AKUN SUKSES** `[{thread_name}]`\n"
                f"📧 Akun: `{baris_asli}`\n"
                f"📌 Metode: `{status_akun}`\n"
                f"💰 Sisa Saldo: `{sisa_saldo_info}`"
            )
            time.sleep(3)

        except Exception as e:
            alasan_gagal = str(e)
            simpan_ke_file("gagal.txt", f"{baris_asli} | Alasan: {alasan_gagal}")
            hapus_akun_dari_list(email_full, "sukses.txt")

            with stats_lock:
                stats["gagal"] += 1
                stats["list_gagal"].append(f"{email_full} ({alasan_gagal})")

            kirim_pesan_tele(
                chat_id,
                f"❌ **AKUN GAGAL** `[{thread_name}]`\n"
                f"📧 Email: `{email_full}`\n"
                f"⚠️ Alasan: `{alasan_gagal}`"
            )

        try:
            driver.execute_cdp_cmd('Network.clearBrowserCache', {})
            driver.execute_cdp_cmd('Network.clearBrowserCookies', {})
            driver.get("about:blank")
        except:
            pass
        time.sleep(2)

    try:
        driver.quit()
    except:
        pass

# ==========================================
# 🤖 PERINTAH TELEGRAM USER & ADMIN
# ==========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = (
        "🤖 **BOT AUTO OPENER GMAIL & OTP** 🤖\n\n"
        f"🆔 ID Telegram Anda: `{user_id}`\n"
        f"💵 Tarif per akun sukses: **Rp {BIAYA_PER_AKUN:,}**\n\n"
        "**Menu Pengguna:**\n"
        "• `/redeem <kode_key>` - Aktivasi lisensi key\n"
        "• `/status` - Cek masa aktif & saldo\n"
        "• `/saldo` - Cek sisa deposit\n"
        "• `/run <jumlah_thread>` - Jalankan bot\n"
        "• `/hasil` - Unduh file hasil sukses & gagal\n"
    )
    if user_id == ADMIN_ID:
        text += (
            "\n**Menu Khusus Admin:**\n"
            "• `/genkey <hari>` - Buat key baru\n"
            "• `/listkeys` - Lihat semua key\n"
            "• `/delkey <KEY>` - Hapus key\n"
            "• `/addsaldo <user_id> <nominal>` - Isi deposit user\n"
        )
    await update.message.reply_text(text, parse_mode="Markdown")

async def redeem_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    args = context.args
    if not args:
        await update.message.reply_text("❌ Format salah! Contoh: `/redeem KEY-ABCD1234`", parse_mode="Markdown")
        return

    key_input = args[0].strip()
    keys_data = load_json(FILE_KEYS)

    if key_input not in keys_data:
        await update.message.reply_text("❌ Key tidak valid atau tidak ditemukan!")
        return

    if keys_data[key_input]["status"] == "used":
        await update.message.reply_text("❌ Key ini sudah pernah digunakan!")
        return

    days = keys_data[key_input].get("days", 1)
    expired_time = datetime.now() + timedelta(days=days)

    keys_data[key_input]["status"] = "used"
    keys_data[key_input]["used_by"] = user_id
    save_json(FILE_KEYS, keys_data)

    users_data = load_json(FILE_USERS)
    saldo_lama = users_data.get(user_id, {}).get("saldo", 0)
    users_data[user_id] = {
        "expired_at": expired_time.strftime("%Y-%m-%d %H:%M:%S"),
        "saldo": saldo_lama
    }
    save_json(FILE_USERS, users_data)

    await update.message.reply_text(
        f"✅ **Aktivasi Lisensi Berhasil!**\n"
        f"⏳ Masa Aktif: `{users_data[user_id]['expired_at']}`\n"
        f"💰 Saldo Saat Ini: `Rp {saldo_lama:,}`",
        parse_mode="Markdown"
    )

async def cek_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    users_data = load_json(FILE_USERS)

    async def cek_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    users_data = load_json(FILE_USERS)

    if user_id not in users_data:
        await update.message.reply_text("❌ Akun belum terdaftar. Silakan `/redeem <key>` atau hubungi Admin.")
        return

    info = users_data[user_id]
    expired_str = info.get("expired_at", "-")
    saldo = info.get("saldo", 0)

    await update.message.reply_text(
        f"📊 **STATUS AKUN ANDA**\n\n"
        f"🆔 User ID: `{user_id}`\n"
        f"⏳ Expired Key: `{expired_str}`\n"
        f"💰 Sisa Saldo: **Rp {saldo:,}**\n"
        f"💵 Tarif/Akun: Rp {BIAYA_PER_AKUN:,}",
        parse_mode="Markdown"
    )

async def cek_saldo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cek_status(update, context)

async def cmd_hasil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text("📂 Mengirimkan file laporan hasil...")
    
    ada_file = False
    if os.path.exists("siapjual.txt") and os.path.getsize("siapjual.txt") > 0:
        kirim_file_tele(chat_id, "siapjual.txt", "✅ Daftar Akun Sukses (siapjual.txt)")
        ada_file = True
    if os.path.exists("gagal.txt") and os.path.getsize("gagal.txt") > 0:
        kirim_file_tele(chat_id, "gagal.txt", "❌ Daftar Akun Gagal (gagal.txt)")
        ada_file = True
        
    if not ada_file:
        await update.message.reply_text("📭 Belum ada file hasil (`siapjual.txt` atau `gagal.txt`) yang tersedia.", parse_mode="Markdown")

# --- ADMIN COMMANDS ---
async def cmd_genkey(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Perintah ini khusus untuk Admin!")
        return

    try:
        days = int(context.args[0]) if context.args else 1
    except ValueError:
        days = 1

    unique_key = "KEY-" + str(uuid.uuid4()).upper()[:8]
    keys_data = load_json(FILE_KEYS)
    keys_data[unique_key] = {
        "days": days,
        "status": "unused",
        "used_by": None,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    save_json(FILE_KEYS, keys_data)

    await update.message.reply_text(
        f"🔑 **KEY BARU BERHASIL DIBUAT**\n\n"
        f"Key: `{unique_key}`\n"
        f"Durasi: `{days} Hari`",
        parse_mode="Markdown"
    )

async def cmd_delkey(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if not context.args:
        await update.message.reply_text("Format: `/delkey KEY-XXXX`", parse_mode="Markdown")
        return

    key_target = context.args[0].strip()
    keys_data = load_json(FILE_KEYS)
    if key_target in keys_data:
        del keys_data[key_target]
        save_json(FILE_KEYS, keys_data)
        await update.message.reply_text(f"🗑️ Key `{key_target}` berhasil dihapus.", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ Key tidak ditemukan.")

async def cmd_listkeys(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    keys_data = load_json(FILE_KEYS)
    if not keys_data:
        await update.message.reply_text("📁 Belum ada key yang dibuat.")
        return

    msg = "📋 **DAFTAR KEY LISENSI:**\n\n"
    for k, v in keys_data.items():
        msg += f"• `{k}` ({v['days']} Hari) - **{v['status']}**\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def cmd_addsaldo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Perintah khusus Admin!")
        return

    if len(context.args) < 2:
        await update.message.reply_text("❌ Format salah! Contoh: `/addsaldo 8910596126 50000`", parse_mode="Markdown")
        return

    target_uid = context.args[0].strip()
    try:
        nominal = int(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ Nominal saldo harus berupa angka!")
        return

    users_data = load_json(FILE_USERS)
    if target_uid not in users_data:
        users_data[target_uid] = {"expired_at": "-", "saldo": 0}

    users_data[target_uid]["saldo"] = users_data[target_uid].get("saldo", 0) + nominal
    save_json(FILE_USERS, users_data)

    await update.message.reply_text(
        f"✅ **DEPOSIT BERHASIL DITAMBAHKAN**\n\n"
        f"👤 User ID: `{target_uid}`\n"
        f"➕ Tambahan: `Rp {nominal:,}`\n"
        f"💰 Total Saldo: **Rp {users_data[target_uid]['saldo']:,}**",
        parse_mode="Markdown"
    )
    kirim_pesan_tele(target_uid, f"💰 **DEPOSIT MASUK!**\nAdmin menambahkan saldo sebesar **Rp {nominal:,}**.\nTotal saldo Anda sekarang: **Rp {users_data[target_uid]['saldo']:,}**.")

# --- RUN BOT SELENIUM ---
async def cmd_run(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = str(update.effective_user.id)
    is_admin = (int(user_id) == ADMIN_ID)

    users_data = load_json(FILE_USERS)
    if not is_admin:
        if user_id not in users_data:
            await update.message.reply_text("❌ Anda belum melakukan aktivasi. Gunakan `/redeem <key>`")
            return
        exp_str = users_data[user_id].get("expired_at", "-")
        if exp_str == "-" or datetime.now() > datetime.strptime(exp_str, "%Y-%m-%d %H:%M:%S"):
            await update.message.reply_text("❌ Masa aktif key Anda telah habis.")
            return
        if users_data[user_id].get("saldo", 0) < BIAYA_PER_AKUN:
            await update.message.reply_text(f"❌ Saldo tidak cukup! Minimal saldo: `Rp {BIAYA_PER_AKUN:,}`.", parse_mode="Markdown")
            return

    try:
        with open('sukses.txt', 'r', encoding="utf-8") as file:
            semua_akun = [line.strip() for line in file.readlines() if line.strip()]
    except FileNotFoundError:
        await update.message.reply_text("❌ File `sukses.txt` tidak ditemukan!")
        return

    if not semua_akun:
        await update.message.reply_text("❌ File `sukses.txt` kosong!")
        return

    try:
        jml_thread = int(context.args[0]) if context.args else 1
        jml_thread = max(1, min(jml_thread, 10))
    except:
        jml_thread = 1

    await update.message.reply_text(
        f"🚀 **MEMULAI PROSES OTOMATISASI**\n"
        f"📊 Total Antrian: `{len(semua_akun)} Akun`\n"
        f"⚙️ Jumlah Thread: `{jml_thread}`\n\n"
        f"Laporan akun sukses & gagal akan dikirim otomatis ke chat ini.",
        parse_mode="Markdown"
    )

    chunks = [[] for _ in range(jml_thread)]
    for i, akun in enumerate(semua_akun):
        chunks[i % jml_thread].append(akun)

    stats = {
        "sukses": 0,
        "gagal": 0,
        "list_sukses": [],
        "list_gagal": []
    }

    def run_threads_bg():
        threads = []
        for i in range(jml_thread):
            if chunks[i]:
                t = threading.Thread(target=worker_thread, args=(i+1, chunks[i], chat_id, is_admin, stats))
                threads.append(t)
                t.start()
        for t in threads:
            t.join()

        sisa_saldo_akhir = "Unlimited (Admin)"
        if not is_admin:
            u_data = load_json(FILE_USERS)
            sisa_saldo_akhir = f"Rp {u_data.get(user_id, {}).get('saldo', 0):,}"

        ringkasan = (
            f"🏁 **SEMUA PROSES SELESAI!** 🏁\n\n"
            f"✅ Total Sukses: **{stats['sukses']} Akun**\n"
            f"❌ Total Gagal: **{stats['gagal']} Akun**\n"
            f"💰 Sisa Saldo: `{sisa_saldo_akhir}`\n\n"
            f"Mengirimkan file hasil di bawah ini..."
        )
        kirim_pesan_tele(chat_id, ringkasan)
        kirim_file_tele(chat_id, "siapjual.txt", "✅ Hasil Akun Sukses (siapjual.txt)")
        kirim_file_tele(chat_id, "gagal.txt", "❌ Hasil Akun Gagal (gagal.txt)")

    threading.Thread(target=run_threads_bg).start()

# ==========================================
# MAIN PROGRAM
# ==========================================
def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("redeem", redeem_key))
    app.add_handler(CommandHandler("status", cek_status))
    app.add_handler(CommandHandler("saldo", cek_saldo))
    app.add_handler(CommandHandler("run", cmd_run))
    app.add_handler(CommandHandler("hasil", cmd_hasil))

    # Admin
    app.add_handler(CommandHandler("genkey", cmd_genkey))
    app.add_handler(CommandHandler("delkey", cmd_delkey))
    app.add_handler(CommandHandler("listkeys", cmd_listkeys))
    app.add_handler(CommandHandler("addsaldo", cmd_addsaldo))

    print("🤖 Bot Telegram siap digunakan! Tekan Ctrl+C untuk berhenti.")
    app.run_polling()

if __name__ == '__main__':
    main()
