import os
import sys
import requests
import json
import time
from datetime import datetime, timedelta
from collections import deque
import pytz

# =====================================================================
# НАСТРОЙКИ
# =====================================================================
BOT_TOKEN = os.getenv('BOT_TOKEN') or os.getenv('BOT_TOKEN_PROGNOZ')
CHAT_ID = os.getenv('CHAT_ID_FOOTBALL') or os.getenv('CHAT_ID')

if not BOT_TOKEN or not CHAT_ID:
    print("❌ BOT_TOKEN или CHAT_ID не заданы", flush=True)
    sys.exit(1)

print(f"✅ BOT_TOKEN: {BOT_TOKEN[:5]}...", flush=True)
print(f"✅ CHAT_ID: {CHAT_ID}", flush=True)

MOSCOW_TZ = pytz.timezone('Europe/Moscow')
BASE_URL = "https://1xlite-8150.pro"
API = f"https://api.telegram.org/bot{BOT_TOKEN}"

# =====================================================================
# ЛИГИ
# =====================================================================
LEAGUE_IDS = {
    88637:   "🏴 Чемпионат Англии. АПЛ",
    96463:   "🇩🇪 Чемпионат Германии. Бундеслига",
    127733:  "🇪🇸 Чемпионат Испании. Примера",
    110163:  "🇮🇹 Чемпионат Италии. Серия А",
    12821:   "🇫🇷 Чемпионат Франции. Лига 1",
    225733:  "🇷🇺 Чемпионат России. РПЛ",
    118587:  "🏆 Лига Чемпионов УЕФА",
    118593:  "🏆 Лига Европы УЕФА",
    2252762: "🏆 Лига Конференций УЕФА",
}

# =====================================================================
# ПОРОГИ СТРАТЕГИЙ
# =====================================================================
S1_XG_DIFF       = 1.3
S1_SHOTS_ON_DIFF = 3
S1_MIN_ODD       = 1.4

S2_SHOTS_DIFF    = 8
S2_SHOTS_ON_DIFF = 3
S2_MIN_ODD       = 1.4

S3_CORNERS_DIFF  = 4
S3_ATT_DIFF      = 20
S3_MIN_ODD       = 1.4

S5_ATT_DIFF      = 30
S5_MIN_ODD       = 1.4

S6_XG_DIFF       = 1.0
S6_CORNERS_DIFF  = 3
S6_MIN_ODD       = 1.4

# Дроп 1X2
DROP_PCT      = -10.0
DROP_WINDOW   = 180
DROP_ANTISPAM = 900
ENABLE_1X2_DROP = False  # Цель OLD — следующий гол, поэтому отдельные ставки по дропу отключены.

# Общие
MAX_MINUTE        = 80
UPDATE_INTERVAL   = 60
ANTISPAM_SEC      = 900
GOAL_COOLDOWN_SEC = 600

SLEEP_HOUR_START = 1
SLEEP_HOUR_END   = 12
SCHEDULE_REFRESH_SEC = 3600

RUSCORE_URL = "https://api-statistics.ruscore.ru/v1/events"
RUSCORE_PARAMS = {
    "app_id": "ruscore",
    "api_key": os.getenv("RUSCORE_API_KEY", ""),
    "lang": "ru",
    "tz": "Europe/Moscow"
}
RUSCORE_LEAGUES_FILTER = [
    "премьер-лига", "бундеслига", "ла лига", "серия а", "лига 1",
    "россии", "рпл", "лига чемпионов", "лига европы", "лига конференций",
]

CHECK_FIRST_AFTER  = 180
CHECK_REPEAT_AFTER = 180
CHECK_MAX_ATTEMPTS = 40
RESULTS_FILE = os.getenv("FOOTBALL_RESULTS_FILE", "football_results.jsonl")

# =====================================================================
# ЗАГОЛОВКИ
# =====================================================================
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 YaBrowser/26.8.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Content-Type": "application/json",
    "Referer": f"{BASE_URL}/ru/live",
    "Origin": BASE_URL,
    "is-srv": "false",
    "priority": "u=1, i",
    "sec-ch-ua": '"Not;A=Brand";v="8", "Chromium";v="150", "YaBrowser";v="26.8", "Yowser";v="2.5"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "x-app-n": "__BETTING_APP__",
    "x-hd": os.getenv("LIVE_X_HD", ""),
    "x-requested-with": "XMLHttpRequest",
    "x-svc-source": "__BETTING_APP__",
    "Cookie": os.getenv("LIVE_API_COOKIE", ""),
}

RUSCORE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 YaBrowser/26.8.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Origin": "https://ruscore.ru",
    "Referer": "https://ruscore.ru/",
    "sec-ch-ua": '"Not;A=Brand";v="8", "Chromium";v="150", "YaBrowser";v="26.8", "Yowser";v="2.5"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-site",
}

if not os.getenv("RUSCORE_API_KEY"):
    print("⚠️ Не задан RUSCORE_API_KEY: расписание и проверка итогов через Ruscore не заработают.", flush=True)
if not os.getenv("LIVE_API_COOKIE") or not os.getenv("LIVE_X_HD"):
    print("⚠️ Проверь LIVE_API_COOKIE и LIVE_X_HD: они могут требоваться live API.", flush=True)
print("✅ Настройки загружены", flush=True)

# =====================================================================
# СОСТОЯНИЕ
# =====================================================================
sent_signals = {}
pending_checks = {}
last_scores = {}
odds_history = {}        # {gid: deque([{ts, odds}, ...])}
sent_drops = {}          # {gid: ts}
schedule_windows = []
schedule_updated_at = None
recent_snapshots = {}    # {game_id: deque([{"ts": ..., "p": {...}}, ...])}


def log_result_record(record):
    """Сохраняет сигналы и результаты в JSONL для честного подсчёта статистики."""
    try:
        with open(RESULTS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except Exception as e:
        print(f"⚠️ Не удалось записать {RESULTS_FILE}: {e}", flush=True)

# =====================================================================
# ВРЕМЯ
# =====================================================================
def is_active_time():
    h = datetime.now(MOSCOW_TZ).hour
    return not (SLEEP_HOUR_START <= h < SLEEP_HOUR_END)

# =====================================================================
# API
# =====================================================================
def get_live_games():
    url = f"{BASE_URL}/service-api/main-live-feed/v3/games1x2"
    params = {"cfView": 3, "count": 40, "fcountry": 1,
              "gr": 2336, "grMode": 4, "lng": "ru", "ref": 1}
    try:
        r = requests.get(url, headers=HEADERS, params=params, timeout=15)
        print(f"   🔎 HTTP {r.status_code}", flush=True)
        if r.status_code != 200:
            return []
        data = r.json()
        if not isinstance(data, list):
            return []
        return [g for g in data if isinstance(g, dict)]
    except Exception as e:
        print(f"   ❌ {e}", flush=True)
        return []

# =====================================================================
# ПАРСИНГ СТАТИСТИКИ
# =====================================================================
def parse_stats(game):
    stats = {}
    tablo = ((game.get("scores") or {}).get("tabloStats")) or {}
    for key, items in tablo.items():
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and item.get("name"):
                    stats[item["name"]] = item
    return stats

def sv(stats, name, side="s1"):
    d = stats.get(name, {})
    try:
        return float(d.get(side, 0) or 0)
    except (ValueError, TypeError):
        return 0.0

# =====================================================================
# ПАРСИНГ КЭФОВ 1X2 (только для дропа)
# =====================================================================
def get_1x2_odds(game):
    """Только 1X2: П1, X, П2."""
    odds = {}
    for grp in (game.get("eventGroups") or []):
        if grp.get("groupId") != 1:
            continue
        for e in (grp.get("events") or []):
            if not isinstance(e, list) or not e:
                continue
            item = e[0]
            if not isinstance(item, dict):
                continue
            t, c = item.get("T"), item.get("C")
            if t == 1:   odds["П1"] = c
            elif t == 2: odds["X"] = c
            elif t == 3: odds["П2"] = c
        break
    return odds

def get_odd_total(game, total_goals):
    """Возвращает числовой коэффициент ТБ на следующий гол (текущий тотал + 0.5)."""
    target = float(total_goals) + 0.5
    for grp in (game.get("centralBlockEventGroups") or []):
        if not isinstance(grp, dict) or grp.get("groupId") != 17:
            continue
        events = grp.get("events") or []
        for event_list in events:
            if not isinstance(event_list, list):
                continue
            for item in event_list:
                if not isinstance(item, dict) or item.get("type") != 9:
                    continue
                try:
                    parameter = float(item.get("parameter"))
                    odd = float(item.get("cf"))
                except (TypeError, ValueError):
                    continue
                if abs(parameter - target) < 0.001 and odd > 1.0:
                    return odd
    return None

# =====================================================================
# ДРОП 1X2
# =====================================================================
def save_odds(gid, now_ts, odds):
    if gid not in odds_history:
        odds_history[gid] = deque(maxlen=30)
    odds_history[gid].append({"ts": now_ts, "odds": odds})

def check_drops(gid, now_ts):
    """Проверяет дроп П1/X/П2."""
    if gid not in odds_history or len(odds_history[gid]) < 2:
        return None

    cur = odds_history[gid][-1]["odds"]

    prev = None
    for h in reversed(list(odds_history[gid])[:-1]):
        if now_ts - h["ts"] >= DROP_WINDOW:
            prev = h
            break

    if prev is None:
        return None

    prev_odds = prev["odds"]
    res = []

    for key in ("П1", "X", "П2"):
        c = cur.get(key)
        p = prev_odds.get(key)
        if not c or not p:
            continue
        try:
            change = (float(c) - float(p)) / float(p) * 100
        except (ValueError, TypeError, ZeroDivisionError):
            continue
        if change <= DROP_PCT:
            res.append({
                "market": key,
                "from": p,
                "to": c,
                "change_pct": round(change, 1),
                "window": now_ts - prev["ts"],
            })

    if not res:
        return None
    res.sort(key=lambda x: x["change_pct"])
    return res

def drop_to_bet(market, p):
    """П1/X/П2 → конкретная ставка."""
    if market == "П1":
        return ("ИТ1 Б 0.5 (хозяева забьют)",
                "Дроп П1 → хозяева побеждают → забьют")
    if market == "П2":
        return ("ИТ2 Б 0.5 (гости забьют)",
                "Дроп П2 → гости побеждают → забьют")
    if market == "X":
        return ("Обе забьют (ОЗ)",
                "Дроп X → ждут ничью → часто обе забивают")
    return (market, "—")

def format_drop_signal(p, drops):
    lines = [
        "📉 <b>ДРОП 1X2</b>",
        p["league"],
        f"⚽ <b>{p['match']}</b>",
        f"📊 Счёт: <b>{p['score']}</b> | ⏱ {p['minute']}'",
        "",
    ]
    for d in drops[:3]:
        lines.append(f"🔻 <b>{d['market']}</b>: {d['from']} → {d['to']} "
                     f"({d['change_pct']}% за {d['window']}с)")

    best = drops[0]
    bet, reason = drop_to_bet(best["market"], p)
    lines.append("")
    lines.append(f"💡 <b>Ставка: {bet}</b>")
    lines.append(f"<i>{reason}</i>")
    lines.append(f"📌 Кэф 1X2 сейчас: {best['to']}")
    return "\n".join(lines)

# =====================================================================
# TELEGRAM
# =====================================================================
def send_telegram(text):
    try:
        r = requests.post(API + "/sendMessage",
                          json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"})
        if r.status_code == 200:
            return r.json()["result"]["message_id"]
    except Exception as e:
        print(f"❌ TG send: {e}", flush=True)
    return None

def edit_telegram(message_id, text):
    try:
        r = requests.post(API + "/editMessageText",
                          json={"chat_id": CHAT_ID, "message_id": message_id,
                                "text": text, "parse_mode": "HTML"})
        return r.status_code == 200
    except Exception as e:
        print(f"❌ TG edit: {e}", flush=True)
        return False

def format_with_result(base_text, result_line):
    return f"{base_text}\n\n{result_line}"

# =====================================================================
# БАЗОВЫЙ ПАРСИНГ МАТЧА
# =====================================================================
def parse_game(game):
    if not isinstance(game, dict):
        return None
    if (game.get("sport") or {}).get("id") != 1:
        return None

    liga_id = (game.get("liga") or {}).get("id")
    if liga_id not in LEAGUE_IDS:
        return None

    scores = game.get("scores") or {}
    if (scores.get("currentPeriodName") == "Игра завершена" or
            scores.get("statusLineStr", "") == ""):
        if not scores.get("timer", {}).get("timeRun"):
            return None

    minute = (scores.get("timer") or {}).get("timeSec", 0) // 60
    score = scores.get("fullScore", "0-0")
    try:
        s1, s2 = map(int, score.split("-"))
    except ValueError:
        s1, s2 = 0, 0

    stats = parse_stats(game)

    xg1 = sv(stats, "xG", "s1")
    xg2 = sv(stats, "xG", "s2")
    shots_on1 = int(sv(stats, "Удары в створ", "s1"))
    shots_on2 = int(sv(stats, "Удары в створ", "s2"))
    shots_off1 = int(sv(stats, "Удары в сторону ворот", "s1"))
    shots_off2 = int(sv(stats, "Удары в сторону ворот", "s2"))
    shots_all1 = shots_on1 + shots_off1
    shots_all2 = shots_on2 + shots_off2
    att1 = int(sv(stats, "Опасные атаки", "s1"))
    att2 = int(sv(stats, "Опасные атаки", "s2"))
    corners1 = int(sv(stats, "Угловые", "s1"))
    corners2 = int(sv(stats, "Угловые", "s2"))
    red1 = int(sv(stats, "Красные карточки", "s1"))
    red2 = int(sv(stats, "Красные карточки", "s2"))
    yellow1 = int(sv(stats, "Желтые карточки", "s1"))
    yellow2 = int(sv(stats, "Желтые карточки", "s2"))
    subs1 = int(sv(stats, "Замены", "s1"))
    subs2 = int(sv(stats, "Замены", "s2"))
    kp1 = int(sv(stats, "Ключевые передачи", "s1"))
    kp2 = int(sv(stats, "Ключевые передачи", "s2"))

    o1 = (game.get("opponent1") or {}).get("fullName", "?")
    o2 = (game.get("opponent2") or {}).get("fullName", "?")

    return {
        "game_id": game.get("id"),
        "liga_id": liga_id,
        "league": LEAGUE_IDS.get(liga_id, ""),
        "team1": o1, "team2": o2,
        "match": f"{o1} — {o2}",
        "minute": minute, "score": score,
        "s1": s1, "s2": s2,
        "xg1": xg1, "xg2": xg2,
        "shots_on1": shots_on1, "shots_on2": shots_on2,
        "shots_all1": shots_all1, "shots_all2": shots_all2,
        "att1": att1, "att2": att2,
        "corners1": corners1, "corners2": corners2,
        "red1": red1, "red2": red2,
        "yellow1": yellow1, "yellow2": yellow2,
        "subs1": subs1, "subs2": subs2,
        "kp1": kp1, "kp2": kp2,
    }

# =====================================================================
# ОБЩИЕ ФИЛЬТРЫ
# =====================================================================
def update_match_history(p, now_ts):
    """Сохраняет недавние снимки матча в памяти для оценки темпа."""
    gid = p.get("game_id")
    if gid is None:
        return
    hist = recent_snapshots.setdefault(gid, deque(maxlen=20))
    snapshot = {
        "ts": now_ts, "minute": p["minute"], "score": p["score"],
        "xg1": p["xg1"], "xg2": p["xg2"],
        "shots_on1": p["shots_on1"], "shots_on2": p["shots_on2"],
        "shots_all1": p["shots_all1"], "shots_all2": p["shots_all2"],
        "corners1": p["corners1"], "corners2": p["corners2"],
        "att1": p["att1"], "att2": p["att2"],
    }
    if hist and hist[-1]["ts"] == now_ts:
        hist[-1] = snapshot
    else:
        hist.append(snapshot)
    while hist and now_ts - hist[0]["ts"] > 900:
        hist.popleft()

    for old_gid in list(recent_snapshots):
        old_hist = recent_snapshots[old_gid]
        if not old_hist or now_ts - old_hist[-1]["ts"] > 7200:
            del recent_snapshots[old_gid]

    reference = None
    for item in hist:
        age = now_ts - item["ts"]
        if 300 <= age <= 900:
            reference = item
            break
    trend = {"available": False, "xg_delta": 0.0, "shots_on_delta": 0,
             "shots_delta": 0, "corners_delta": 0, "attacks_delta": 0}
    if reference:
        trend = {
            "available": True,
            "xg_delta": round((p["xg1"] + p["xg2"]) - (reference["xg1"] + reference["xg2"]), 3),
            "shots_on_delta": (p["shots_on1"] + p["shots_on2"]) - (reference["shots_on1"] + reference["shots_on2"]),
            "shots_delta": (p["shots_all1"] + p["shots_all2"]) - (reference["shots_all1"] + reference["shots_all2"]),
            "corners_delta": (p["corners1"] + p["corners2"]) - (reference["corners1"] + reference["corners2"]),
            "attacks_delta": (p["att1"] + p["att2"]) - (reference["att1"] + reference["att2"]),
        }
    p["trend"] = trend


def has_real_threat(p):
    """Не позволяет опасным атакам/углам быть единственным основанием сигнала."""
    total_xg = p["xg1"] + p["xg2"]
    total_sot = p["shots_on1"] + p["shots_on2"]
    total_shots = p["shots_all1"] + p["shots_all2"]
    trend = p.get("trend", {})
    recent_pressure = trend.get("available") and (
        trend.get("xg_delta", 0) >= 0.15 or trend.get("shots_on_delta", 0) >= 1
        or trend.get("shots_delta", 0) >= 3
    )
    return total_xg >= 0.70 or total_sot >= 3 or total_shots >= 8 or recent_pressure


def common_ok(p, gid, now_ts):
    if p["minute"] > MAX_MINUTE:
        return False
    prev = last_scores.get(gid)
    if prev is None:
        last_scores[gid] = {"score": p["score"], "changed_at": 0}
    elif prev.get("score") != p["score"]:
        last_scores[gid] = {"score": p["score"], "changed_at": now_ts}
        return False
    changed_at = last_scores.get(gid, {}).get("changed_at", 0)
    if changed_at and now_ts - changed_at < GOAL_COOLDOWN_SEC:
        return False
    return True

# =====================================================================
# СТРАТЕГИИ
# =====================================================================
def strategy_xg(p):
    xg_diff = abs(p["xg1"] - p["xg2"])
    shots_on_diff = abs(p["shots_on1"] - p["shots_on2"])
    if xg_diff < S1_XG_DIFF or shots_on_diff < S1_SHOTS_ON_DIFF:
        return None
    side = "home" if p["xg1"] > p["xg2"] else "away"
    red_side = p["red1"] if side == "home" else p["red2"]
    if red_side > 0:
        return None
    dominant = p["team1"] if side == "home" else p["team2"]
    return {"strategy": "xG-мощь", "emoji": "🟢", "dominant": dominant,
            "key": f"xG {xg_diff:.2f}, удары в створ {shots_on_diff}",
            "min_odd": S1_MIN_ODD}

def strategy_shots(p):
    shots_diff = abs(p["shots_all1"] - p["shots_all2"])
    shots_on_diff = abs(p["shots_on1"] - p["shots_on2"])
    if shots_diff < S2_SHOTS_DIFF or shots_on_diff < S2_SHOTS_ON_DIFF:
        return None
    side = "home" if p["shots_all1"] > p["shots_all2"] else "away"
    red_side = p["red1"] if side == "home" else p["red2"]
    if red_side > 0:
        return None
    dominant = p["team1"] if side == "home" else p["team2"]
    return {"strategy": "Удары", "emoji": "🥅", "dominant": dominant,
            "key": f"удары {shots_diff}, в створ {shots_on_diff}",
            "min_odd": S2_MIN_ODD}

def strategy_corners(p):
    corners_diff = abs(p["corners1"] - p["corners2"])
    att_diff = abs(p["att1"] - p["att2"])
    if corners_diff < S3_CORNERS_DIFF or att_diff < S3_ATT_DIFF:
        return None
    if not has_real_threat(p):
        return None
    side = "home" if p["corners1"] > p["corners2"] else "away"
    red_side = p["red1"] if side == "home" else p["red2"]
    if red_side > 0:
        return None
    dominant = p["team1"] if side == "home" else p["team2"]
    return {"strategy": "Углы + атаки", "emoji": "🚩", "dominant": dominant,
            "key": f"углы {corners_diff}, атаки {att_diff}",
            "min_odd": S3_MIN_ODD}

def strategy_attacks(p):
    att_diff = abs(p["att1"] - p["att2"])
    if att_diff < S5_ATT_DIFF:
        return None
    if not has_real_threat(p):
        return None
    side = "home" if p["att1"] > p["att2"] else "away"
    red_side = p["red1"] if side == "home" else p["red2"]
    if red_side > 0:
        return None
    dominant = p["team1"] if side == "home" else p["team2"]
    return {"strategy": "Опасные атаки", "emoji": "⚔️", "dominant": dominant,
            "key": f"атаки {att_diff}", "min_odd": S5_MIN_ODD}

def strategy_combo(p):
    xg_diff = abs(p["xg1"] - p["xg2"])
    corners_diff = abs(p["corners1"] - p["corners2"])
    if xg_diff < S6_XG_DIFF or corners_diff < S6_CORNERS_DIFF:
        return None
    side = "home" if p["xg1"] > p["xg2"] else "away"
    red_side = p["red1"] if side == "home" else p["red2"]
    if red_side > 0:
        return None
    dominant = p["team1"] if side == "home" else p["team2"]
    return {"strategy": "Комбо xG+углы", "emoji": "💡", "dominant": dominant,
            "key": f"xG {xg_diff:.2f}, углы {corners_diff}",
            "min_odd": S6_MIN_ODD}

# =====================================================================
# ФОРМАТ СИГНАЛА СТРАТЕГИЙ
# =====================================================================
def format_signal(p, strategy, odd):
    side = "home" if strategy["dominant"] == p["team1"] else "away"
    xg_dom = p["xg1"] if side == "home" else p["xg2"]
    xg_opp = p["xg2"] if side == "home" else p["xg1"]
    so_dom = p["shots_on1"] if side == "home" else p["shots_on2"]
    so_opp = p["shots_on2"] if side == "home" else p["shots_on1"]
    sa_dom = p["shots_all1"] if side == "home" else p["shots_all2"]
    sa_opp = p["shots_all2"] if side == "home" else p["shots_all1"]
    at_dom = p["att1"] if side == "home" else p["att2"]
    at_opp = p["att2"] if side == "home" else p["att1"]
    co_dom = p["corners1"] if side == "home" else p["corners2"]
    co_opp = p["corners2"] if side == "home" else p["corners1"]

    total = p["s1"] + p["s2"]
    tb1 = total + 0.5
    tb2 = total + 1.5
    odd_str = f"💰 Кэф ТБ {tb1}: <b>{odd}</b>" if odd else "💰 Кэф: —"

    return (
        f"{strategy['emoji']} <b>СИГНАЛ: {strategy['strategy']}</b>\n"
        f"{p['league']}\n"
        f"⚽ <b>{p['match']}</b>\n"
        f"📊 Счёт: <b>{p['score']}</b> | ⏱ {p['minute']}'\n"
        f"🎯 xG: {xg_dom:.2f} — {xg_opp:.2f}\n"
        f"🥅 Удары: {sa_dom} — {sa_opp} (в створ {so_dom} — {so_opp})\n"
        f"⚔️ Опасные атаки: {at_dom} — {at_opp}\n"
        f"🚩 Углы: {co_dom} — {co_opp}\n"
        f"👉 Давит: <b>{strategy['dominant']}</b>\n"
        f"🔑 {strategy['key']}\n"
        f"{odd_str}\n"
        f"💡 <b>Ожидается гол — ТБ {tb1} / ТБ {tb2}</b>"
    )

def format_signal_multi(p, strategies, odd):
    """Обновляет сигнал, не теряя исходные данные и список подтверждений."""
    total = p["s1"] + p["s2"]
    tb1, tb2 = total + 0.5, total + 1.5
    trend = p.get("trend", {})
    if trend.get("available"):
        trend_line = (f"📈 За 5–10 мин: xG +{trend['xg_delta']:.2f}, "
                      f"удары в створ +{trend['shots_on_delta']}, "
                      f"удары +{trend['shots_delta']}\n")
    else:
        trend_line = "📈 Динамика: собирается история\n"
    odd_line = f"💰 Кэф ТБ {tb1}: <b>{odd:.2f}</b>" if odd is not None else "💰 Кэф: недоступен"
    return (
        f"🎯 <b>СИГНАЛ OLD — следующий гол до конца матча</b>\n"
        f"{p['league']}\n⚽ <b>{p['match']}</b>\n"
        f"📊 Счёт: <b>{p['score']}</b> | ⏱ {p['minute']}'\n"
        f"🎯 xG: {p['xg1']:.2f} — {p['xg2']:.2f}\n"
        f"🥅 Удары: {p['shots_all1']} — {p['shots_all2']} "
        f"(в створ {p['shots_on1']} — {p['shots_on2']})\n"
        f"⚔️ Опасные атаки: {p['att1']} — {p['att2']}\n"
        f"🚩 Углы: {p['corners1']} — {p['corners2']}\n"
        f"{trend_line}{odd_line}\n"
        f"🧠 Фильтры: {', '.join(strategies)}\n"
        f"💡 Цель: хотя бы один гол до финального свистка; это оценка, не гарантия."
    )


# =====================================================================
# RUSCORE
# =====================================================================
def fetch_ruscore_events(date_str):
    params = dict(RUSCORE_PARAMS)
    params["date"] = date_str
    try:
        r = requests.get(RUSCORE_URL, params=params, headers=RUSCORE_HEADERS, timeout=15)
        if r.status_code != 200:
            return []
        data = r.json()
        events = []
        for block in data.get("data", []):
            for ev in block.get("events", []):
                ev["_league"] = block.get("name", "")
                events.append(ev)
        return events
    except Exception:
        return []

def normalize_name(s):
    if not s:
        return ""
    return (s.lower().replace(" ", "").replace("-", "").replace("'", "")
            .replace("ё", "е").replace(".", "").strip())

def find_match(events, team1, team2):
    n1, n2 = normalize_name(team1), normalize_name(team2)
    for ev in events:
        h = normalize_name((ev.get("home") or {}).get("name", ""))
        a = normalize_name((ev.get("away") or {}).get("name", ""))
        if (n1 in h or h in n1) and (n2 in a or a in n2):
            return ev
        if (n1 in a or a in n1) and (n2 in h or h in n2):
            return ev
    return None

def parse_score_from_ruscore(ev):
    for s in (ev.get("score") or []):
        if s.get("type") == "overall":
            h, a = s.get("home"), s.get("away")
            if h == "" or a == "":
                return None, None
            try:
                return int(h), int(a)
            except (ValueError, TypeError):
                return None, None
    return None, None

def parse_score_for_match(ev, team1, team2):
    """Возвращает счёт в порядке команд, как они записаны в сигнале OLD."""
    h_score, a_score = parse_score_from_ruscore(ev)
    if h_score is None or a_score is None:
        return None, None
    home = normalize_name((ev.get("home") or {}).get("name", ""))
    away = normalize_name((ev.get("away") or {}).get("name", ""))
    n1, n2 = normalize_name(team1), normalize_name(team2)
    if (n1 in home or home in n1) and (n2 in away or away in n2):
        return h_score, a_score
    if (n1 in away or away in n1) and (n2 in home or home in n2):
        return a_score, h_score
    return None, None


def check_pending_results():
    global pending_checks
    if not pending_checks:
        return

    now = int(time.time())
    by_date = {}
    for key, info in pending_checks.items():
        if now < info.get("check_after", 0):
            continue
        by_date.setdefault(info["date_str"], []).append(key)

    for date_str, keys in by_date.items():
        events = fetch_ruscore_events(date_str)
        if not events:
            for k in keys:
                pending_checks[k]["check_after"] = now + CHECK_REPEAT_AFTER
            continue

        for k in keys:
            info = pending_checks.get(k)
            if not info:
                continue

            ev = find_match(events, info["team1"], info["team2"])
            if not ev:
                info["attempts"] = info.get("attempts", 0) + 1
                info["check_after"] = now + CHECK_REPEAT_AFTER
                if info["attempts"] >= CHECK_MAX_ATTEMPTS:
                    edit_telegram(info["message_id"],
                                  format_with_result(info["base_text"],
                                                     "❓ <b>РЕЗУЛЬТАТ НЕ НАЙДЕН</b>"))
                    del pending_checks[k]
                continue

            h_score, a_score = parse_score_for_match(ev, info["team1"], info["team2"])
            status = str((ev.get("status") or {}).get("label", "")).lower()

            if h_score is None:
                info["check_after"] = now + CHECK_REPEAT_AFTER
                continue

            goal = (h_score > info["old_s1"]) or (a_score > info["old_s2"])
            finished = status in ("finished", "ended", "завершен", "завершён", "матч завершен", "матч завершён")

            if goal:
                elapsed = (now - info["signal_ts"]) // 60
                line = (f"✅ <b>ЗАШЛО</b>\n"
                        f"📊 Было: {info['old_s1']}-{info['old_s2']} ({info['minute']}')\n"
                        f"📊 Стало: {h_score}-{a_score}\n"
                        f"⏱ ~{elapsed} мин")
                edit_telegram(info["message_id"], format_with_result(info["base_text"], line))
                log_result_record({"record_type": "result", "game_id": k, "timestamp": now,
                                   "match": info["match"], "strategy": info["strategy"],
                                   "odd": info.get("odd"), "outcome": "hit",
                                   "signal_score": info.get("signal_score"),
                                   "final_score": f"{h_score}-{a_score}"})
                print(f"✅ {info['match']} [{info['strategy']}]", flush=True)
                del pending_checks[k]
                continue

            if finished:
                line = f"❌ <b>НЕ ЗАШЛО</b>\n📊 Итог: {h_score}-{a_score}"
                edit_telegram(info["message_id"], format_with_result(info["base_text"], line))
                log_result_record({"record_type": "result", "game_id": k, "timestamp": now,
                                   "match": info["match"], "strategy": info["strategy"],
                                   "odd": info.get("odd"), "outcome": "miss",
                                   "signal_score": info.get("signal_score"),
                                   "final_score": f"{h_score}-{a_score}"})
                print(f"❌ {info['match']} [{info['strategy']}]", flush=True)
                del pending_checks[k]
                continue

            info["attempts"] = info.get("attempts", 0) + 1
            info["check_after"] = now + CHECK_REPEAT_AFTER
            if info["attempts"] >= CHECK_MAX_ATTEMPTS:
                edit_telegram(info["message_id"],
                              format_with_result(info["base_text"],
                                                 f"⏱ <b>БЕЗ РЕЗУЛЬТАТА</b> ({h_score}-{a_score})"))
                del pending_checks[k]

# =====================================================================
# РАСПИСАНИЕ
# =====================================================================
def is_our_league(name):
    if not name:
        return False
    low = name.lower()
    return any(p in low for p in RUSCORE_LEAGUES_FILTER)

def get_today_schedule():
    today = datetime.now(MOSCOW_TZ).strftime("%Y-%m-%d")
    events = fetch_ruscore_events(today)
    schedule = []
    for ev in events:
        if not is_our_league(ev.get("_league", "")):
            continue
        t = ev.get("time")
        if not t:
            continue
        try:
            dt = datetime.fromisoformat(t)
            dt = dt.astimezone(MOSCOW_TZ) if dt.tzinfo else MOSCOW_TZ.localize(dt)
            schedule.append({"time": dt})
        except (ValueError, TypeError):
            continue
    return schedule

def get_windows(schedule):
    if not schedule:
        return []
    times = sorted([s["time"] for s in schedule])
    windows = [(t, t + timedelta(hours=2)) for t in times]
    merged = [windows[0]]
    for start, end in windows[1:]:
        ls, le = merged[-1]
        if start <= le:
            merged[-1] = (ls, max(le, end))
        else:
            merged.append((start, end))
    return merged

def refresh_schedule_if_needed():
    global schedule_windows, schedule_updated_at
    now = datetime.now(MOSCOW_TZ)
    if schedule_updated_at and (now - schedule_updated_at).total_seconds() < SCHEDULE_REFRESH_SEC:
        return
    print("📅 Обновляем расписание...", flush=True)
    schedule_windows = get_windows(get_today_schedule())
    schedule_updated_at = now
    if schedule_windows:
        for s, e in schedule_windows:
            print(f"   {s.strftime('%H:%M')} – {e.strftime('%H:%M')}", flush=True)

def is_match_time():
    if not schedule_windows:
        return False
    now = datetime.now(MOSCOW_TZ)
    return any(s <= now <= e for s, e in schedule_windows)

# =====================================================================
# ОТПРАВКА СИГНАЛА СТРАТЕГИИ
# =====================================================================
def try_send_signal(p, strategy, now_ts):
    """
    Первый сигнал по матчу — отправляем.
    Следующий по тому же матчу — редактируем, добавляем стратегию.
    """
    gid = p["game_id"]
    key = str(gid)

    odd = get_odd_total(p_game_cache.get(gid, {}), p["s1"] + p["s2"])

    if odd is None:
        print(f"    💸 Пропуск {p['match']} [{strategy['strategy']}] — коэффициент ТБ не найден в API", flush=True)
        return False
    try:
        odd = float(odd)
    except (TypeError, ValueError):
        return False
    if odd < strategy["min_odd"]:
        print(f"    💸 Пропуск {p['match']} [{strategy['strategy']}] — кэф {odd:.2f}", flush=True)
        return False

    existing = sent_signals.get(key)

    # ===== ПЕРВЫЙ СИГНАЛ ПО МАТЧУ =====
    if not existing:
        text = format_signal_multi(p, [f"{strategy['emoji']} {strategy['strategy']}"], odd)
        msg_id = send_telegram(text)
        if not msg_id:
            return False

        sent_signals[key] = {
            "ts": now_ts,
            "message_id": msg_id,
            "base_text": text,
            "strategies": [f"{strategy['emoji']} {strategy['strategy']}"],
            "last_p": p,
        }
        print(f"    📤 {p['match']} | {strategy['emoji']} {strategy['strategy']} | кэф {odd:.2f}", flush=True)
        log_result_record({
            "record_type": "signal", "game_id": gid, "timestamp": now_ts,
            "date_moscow": datetime.now(MOSCOW_TZ).isoformat(),
            "match": p["match"], "league": p["league"], "minute": p["minute"],
            "score": p["score"], "strategy": strategy["strategy"], "odd": odd,
            "xg1": p["xg1"], "xg2": p["xg2"],
            "shots_on1": p["shots_on1"], "shots_on2": p["shots_on2"],
            "shots_all1": p["shots_all1"], "shots_all2": p["shots_all2"],
            "att1": p["att1"], "att2": p["att2"],
            "corners1": p["corners1"], "corners2": p["corners2"],
            "trend": p.get("trend", {}),
        })

        today = datetime.now(MOSCOW_TZ).strftime("%Y-%m-%d")
        pending_checks[key] = {
            "team1": p["team1"], "team2": p["team2"],
            "match": p["match"], "date_str": today,
            "old_s1": p["s1"], "old_s2": p["s2"],
            "minute": p["minute"], "signal_ts": now_ts,
            "message_id": msg_id, "base_text": text,
            "strategy": strategy["strategy"],
            "odd": odd,
            "signal_score": p["score"],
            "check_after": now_ts + CHECK_FIRST_AFTER,
            "attempts": 0,
        }
        time.sleep(1)
        return True

    # Один прогноз на матч: повторный сигнал перезаписал бы контроль результата первого.
    if existing:
        return False
    return False

p_game_cache = {}

# =====================================================================
# ОСНОВНОЙ ЦИКЛ
# =====================================================================
def monitor():
    global sent_signals, sent_drops, p_game_cache

    print(f"🔄 {datetime.now(MOSCOW_TZ).strftime('%H:%M:%S')}", flush=True)

    games = get_live_games()
    if not games:
        print("   0 матчей", flush=True)
        return

    now_ts = int(time.time())
    p_game_cache = {g.get("id"): g for g in games if isinstance(g, dict)}

    total_our = 0
    total_signals = 0
    total_drops = 0

    by_league = {}
    for game in games:
        lid = (game.get("liga") or {}).get("id")
        if lid in LEAGUE_IDS:
            by_league[lid] = by_league.get(lid, 0) + 1
    for lid, cnt in by_league.items():
        print(f"  📋 {LEAGUE_IDS[lid]}: {cnt}", flush=True)

    for game in games:
        p = parse_game(game)
        if not p:
            continue

        gid = p["game_id"]
        update_match_history(p, now_ts)

        # =============================================================
        # ДРОП 1X2 — отдельный модуль (работает ВСЕГДА, независимо)
        # =============================================================
        odds_1x2 = get_1x2_odds(game)
        if ENABLE_1X2_DROP and odds_1x2:
            save_odds(gid, now_ts, odds_1x2)

            drops = check_drops(gid, now_ts)
            if drops:
                prev_drop = sent_drops.get(gid)
                if not (prev_drop and (now_ts - prev_drop) < DROP_ANTISPAM):
                    drop_text = format_drop_signal(p, drops)
                    if send_telegram(drop_text):
                        sent_drops[gid] = now_ts
                        total_drops += 1
                        print(f"    📉 ДРОП {p['match']} | "
                              f"{drops[0]['market']} {drops[0]['change_pct']}%", flush=True)
                        time.sleep(1)

        # =============================================================
        # СТРАТЕГИИ xG и др. (работают как раньше)
        # =============================================================
        if not common_ok(p, gid, now_ts):
            continue

        total_our += 1

        for strategy_func in (strategy_xg, strategy_shots, strategy_corners,
                              strategy_attacks, strategy_combo):
            strat = strategy_func(p)
            if not strat:
                continue
            if try_send_signal(p, strat, now_ts):
                total_signals += 1
                break

    print(f"✅ {total_our} наших, {total_signals} сигналов, "
          f"{total_drops} дропов, pending: {len(pending_checks)}", flush=True)

    sent_signals = {k: v for k, v in sent_signals.items() if now_ts - v["ts"] < 14400}
    sent_drops = {k: v for k, v in sent_drops.items() if now_ts - v < 3600}

# =====================================================================
# MAIN
# =====================================================================
def main():
    print("🚀 БОТ ЗАПУЩЕН", flush=True)
    print(f"📋 Лиг: {len(LEAGUE_IDS)}", flush=True)
    print(f"🎯 Стратегии: xG, Удары, Углы, Атаки, Комбо", flush=True)
    print(f"🎯 Цель: хотя бы один гол до конца матча; отдельный дроп 1X2: {'включён' if ENABLE_1X2_DROP else 'отключён'}", flush=True)
    print(f"⏸️ Пауза после гола: {GOAL_COOLDOWN_SEC // 60} мин", flush=True)
    print(f"🚫 Ничья (кроме 0:0) — пропуск", flush=True)
    print("=" * 60, flush=True)

    while True:
        try:
            now_str = datetime.now(MOSCOW_TZ).strftime('%H:%M')
            if not is_active_time():
                print(f"😴 Ночь ({now_str})", flush=True)
                time.sleep(600)
                continue

            refresh_schedule_if_needed()

            if is_match_time():
                monitor()
                check_pending_results()
                time.sleep(UPDATE_INTERVAL)
            else:
                print(f"💤 Матчей нет ({now_str})", flush=True)
                check_pending_results()
                time.sleep(600)

        except KeyboardInterrupt:
            print("⏹️", flush=True)
            break
        except Exception as e:
            print(f"❌ {e}", flush=True)
            import traceback
            traceback.print_exc()
            time.sleep(30)

if __name__ == "__main__":
    main()