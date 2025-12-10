# ==========================================
# 模擬真實架構：感測器 -> DB -> ML -> DB -> Web
# ==========================================
import os
os.system('pip install fastapi uvicorn pydantic requests pyngrok nest_asyncio')

import sqlite3
import time
import json
import random
import requests
import threading
import uvicorn
import nest_asyncio
from pyngrok import ngrok
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime

nest_asyncio.apply()

# ★★★ 請填入你的 Ngrok Token ★★★
NGROK_TOKEN = "36biCzr0Ibfu5xePl72Io9vxx1U_3u4PyckBZK54ZEBzg1743"
ngrok.set_auth_token(NGROK_TOKEN)

# ==========================================
# 1. 資料庫初始化 (建立兩張表)
# ==========================================
DB_NAME = "water_system.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    # 表格 1: 存放感測器原始數據 (Raw Data)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS raw_sensor_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            device_id TEXT,
            ph REAL,
            cod REAL
        )
    ''')
    # 表格 2: 存放 ML 運算後的結果 (Processed Result)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ml_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            raw_id INTEGER,
            is_pollution BOOLEAN,
            sluice_gate_status BOOLEAN
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# ==========================================
# 2. 定義 API 伺服器 (FastAPI)
# ==========================================
app = FastAPI()

# 設定 CORS 允許網頁連線
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允許任何網址連線
    allow_credentials=True,
    allow_methods=["*"],  # 允許任何方法 (GET, POST...)
    allow_headers=["*"],  # 允許任何 Header (包含 ngrok-skip-browser-warning)
)

# 定義資料格式
class RawData(BaseModel):
    device_id: str
    timestamp: str
    ph: float
    cod: float

class MLResult(BaseModel):
    timestamp: str
    raw_id: int
    is_pollution: bool
    sluice_gate_status: bool

# --- API 1: 感測器上傳專用 (寫入 Raw Table) ---
@app.post("/api/sensor/upload")
def upload_sensor_data(data: RawData):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO raw_sensor_data (timestamp, device_id, ph, cod) VALUES (?, ?, ?, ?)",
        (data.timestamp, data.device_id, data.ph, data.cod)
    )
    conn.commit()
    conn.close()
    return {"status": "saved_to_raw"}

# --- API 2: ML 模型抓取資料專用 (讀取 Raw Table) ---
@app.get("/api/ml/fetch_latest")
def get_latest_raw_data():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    # 抓取最新一筆原始數據
    cursor.execute("SELECT * FROM raw_sensor_data ORDER BY id DESC LIMIT 1")
    row = cursor.fetchone()
    conn.close()

    if row:
        return {"id": row[0], "timestamp": row[1], "device_id": row[2], "ph": row[3], "cod": row[4]}
    return {"error": "no_data"}

# --- API 3: ML 模型回傳結果專用 (寫入 Result Table) ---
@app.post("/api/ml/submit_result")
def submit_ml_result(data: MLResult):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO ml_results (timestamp, raw_id, is_pollution, sluice_gate_status) VALUES (?, ?, ?, ?)",
        (data.timestamp, data.raw_id, data.is_pollution, data.sluice_gate_status)
    )
    conn.commit()
    conn.close()
    return {"status": "saved_to_result"}

# --- API 4: 網頁前端呈現專用 (讀取 Raw + Result Table) ---
@app.get("/api/dashboard/monitor")
def get_dashboard_data():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    # 我們同時需要「原始數值」和「ML判斷結果」，所以這裡做了一個 JOIN 查詢
    # 找出最新的一筆 ML 結果，並把它對應的原始數據也抓出來
    query = '''
        SELECT r.ph, r.cod, m.is_pollution, m.sluice_gate_status, m.timestamp
        FROM ml_results m
        JOIN raw_sensor_data r ON m.raw_id = r.id
        ORDER BY m.id DESC LIMIT 1
    '''
    cursor.execute(query)
    row = cursor.fetchone()
    conn.close()

    if row:
        return {
            "ph": row[0],
            "cod": row[1],
            "alert": bool(row[2]),
            "sluice_gate": bool(row[3]),
            "timestamp": row[4]
        }
    # 如果資料庫是空的，回傳假資料避免網頁報錯
    return {"ph": 0, "cod": 0, "alert": False, "sluice_gate": False, "timestamp": "Wait..."}

def run_server():
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="error")

# ==========================================
# 3. 啟動系統 (背景執行 Server)
# ==========================================
try:
    public_url = ngrok.connect(8000).public_url
    print(f"🎉 API 已上線！網頁請用此網址: {public_url}")

    t = threading.Thread(target=run_server, daemon=True)
    t.start()
    time.sleep(3) # 等伺服器開好

    # ==========================================
    # 4. 模擬角色 A：現場感測器 (只負責產生數據 -> 上傳)
    # ==========================================
    def sensor_simulator():
        print("📡 [感測器] 啟動中...")
        while True:
            # 隨機產生數據
            is_bad = random.random() < 0.2
            ph = round(random.uniform(3.0, 5.0) if is_bad else random.uniform(6.5, 8.5), 2)
            cod = round(random.uniform(120, 200) if is_bad else random.uniform(20, 60), 1)

            payload = {
                "device_id": "Station_A",
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "ph": ph,
                "cod": cod
            }
            try:
                # 傳送到 API 1
                requests.post("http://127.0.0.1:8000/api/sensor/upload", json=payload)
                print(f"📤 [感測器] 上傳數據: pH={ph}, COD={cod}")
            except:
                pass
            time.sleep(5) # 每 2 秒傳一次

    # ==========================================
    # 5. 模擬角色 B：ML 運算中心 (負責抓資料 -> 判斷 -> 存回)
    # ==========================================
    def ml_worker_simulator():
        print("🧠 [ML模型] 待命中...")
        last_processed_id = -1

        while True:
            try:
                # 步驟 A: 從 API 2 抓取最新資料
                response = requests.get("http://127.0.0.1:8000/api/ml/fetch_latest")
                data = response.json()

                if "error" not in data:
                    raw_id = data['id']

                    # 避免重複處理同一筆資料
                    if raw_id != last_processed_id:
                        # 步驟 B: 進行預測 (模擬 ML 邏輯)
                        # 這裡就是你的機器學習模型發揮作用的地方
                        is_pollution = data['cod'] > 100 or data['ph'] < 4.0

                        # 步驟 C: 將結果透過 API 3 傳回資料庫
                        result_payload = {
                            "timestamp": datetime.now().strftime("%H:%M:%S"),
                            "raw_id": raw_id,
                            "is_pollution": is_pollution,
                            "sluice_gate_status": is_pollution # 如果汙染就開閘
                        }
                        requests.post("http://127.0.0.1:8000/api/ml/submit_result", json=result_payload)

                        action = "開閘排洪" if is_pollution else "正常監控"
                        print(f"✅ [ML模型] 完成分析 (ID: {raw_id}) -> 判斷: {action}")

                        last_processed_id = raw_id
            except Exception as e:
                print(e)

            time.sleep(1) # ML 模型每秒檢查一次有沒有新資料

    # 啟動模擬執行緒
    threading.Thread(target=sensor_simulator, daemon=True).start()
    threading.Thread(target=ml_worker_simulator, daemon=True).start()

    # 保持主程式運作
    while True:
        time.sleep(1)

except KeyboardInterrupt:
    print("系統停止")
