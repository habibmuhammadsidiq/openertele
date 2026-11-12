import time
import os
import sys
import re
import requests
import uuid
import threading
import json
from datetime import datetime, timedelta
from selenium import webdriverfrom selenium.webdriver.edge.service import Service as EdgeService
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
# ⚙️ KONFIGURASI UTAMA (SUDAH DIPASANG)
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
