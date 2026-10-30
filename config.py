import os
import pytz
import sys

BOT_TOKEN = os.getenv('BOT_TOKEN') or os.getenv('BOT_TOKEN_PROGNOZ')
CHAT_ID = os.getenv('CHAT_ID_FOOTBALL') or os.getenv('CHAT_ID')

if not BOT_TOKEN or not CHAT_ID:
    print("❌ BOT_TOKEN или CHAT_ID не заданы", flush=True)
    sys.exit(1)

print(f"✅ BOT_TOKEN: {BOT_TOKEN[:5]}...", flush=True)
print(f"✅ CHAT_ID: {CHAT_ID}", flush=True)

MOSCOW_TZ = pytz.timezone('Europe/Moscow')
BASE_URL = "https://1xlite-1679.pro"
API = f"https://api.telegram.org/bot{BOT_TOKEN}"

LEAGUE_IDS = {
    88637: "🏴 Чемпионат Англии. АПЛ", 96463: "🇩🇪 Чемпионат Германии. Бундеслига",
    127733: "🇪🇸 Чемпионат Испании. Примера", 110163: "🇮🇹 Чемпионат Италии. Серия А",
    12821: "🇫🇷 Чемпионат Франции. Лига 1", 225733: "🇷🇺 Чемпионат России. РПЛ",
    118587: "🏆 Лига Чемпионов УЕФА", 118593: "🏆 Лига Европы УЕФА",
    2252762: "🏆 Лига Конференций УЕФА",
}

S1_XG_DIFF = 1.3
S1_SHOTS_ON_DIFF = 3
S1_MIN_ODD = 1.4
S2_SHOTS_DIFF = 8
S2_SHOTS_ON_DIFF = 3
S2_MIN_ODD = 1.4
S3_CORNERS_DIFF = 4
S3_ATT_DIFF = 20
S3_MIN_ODD = 1.4
S5_ATT_DIFF = 30
S5_MIN_ODD = 1.4
S6_XG_DIFF = 1.0
S6_CORNERS_DIFF = 3
S6_MIN_ODD = 1.4

DROP_PCT = -10.0
DROP_WINDOW = 180
DROP_ANTISPAM = 900
ENABLE_1X2_DROP = False
MAX_MINUTE = 80
UPDATE_INTERVAL = 60
ANTISPAM_SEC = 900
GOAL_COOLDOWN_SEC = 600
SLEEP_HOUR_START = 1
SLEEP_HOUR_END = 12
SCHEDULE_REFRESH_SEC = 3600

RUSCORE_URL = "https://api-statistics.ruscore.ru/v1/events"
RUSCORE_PARAMS = {"app_id": "ruscore", "api_key": os.getenv("RUSCORE_API_KEY", ""), "lang": "ru", "tz": "Europe/Moscow"}
RUSCORE_LEAGUES_FILTER = ["премьер-лига", "бундеслига", "ла лига", "серия а", "лига 1", "россии", "рпл", "лига чемпионов", "лига европы", "лига конференций"]

CHECK_FIRST_AFTER = 180
CHECK_REPEAT_AFTER = 180
CHECK_MAX_ATTEMPTS = 40
RESULTS_FILE = os.getenv("FOOTBALL_RESULTS_FILE", "football_results.jsonl")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 YaBrowser/26.8.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*", "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Content-Type": "application/json", "Referer": f"{BASE_URL}/ru/live", "Origin": BASE_URL, "is-srv": "false",
    "x-app-n": "__BETTING_APP__", "x-hd": os.getenv("LIVE_X_HD", ""), "x-requested-with": "XMLHttpRequest",
    "x-svc-source": "__BETTING_APP__", "Cookie": os.getenv("LIVE_API_COOKIE", ""),
}

RUSCORE_HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "*/*", "Origin": "https://ruscore.ru", "Referer": "https://ruscore.ru/"}
