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
BASE_URL = "https://1xlite-7720.pro"
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
    "api_key": "yAUBmZp9XJgh3US6bN1GZKtAYsFRKET6",
    "lang": "ru",
    "tz": "Europe/Moscow"
}
RUSCORE_LEAGUES_FILTER = [
    "премьер-лига", "бундеслига", "ла лига", "серия а", "лига 1",
    "россии", "рпл", "лига чемпионов", "лига европы", "лига конференций",
]

CHECK_FIRST_AFTER  = 1800
CHECK_REPEAT_AFTER = 1800
CHECK_MAX_ATTEMPTS = 4

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
    "x-hd": "3li6mKmIg5PTz2GyMGs8vd22dQHcuhYMxRR+e2T8PWMKD8rRCXsQ9PZUzd0+DiICw+4UGuu6622DymSOgU8y/wm+8LUGmxhDyoQA7IBZzk026xR8NHvlW13dPxN01ZVT6ynO+oIZq7BtjToZcIPK6TSh+paC+hAayBLg/D3p82x7g5sbuQ9Nip3yB2Vak/p/fB5qVui4XFnebDkoFIMhSBA/ehM2g/B/GOfZQon1E2v1GdApeM39i74erqrqTrM9+/HYBUiqEXxrazx02w==",
    "x-requested-with": "XMLHttpRequest",
    "x-svc-source": "__BETTING_APP__",
    "Cookie": "platform_type=desktop; auid=ua+l62qti/C6vzE7AxyDAg==; lng=ru; cookies_agree_type=3; tzo=3; is12h=0; fatman_uuid=6130f537-4410-1609-a97d-d8e42c9bd207; che_g=56f6092d-82cb-434a-aeac-681011664974; referral_values=%7B%22type%22%3A%22reflinkid%22%2C%22val%22%3A%22d_3837289m_1599c_%22%2C%22additional%22%3A%7B%22name_tag%22%3A%22tag%22%7D%7D; reflinkid=d_3837289m_1599c_; SESSION=a0b5dfe7c481dc01770a3b152bf27652; sh.session.id=f6faa86a-0670-459e-8327-f11ca865b071; _ga=GA1.1.1249863541.1789758468; window_width=1091; _ga_7JGWL9SV66=GS2.1.s1789758468$o1$g1$t1789759197$j15$l0$h1289626781",
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
    """Кэф на ТБ (total+0.5) — для value-фильтра стратегий."""
    target = total_goals + 0.5
    for grp in (game.get("centralBlockEventGroups") or []):
        if grp.get("groupId") != 17:
            continue
        events = grp.get("events") or []
        if len(events) < 2:
            continue
        tb_list = events[0] if isinstance(events[0], list) else []
        for item in tb_list:
            if (isinstance(item, dict) and item.get("parameter") == target
                    and item.get("type") == 9):
                return item.get("cf")
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
def common_ok(p, gid, now_ts):
    if p["s1"] == p["s2"] and p["s1"] != 0:
        return False
    if p["minute"] > MAX_MINUTE:
        return False
    prev = last_scores.get(gid, {})
    if prev.get("score") and prev["score"] != p["score"]:
        last_scores[gid] = {"score": p["score"], "changed_at": now_ts}
        return False
    if prev.get("changed_at"):
        if now_ts - prev["changed_at"] < GOAL_COOLDOWN_SEC:
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

            h_score, a_score = parse_score_from_ruscore(ev)
            status = (ev.get("status") or {}).get("label", "")

            if h_score is None:
                info["check_after"] = now + CHECK_REPEAT_AFTER
                continue

            goal = (h_score != info["old_s1"]) or (a_score != info["old_s2"])
            finished = status in ("finished", "ended")

            if goal:
                elapsed = (now - info["signal_ts"]) // 60
                line = (f"✅ <b>ЗАШЛО</b>\n"
                        f"📊 Было: {info['old_s1']}-{info['old_s2']} ({info['minute']}')\n"
                        f"📊 Стало: {h_score}-{a_score}\n"
                        f"⏱ ~{elapsed} мин")
                edit_telegram(info["message_id"], format_with_result(info["base_text"], line))
                print(f"✅ {info['match']} [{info['strategy']}]", flush=True)
                del pending_checks[k]
                continue

            if finished:
                line = f"❌ <b>НЕ ЗАШЛО</b>\n📊 Итог: {h_score}-{a_score}"
                edit_telegram(info["message_id"], format_with_result(info["base_text"], line))
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

    if odd is not None and odd < strategy["min_odd"]:
        print(f"    💸 Пропуск {p['match']} [{strategy['strategy']}] — кэф {odd}", flush=True)
        return False

    existing = sent_signals.get(key)

    # ===== ПЕРВЫЙ СИГНАЛ ПО МАТЧУ =====
    if not existing:
        text = format_signal(p, strategy, odd)
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
        print(f"    📤 {p['match']} | {strategy['emoji']} {strategy['strategy']} | кэф {odd}", flush=True)

        today = datetime.now(MOSCOW_TZ).strftime("%Y-%m-%d")
        pending_checks[key] = {
            "team1": p["team1"], "team2": p["team2"],
            "match": p["match"], "date_str": today,
            "old_s1": p["s1"], "old_s2": p["s2"],
            "minute": p["minute"], "signal_ts": now_ts,
            "message_id": msg_id, "base_text": text,
            "strategy": strategy["strategy"],
            "check_after": now_ts + CHECK_FIRST_AFTER,
            "attempts": 0,
        }
        time.sleep(1)
        return True

    # ===== МАТЧ УЖЕ В СИГНАЛАХ =====
    full_name = f"{strategy['emoji']} {strategy['strategy']}"

    if full_name in existing["strategies"]:
        return False

    if (now_ts - existing["ts"]) > ANTISPAM_SEC:
        del sent_signals[key]
        return try_send_signal(p, strategy, now_ts)

    # ===== ДОБАВЛЯЕМ СТРАТЕГИЮ В СУЩЕСТВУЮЩЕЕ СООБЩЕНИЕ =====
    existing["strategies"].append(full_name)
    existing["ts"] = now_ts
    existing["last_p"] = p

    new_text = format_signal_multi(p, existing["strategies"], odd)
    edit_telegram(existing["message_id"], new_text)
    existing["base_text"] = new_text

    if key in pending_checks:
        pending_checks[key]["base_text"] = new_text

    print(f"    ✏️ {p['match']} | + {full_name} "
          f"(всего: {len(existing['strategies'])})", flush=True)
    time.sleep(1)
    return True

    # ===== МАТЧ УЖЕ В СИГНАЛАХ =====
    full_name = f"{strategy['emoji']} {strategy['strategy']}"

    # Эта стратегия уже подтвердила — пропуск
    if full_name in existing["strategies"]:
        return False

    # Прошло много времени — старый удаляем, новый отправляем
    if (now_ts - existing["ts"]) > ANTISPAM_SEC:
        del sent_signals[key]
        return try_send_signal(p, strategy, now_ts)

    # ===== ДОБАВЛЯЕМ СТРАТЕГИЮ В СУЩЕСТВУЮЩЕЕ СООБЩЕНИЕ =====
    existing["strategies"].append(full_name)
    existing["ts"] = now_ts
    existing["last_p"] = p

    new_text = format_signal_multi(p, existing["strategies"], odd)
    edit_telegram(existing["message_id"], new_text)
    existing["base_text"] = new_text

    # Обновляем pending (свежие данные)
    if key in pending_checks:
        pending_checks[key]["base_text"] = new_text

    print(f"    ✏️ {p['match']} | + {full_name} "
          f"(всего: {len(existing['strategies'])})", flush=True)
    time.sleep(1)
    return True

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

        # =============================================================
        # ДРОП 1X2 — отдельный модуль (работает ВСЕГДА, независимо)
        # =============================================================
        odds_1x2 = get_1x2_odds(game)
        if odds_1x2:
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

    sent_signals = {k: v for k, v in sent_signals.items() if now_ts - v < 3600}
    sent_drops = {k: v for k, v in sent_drops.items() if now_ts - v < 3600}

# =====================================================================
# MAIN
# =====================================================================
def main():
    print("🚀 БОТ ЗАПУЩЕН", flush=True)
    print(f"📋 Лиг: {len(LEAGUE_IDS)}", flush=True)
    print(f"🎯 Стратегии: xG, Удары, Углы, Атаки, Комбо", flush=True)
    print(f"📉 Дроп 1X2 (П1/X/П2): {DROP_PCT}% за {DROP_WINDOW}с", flush=True)
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