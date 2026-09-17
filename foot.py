import os
import sys
import requests
import json
import time
from datetime import datetime
import pytz

# =====================================================================
# НАСТРОЙКИ
# =====================================================================
BOT_TOKEN = os.getenv('BOT_TOKEN')
if not BOT_TOKEN:
    BOT_TOKEN = os.getenv('BOT_TOKEN_PROGNOZ')

CHAT_ID = os.getenv('CHAT_ID_FOOTBALL')
if not CHAT_ID:
    CHAT_ID = os.getenv('CHAT_ID')

if not BOT_TOKEN or not CHAT_ID:
    print("❌ Ошибка: BOT_TOKEN или CHAT_ID не заданы!", flush=True)
    sys.exit(1)

print(f"✅ BOT_TOKEN: {BOT_TOKEN[:5]}...", flush=True)
print(f"✅ CHAT_ID: {CHAT_ID}", flush=True)

MOSCOW_TZ = pytz.timezone('Europe/Moscow')
BASE_URL = "https://1xlite-36553.pro"
API = f"https://api.telegram.org/bot{BOT_TOKEN}"

# =====================================================================
# ТОП-ЛИГИ
# =====================================================================
LEAGUES = {
    "🏆 Лига Чемпионов УЕФА":            118587,
    "🏆 Лига Европы УЕФА":               118593,
    "🏆 Лига Конференций УЕФА":          2252762,
    "🏴 Чемпионат Англии. АПЛ":          88637,
    "🇩🇪 Чемпионат Германии. Бундеслига": 96463,
    "🇪🇸 Чемпионат Испании. Примера":     127733,
    "🇮🇹 Чемпионат Италии. Серия А":      110163,
    "🇫🇷 Чемпионат Франции. Лига 1":      12821,
    "🇷🇺 Чемпионат России. РПЛ":          225733,
}

# =====================================================================
# ПОРОГИ
# =====================================================================
MIN_XG_DIFF    = 1.0
MIN_SHOTS_DIFF = 3
MIN_ATT_DIFF   = 20
MAX_MINUTE     = 80
UPDATE_INTERVAL = 60
ANTISPAM_SEC   = 600

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": f"{BASE_URL}/ru/live/football",
    "Cookie": "platform_type=desktop; lng=ru; cookies_agree_type=3; tzo=3; is12h=0; "
              "auid=uaJb+WqQFLEHP+WbAwdUAg==; "
              "SESSION=ae9f1b4deac37d41be6873b1acf03cf4"
}

print("✅ Настройки загружены", flush=True)

# =====================================================================
# СОСТОЯНИЕ
# =====================================================================
sent_signals = {}

# =====================================================================
# API
# =====================================================================
def get_league_games(league_id):
    """Возвращает все матчи лиги с уже встроенной статистикой."""
    url = f"{BASE_URL}/service-api/LiveFeed/GetGameZip"
    params = {
        "id": league_id,
        "isSubGames": "true",
        "GroupEvents": "true",
        "countevents": 250,
        "grMode": 4,
        "country": 1,
        "marketType": 1,
        "isNewBuilder": "true"
    }
    try:
        r = requests.get(url, headers=HEADERS, params=params, timeout=10)
        if r.status_code != 200:
            print(f"⚠️ [{league_id}] HTTP {r.status_code}", flush=True)
            return []
        data = r.json()
        games = data.get("Value", [])
        if not isinstance(games, list):
            games = [games]
        games = [g for g in games if isinstance(g, dict)]
        return games
    except Exception as e:
        print(f"❌ [{league_id}] {e}", flush=True)
        return []

# =====================================================================
# АНАЛИЗ
# =====================================================================
def parse_stats(game):
    """Извлекает статистику из tabloStats."""
    stats = {}
    tablo = game.get("tabloStats") or {}
    for key, items in tablo.items():
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                name = item.get("name")
                if name:
                    stats[name] = item
    return stats

def analyze_game(game):
    """Возвращает dict с сигналом или None."""
    if not isinstance(game, dict):
        return None
    if game.get("isFinished"):
        return None
    if not game.get("tabloStats"):
        return None

    o1 = (game.get("opponent1") or {}).get("fullName", "?")
    o2 = (game.get("opponent2") or {}).get("fullName", "?")
    score = (game.get("scores") or {}).get("fullScore", "0-0")
    period = game.get("currentPeriodName", "")
    game_id = game.get("id")

    timer = game.get("timer") or {}
    time_sec = timer.get("timeSec", 0)
    minute = time_sec // 60

    stats = parse_stats(game)
    xg = stats.get("xG", {})
    shots = stats.get("Удары в створ", {})
    attacks = stats.get("Опасные атаки", {})

    try:
        xg1 = float(xg.get("s1", 0))
        xg2 = float(xg.get("s2", 0))
        shots1 = int(float(shots.get("s1", 0)))
        shots2 = int(float(shots.get("s2", 0)))
        att1 = int(float(attacks.get("s1", 0)))
        att2 = int(float(attacks.get("s2", 0)))
    except (ValueError, TypeError):
        return None

    xg_diff    = abs(xg1 - xg2)
    shots_diff = abs(shots1 - shots2)
    att_diff   = abs(att1 - att2)

    signal_type = None
    if minute <= MAX_MINUTE:
        if xg_diff >= 2.0 and shots_diff >= 3:
            signal_type = "🔥🔥 СИЛЬНЫЙ СИГНАЛ"
        elif xg_diff >= MIN_XG_DIFF and shots_diff >= MIN_SHOTS_DIFF:
            signal_type = "🟢 СИГНАЛ НА ГОЛ"
        elif xg_diff >= MIN_XG_DIFF and att_diff >= MIN_ATT_DIFF:
            signal_type = "🟡 ДАВЛЕНИЕ"

    if not signal_type:
        return None

    if xg1 > xg2:
        dominant = o1
        weak = o2
    else:
        dominant = o2
        weak = o1

    return {
        "game_id":   game_id,
        "match":     f"{o1} — {o2}",
        "score":     score,
        "minute":    minute,
        "period":    period,
        "xg":        f"{xg1:.2f} — {xg2:.2f}",
        "xg_diff":   round(xg_diff, 2),
        "shots":     f"{shots1} — {shots2}",
        "attacks":   f"{att1} — {att2}",
        "dominant":  dominant,
        "weak":      weak,
        "signal":    signal_type,
    }

# =====================================================================
# TELEGRAM
# =====================================================================
def send_telegram(text):
    try:
        r = requests.post(API + "/sendMessage",
                          json={"chat_id": CHAT_ID,
                                "text": text,
                                "parse_mode": "HTML"})
        return r.status_code == 200
    except Exception as e:
        print(f"❌ TG: {e}", flush=True)
        return False

def format_signal(s):
    return (
        f"{s['signal']}\n"
        f"⚽ <b>{s['match']}</b>\n"
        f"📊 Счёт: <b>{s['score']}</b> | ⏱ {s['minute']}'\n"
        f"🎯 xG: {s['xg']}  (разница {s['xg_diff']})\n"
        f"🥅 Удары в створ: {s['shots']}\n"
        f"⚔️ Опасные атаки: {s['attacks']}\n"
        f"👉 Доминирует: <b>{s['dominant']}</b>"
    )

# =====================================================================
# ОСНОВНОЙ ЦИКЛ
# =====================================================================
def monitor():
    global sent_signals

    print(f"🔄 Цикл: {datetime.now(MOSCOW_TZ).strftime('%H:%M:%S')}", flush=True)

    total_games = 0
    total_signals = 0

    for league_name, league_id in LEAGUES.items():
        games = get_league_games(league_id)
        if not games:
            continue

        total_games += len(games)
        print(f"  📋 {league_name}: {len(games)} матчей", flush=True)

        for game in games:
            result = analyze_game(game)
            if not result:
                continue

            gid = result["game_id"]
            now = int(time.time())

            prev = sent_signals.get(gid)
            if prev and (now - prev["ts"]) < ANTISPAM_SEC:
                if abs(prev["xg_diff"] - result["xg_diff"]) < 0.3:
                    continue

            text = format_signal(result)
            if send_telegram(text):
                sent_signals[gid] = {"xg_diff": result["xg_diff"], "ts": now}
                total_signals += 1
                print(f"    📤 {result['match']} | {result['signal']}", flush=True)
                time.sleep(1)

        time.sleep(2)

    print(f"✅ Итого: {total_games} матчей, {total_signals} сигналов", flush=True)

    now = int(time.time())
    sent_signals = {k: v for k, v in sent_signals.items() if now - v["ts"] < 1800}

# =====================================================================
# MAIN
# =====================================================================
def main():
    print("🚀 БОТ-МОНИТОР ФУТБОЛЬНЫХ АНОМАЛИЙ ЗАПУЩЕН", flush=True)
    print(f"⏱️ Интервал: {UPDATE_INTERVAL} сек", flush=True)
    print(f"📋 Лиг: {len(LEAGUES)}", flush=True)
    print(f"🎯 Пороги: xG diff ≥ {MIN_XG_DIFF}, удары ≥ {MIN_SHOTS_DIFF}, "
          f"атаки ≥ {MIN_ATT_DIFF}, мин ≤ {MAX_MINUTE}", flush=True)
    print("=" * 60, flush=True)

    while True:
        try:
            monitor()
            time.sleep(UPDATE_INTERVAL)
        except KeyboardInterrupt:
            print("⏹️ Остановлено", flush=True)
            break
        except Exception as e:
            print(f"❌ Критическая ошибка: {e}", flush=True)
            import traceback
            traceback.print_exc()
            time.sleep(30)

if __name__ == "__main__":
    main()