import os
import sys
import requests
import json
import time
from datetime import datetime, timedelta
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

# Проверка результата
CHECK_FIRST_AFTER  = 1800
CHECK_REPEAT_AFTER = 1800
CHECK_MAX_ATTEMPTS = 4

# Ночной режим (МСК): спит с 01:00 до 12:00
SLEEP_HOUR_START = 1
SLEEP_HOUR_END   = 12

# Расписание
SCHEDULE_REFRESH_SEC = 3600    # обновление раз в час

RUSCORE_URL = "https://api-statistics.ruscore.ru/v1/events"
RUSCORE_PARAMS = {
    "app_id": "ruscore",
    "api_key": "yAUBmZp9XJgh3US6bN1GZKtAYsFRKET6",
    "lang": "ru",
    "tz": "Europe/Moscow"
}

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
pending_checks = {}

# Расписание
schedule_windows = []       # список (start, end) — окна матчей
schedule_updated_at = None  # когда обновляли

# =====================================================================
# АКТИВНОЕ ВРЕМЯ
# =====================================================================
def is_active_time():
    """Активное время: 12:00 – 00:59 МСК."""
    hour = datetime.now(MOSCOW_TZ).hour
    if SLEEP_HOUR_START <= hour < SLEEP_HOUR_END:
        return False
    return True

# =====================================================================
# API 1WIN
# =====================================================================
def get_league_games(league_id):
    url = f"{BASE_URL}/service-api/LiveFeed/GetGameZip"
    params = {
        "id": league_id, "isSubGames": "true", "GroupEvents": "true",
        "countevents": 250, "grMode": 4, "country": 1,
        "marketType": 1, "isNewBuilder": "true"
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

    dominant = o1 if xg1 > xg2 else o2

    return {
        "game_id":   game_id,
        "team1":     o1,
        "team2":     o2,
        "match":     f"{o1} — {o2}",
        "score":     score,
        "minute":    minute,
        "period":    period,
        "xg":        f"{xg1:.2f} — {xg2:.2f}",
        "xg_diff":   round(xg_diff, 2),
        "shots":     f"{shots1} — {shots2}",
        "attacks":   f"{att1} — {att2}",
        "dominant":  dominant,
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
        if r.status_code == 200:
            return r.json()["result"]["message_id"]
    except Exception as e:
        print(f"❌ TG send: {e}", flush=True)
    return None

def edit_telegram(message_id, text):
    try:
        r = requests.post(API + "/editMessageText",
                          json={"chat_id": CHAT_ID,
                                "message_id": message_id,
                                "text": text,
                                "parse_mode": "HTML"})
        return r.status_code == 200
    except Exception as e:
        print(f"❌ TG edit: {e}", flush=True)
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

def format_with_result(base_text, result_line):
    return f"{base_text}\n\n{result_line}"

# =====================================================================
# RUSCORE — ПРОВЕРКА РЕЗУЛЬТАТОВ
# =====================================================================
def fetch_ruscore_events(date_str):
    params = dict(RUSCORE_PARAMS)
    params["date"] = date_str
    try:
        r = requests.get(RUSCORE_URL, params=params, timeout=15)
        if r.status_code != 200:
            print(f"⚠️ ruscore HTTP {r.status_code}", flush=True)
            return []
        data = r.json()
        events = []
        for block in data.get("data", []):
            for ev in block.get("events", []):
                ev["_league"] = block.get("name", "")
                events.append(ev)
        return events
    except Exception as e:
        print(f"❌ ruscore: {e}", flush=True)
        return []

def normalize_name(s):
    if not s:
        return ""
    return (
        s.lower()
        .replace(" ", "").replace("-", "").replace("'", "")
        .replace("ё", "е").replace(".", "").strip()
    )

def find_match(events, team1, team2):
    n1 = normalize_name(team1)
    n2 = normalize_name(team2)
    for ev in events:
        h = normalize_name((ev.get("home") or {}).get("name", ""))
        a = normalize_name((ev.get("away") or {}).get("name", ""))
        if (n1 in h or h in n1) and (n2 in a or a in n2):
            return ev
        if (n1 in a or a in n1) and (n2 in h or h in n2):
            return ev
    return None

def parse_score_from_ruscore(ev):
    score_list = ev.get("score") or []
    for s in score_list:
        if s.get("type") == "overall":
            h = s.get("home")
            a = s.get("away")
            if h == "" or a == "":
                return None, None
            try:
                return int(h), int(a)
            except (ValueError, TypeError):
                return None, None
    return None, None

def check_pending_results():
    global pending_checks
    if not pending_checks:
        return

    now = int(time.time())

    by_date = {}
    for gid, info in pending_checks.items():
        if now < info.get("check_after", 0):
            continue
        by_date.setdefault(info["date_str"], []).append(gid)

    for date_str, gids in by_date.items():
        events = fetch_ruscore_events(date_str)
        if not events:
            for gid in gids:
                pending_checks[gid]["check_after"] = now + CHECK_REPEAT_AFTER
            continue

        for gid in gids:
            info = pending_checks.get(gid)
            if not info:
                continue

            ev = find_match(events, info["team1"], info["team2"])
            if not ev:
                info["attempts"] = info.get("attempts", 0) + 1
                info["check_after"] = now + CHECK_REPEAT_AFTER
                if info["attempts"] >= CHECK_MAX_ATTEMPTS:
                    line = "❓ <b>РЕЗУЛЬТАТ НЕ НАЙДЕН</b>\n(матч не найден в ruscore)"
                    edit_telegram(info["message_id"],
                                  format_with_result(info["base_text"], line))
                    del pending_checks[gid]
                continue

            h_score, a_score = parse_score_from_ruscore(ev)
            status = (ev.get("status") or {}).get("label", "")

            if h_score is None:
                info["check_after"] = now + CHECK_REPEAT_AFTER
                continue

            old_s1 = info["old_s1"]
            old_s2 = info["old_s2"]

            goal_happened = (h_score != old_s1) or (a_score != old_s2)
            is_finished = status in ("finished", "ended")

            if goal_happened:
                elapsed = (now - info["signal_ts"]) // 60
                line = (
                    f"✅ <b>ЗАШЛО</b>\n"
                    f"📊 Было: {old_s1}-{old_s2} ({info['minute']}')\n"
                    f"📊 Стало: {h_score}-{a_score}\n"
                    f"⏱ Через ~{elapsed} мин"
                )
                edit_telegram(info["message_id"],
                              format_with_result(info["base_text"], line))
                print(f"✅ ЗАШЛО: {info['match']}", flush=True)
                del pending_checks[gid]
                continue

            if is_finished:
                line = (
                    f"❌ <b>НЕ ЗАШЛО</b>\n"
                    f"📊 Итог: {h_score}-{a_score}\n"
                    f"⏱ Матч завершён"
                )
                edit_telegram(info["message_id"],
                              format_with_result(info["base_text"], line))
                print(f"❌ НЕ ЗАШЛО: {info['match']}", flush=True)
                del pending_checks[gid]
                continue

            info["attempts"] = info.get("attempts", 0) + 1
            info["check_after"] = now + CHECK_REPEAT_AFTER

            if info["attempts"] >= CHECK_MAX_ATTEMPTS:
                line = (
                    f"⏱ <b>БЕЗ РЕЗУЛЬТАТА</b>\n"
                    f"📊 Счёт: {h_score}-{a_score}\n"
                    f"(проверено {info['attempts']} раз)"
                )
                edit_telegram(info["message_id"],
                              format_with_result(info["base_text"], line))
                del pending_checks[gid]

# =====================================================================
# РАСПИСАНИЕ
# =====================================================================
def get_today_schedule():
    """Возвращает список матчей на сегодня с временем начала."""
    today = datetime.now(MOSCOW_TZ).strftime("%Y-%m-%d")
    events = fetch_ruscore_events(today)

    schedule = []
    for ev in events:
        time_str = ev.get("time")
        if not time_str:
            continue
        try:
            dt = datetime.fromisoformat(time_str)
            # Приводим к МСК
            dt = dt.astimezone(MOSCOW_TZ)
            schedule.append({
                "time": dt,
                "match": f"{(ev.get('home') or {}).get('name')} — "
                         f"{(ev.get('away') or {}).get('name')}",
            })
        except (ValueError, TypeError):
            continue
    return schedule

def get_monitoring_windows(schedule):
    """Объединяет времена матчей в окна (start, end)."""
    if not schedule:
        return []

    times = sorted([s["time"] for s in schedule])
    windows = [(t, t + timedelta(hours=2)) for t in times]

    merged = [windows[0]]
    for start, end in windows[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged

def refresh_schedule_if_needed():
    """Обновляет расписание раз в час."""
    global schedule_windows, schedule_updated_at
    now = datetime.now(MOSCOW_TZ)

    if schedule_updated_at and (now - schedule_updated_at).total_seconds() < SCHEDULE_REFRESH_SEC:
        return

    print(f"📅 Обновляем расписание...", flush=True)
    schedule = get_today_schedule()
    schedule_windows = get_monitoring_windows(schedule)
    schedule_updated_at = now

    if schedule_windows:
        print(f"📅 Найдено {len(schedule_windows)} окон:", flush=True)
        for start, end in schedule_windows:
            print(f"   {start.strftime('%H:%M')} – {end.strftime('%H:%M')} МСК", flush=True)
    else:
        print("📅 Матчей в топ-лигах сегодня нет", flush=True)

def is_match_time():
    """Проверяет, есть ли матч прямо сейчас."""
    if not schedule_windows:
        return False
    now = datetime.now(MOSCOW_TZ)
    for start, end in schedule_windows:
        if start <= now <= end:
            return True
    return False

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
            msg_id = send_telegram(text)

            if msg_id:
                sent_signals[gid] = {"xg_diff": result["xg_diff"], "ts": now}
                total_signals += 1
                print(f"    📤 {result['match']} | {result['signal']}", flush=True)

                today = datetime.now(MOSCOW_TZ).strftime("%Y-%m-%d")
                try:
                    s1, s2 = map(int, result["score"].split("-"))
                except ValueError:
                    s1, s2 = 0, 0

                if gid not in pending_checks:
                    pending_checks[gid] = {
                        "team1":      result["team1"],
                        "team2":      result["team2"],
                        "match":      result["match"],
                        "date_str":   today,
                        "old_s1":     s1,
                        "old_s2":     s2,
                        "minute":     result["minute"],
                        "signal_ts":  now,
                        "message_id": msg_id,
                        "base_text":  text,
                        "check_after": now + CHECK_FIRST_AFTER,
                        "attempts":   0,
                    }

                time.sleep(1)

        time.sleep(2)

    print(f"✅ Итого: {total_games} матчей, {total_signals} сигналов, "
          f"на проверке: {len(pending_checks)}", flush=True)

    now = int(time.time())
    sent_signals = {k: v for k, v in sent_signals.items() if now - v["ts"] < 1800}

# =====================================================================
# MAIN
# =====================================================================
def main():
    print("🚀 БОТ-МОНИТОР ФУТБОЛЬНЫХ АНОМАЛИЙ ЗАПУЩЕН", flush=True)
    print(f"📋 Лиг: {len(LEAGUES)}", flush=True)
    print(f"🎯 Пороги: xG diff ≥ {MIN_XG_DIFF}, удары ≥ {MIN_SHOTS_DIFF}, "
          f"атаки ≥ {MIN_ATT_DIFF}, мин ≤ {MAX_MINUTE}", flush=True)
    print(f"🔍 Проверка: через {CHECK_FIRST_AFTER//60} мин, "
          f"повтор каждые {CHECK_REPEAT_AFTER//60} мин, "
          f"макс {CHECK_MAX_ATTEMPTS} попыток", flush=True)
    print(f"😴 Ночной режим: с {SLEEP_HOUR_START:02d}:00 до {SLEEP_HOUR_END:02d}:00 МСК", flush=True)
    print(f"📅 Расписание: обновление раз в час", flush=True)
    print("=" * 60, flush=True)

    while True:
        try:
            now = datetime.now(MOSCOW_TZ)
            now_str = now.strftime('%H:%M')

            # Ночью — полный сон, НИЧЕГО не делаем
            if not is_active_time():
                print(f"😴 Ночь ({now_str} МСК) — спим до 12:00", flush=True)
                time.sleep(600)
                continue

            # Днём — обновляем расписание раз в час
            refresh_schedule_if_needed()

            # Матчи идут?
            if is_match_time():
                monitor()
                check_pending_results()
                time.sleep(UPDATE_INTERVAL)
            else:
                # Матчей нет — только проверки сигналов
                print(f"💤 Матчей нет ({now_str} МСК) — ждём", flush=True)
                check_pending_results()
                time.sleep(600)

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