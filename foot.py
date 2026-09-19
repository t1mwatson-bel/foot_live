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

RUSCORE_LEAGUES_FILTER = [
    "премьер-лига", "бундеслига", "ла лига", "серия а", "лига 1",
    "россии", "рпл", "лига чемпионов", "лига европы", "лига конференций",
]

# =====================================================================
# ПОРОГИ
# =====================================================================
# Уровень A (🔥🔥)
A_XG_DIFF      = 1.6
A_SHOTS_ALL    = 12
A_SHOTS_ON     = 4
A_ATT_DIFF     = 28
A_CORNERS_DIFF = 3
A_ATT_CONV     = 0.20
A_MIN_ODD      = 1.3

# Уровень B (🟢)
B_XG_DIFF      = 1.2
B_SHOTS_ALL    = 9
B_SHOTS_ON     = 3
B_ATT_DIFF     = 20
B_CORNERS_DIFF = 2
B_ATT_CONV     = 0.15
B_MIN_ODD      = 1.5

MAX_MINUTE        = 80
UPDATE_INTERVAL   = 60
ANTISPAM_SEC      = 900
GOAL_COOLDOWN_SEC = 600
DECAY_WINDOW_MIN  = 5
DECAY_MIN_DXG     = 0.05
DYNAMIC_WINDOWS   = [3, 5, 10, 15]

# Дроп кэфа
ODDS_DROP_WINDOW_SEC = 180       # окно сравнения 3 минуты
ODDS_DROP_PCT        = -10.0     # падение 10%+
ODDS_HISTORY_MAXLEN  = 30

# Проверка результата
CHECK_FIRST_AFTER  = 1800
CHECK_REPEAT_AFTER = 1800
CHECK_MAX_ATTEMPTS = 4

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
    "Cookie": "platform_type=desktop; auid=ua+l62qti/C6vzE7AxyDAg==; lng=ru; cookies_agree_type=3; tzo=3; is12h=0; fatman_uuid=6130f537-4410-1609-a97d-d8e42c9bd207; che_g=56f6092d-82cb-434a-aeac-681011664974; referral_values=%7B%22type%22%3A%22reflinkid%22%2C%22val%22%3A%22d_en3837289m_1599c;_%22%2C%22additionalq%22%3=A%7B%22name_tag%220%3A%22tag%22%7D%7D; reflinkid=d_3837289m_1599c_; SESSION=a0b5dfe7c481dc01770a3b152bf27652; sh.session.id=f6faa86a-0670-459e-8327-f11ca865b071; _ga=GA1.1.1249863541.1789758468; window_width=1091; _ga_7JGWL9SV66=GS2.1.s1789758468$o1$g1$t1789759197$j15$l0$h1289626781",
}

RUSCORE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 YaBrowser/26.8.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,.7",
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
schedule_windows = []
schedule_updated_at = None
last_scores = {}
history = {}         # {gid: deque([snapshot, ...], maxlen=30)}
odds_history = {}    # {gid: deque([{ts, tb, p1, x, p2}, ...], maxlen=30)}

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
    params = {
        "cfView": 3, "count": 40, "fcountry": 1,
        "gr": 2336, "grMode": 4, "lng": "ru", "ref": 1,
    }
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
# ПАРСИНГ
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

def get_odd_total(game, total_goals):
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

def get_1x2_odds(game):
    p1 = x = p2 = None
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
            if t == 1:   p1 = c
            elif t == 2: x = c
            elif t == 3: p2 = c
        break
    return p1, x, p2

# =====================================================================
# ИСТОРИЯ МЕТРИК
# =====================================================================
def update_history(gid, snap):
    if gid not in history:
        history[gid] = deque(maxlen=30)
    history[gid].append(snap)

def get_dyn(gid, now_minute, window_min):
    if gid not in history or len(history[gid]) < 2:
        return None
    cur = history[gid][-1]
    prev = None
    for snap in reversed(history[gid]):
        if now_minute - snap["minute"] >= window_min:
            prev = snap
            break
    if prev is None:
        return None
    return {
        "dxg1": cur["xg1"] - prev["xg1"],
        "dxg2": cur["xg2"] - prev["xg2"],
        "dshots_all1": cur["shots_all1"] - prev["shots_all1"],
        "dshots_all2": cur["shots_all2"] - prev["shots_all2"],
        "dshots_on1": cur["shots_on1"] - prev["shots_on1"],
        "dshots_on2": cur["shots_on2"] - prev["shots_on2"],
        "datt1": cur["att1"] - prev["att1"],
        "datt2": cur["att2"] - prev["att2"],
        "dcorners1": cur["corners1"] - prev["corners1"],
        "dcorners2": cur["corners2"] - prev["corners2"],
        "minutes": now_minute - prev["minute"],
    }

# =====================================================================
# ИСТОРИЯ КЭФОВ + ДРОП
# =====================================================================
def save_odds(gid, now_ts, tb, p1, x, p2):
    if gid not in odds_history:
        odds_history[gid] = deque(maxlen=ODDS_HISTORY_MAXLEN)
    odds_history[gid].append({
        "ts": now_ts, "tb": tb, "p1": p1, "x": x, "p2": p2,
    })

def check_odds_drop(gid, now_ts):
    if gid not in odds_history or len(odds_history[gid]) < 2:
        return None

    cur = odds_history[gid][-1]
    prev = None
    for h in reversed(odds_history[gid][:-1]):
        if now_ts - h["ts"] >= ODDS_DROP_WINDOW_SEC:
            prev = h
            break

    if prev is None:
        return None

    results = []
    for key, label in [("tb", "ТБ"), ("p1", "П1"), ("x", "X"), ("p2", "П2")]:
        c_val = cur.get(key)
        p_val = prev.get(key)
        if not c_val or not p_val:
            continue
        change = (c_val - p_val) / p_val * 100
        if change <= ODDS_DROP_PCT:
            results.append({
                "label": label,
                "from": p_val,
                "to": c_val,
                "change_pct": round(change, 1),
                "window_sec": now_ts - prev["ts"],
            })

    return results if results else None

# =====================================================================
# ЯДРО АНАЛИЗА
# =====================================================================
def analyze_game(game, now_ts):
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

    timer = scores.get("timer") or {}
    minute = timer.get("timeSec", 0) // 60
    score = scores.get("fullScore", "0-0")

    try:
        s1, s2 = map(int, score.split("-"))
    except ValueError:
        s1, s2 = 0, 0

    # Ничья (кроме 0:0)
    if s1 == s2 and s1 != 0:
        return None

    # Пауза после гола
    gid = game.get("id")
    prev = last_scores.get(gid, {})
    if prev.get("score") and prev["score"] != score:
        last_scores[gid] = {"score": score, "changed_at": now_ts}
        return None
    if prev.get("changed_at"):
        if now_ts - prev["changed_at"] < GOAL_COOLDOWN_SEC:
            return None

    # Статистика
    stats = parse_stats(game)
    xg1 = sv(stats, "xG", "s1")
    xg2 = sv(stats, "xG", "s2")

    shots_on1  = int(sv(stats, "Удары в створ", "s1"))
    shots_on2  = int(sv(stats, "Удары в створ", "s2"))
    shots_off1 = int(sv(stats, "Удары в сторону ворот", "s1"))
    shots_off2 = int(sv(stats, "Удары в сторону ворот", "s2"))
    shots_all1 = shots_on1 + shots_off1
    shots_all2 = shots_on2 + shots_off2

    att1 = int(sv(stats, "Опасные атаки", "s1"))
    att2 = int(sv(stats, "Опасные атаки", "s2"))
    att_all1 = int(sv(stats, "Атаки", "s1"))
    att_all2 = int(sv(stats, "Атаки", "s2"))
    corners1 = int(sv(stats, "Угловые", "s1"))
    corners2 = int(sv(stats, "Угловые", "s2"))
    poss1 = int(sv(stats, "Владение мячом %", "s1"))
    poss2 = int(sv(stats, "Владение мячом %", "s2"))
    yellow1 = int(sv(stats, "Желтые карточки", "s1"))
    yellow2 = int(sv(stats, "Желтые карточки", "s2"))
    red1 = int(sv(stats, "Красные карточки", "s1"))
    red2 = int(sv(stats, "Красные карточки", "s2"))
    subs1 = int(sv(stats, "Замены", "s1"))
    subs2 = int(sv(stats, "Замены", "s2"))
    kp1 = int(sv(stats, "Ключевые передачи", "s1"))
    kp2 = int(sv(stats, "Ключевые передачи", "s2"))

    # Сохраняем кэфы
    odd_tb = get_odd_total(game, s1 + s2)
    odd_p1, odd_x, odd_p2 = get_1x2_odds(game)
    save_odds(gid, now_ts, odd_tb, odd_p1, odd_x, odd_p2)

    # История
    snap = {
        "ts": now_ts, "minute": minute,
        "xg1": xg1, "xg2": xg2,
        "shots_all1": shots_all1, "shots_all2": shots_all2,
        "shots_on1": shots_on1, "shots_on2": shots_on2,
        "att1": att1, "att2": att2,
        "corners1": corners1, "corners2": corners2,
    }
    update_history(gid, snap)

    # Направление давления
    if xg1 > xg2 and shots_all1 > shots_all2 and att1 > att2:
        side = "home"
        p_xg, p_sh_all, p_sh_on = xg1 - xg2, shots_all1 - shots_all2, shots_on1 - shots_on2
        p_att, p_corners = att1 - att2, corners1 - corners2
        p_poss = poss1 - poss2
        p_att_abs = att1
    elif xg2 > xg1 and shots_all2 > shots_all1 and att2 > att1:
        side = "away"
        p_xg, p_sh_all, p_sh_on = xg2 - xg1, shots_all2 - shots_all1, shots_on2 - shots_on1
        p_att, p_corners = att2 - att1, corners2 - corners1
        p_poss = poss2 - poss1
        p_att_abs = att2
    else:
        return None

    # xG фиктивный
    if p_xg >= 1.3 and p_sh_on < 2:
        return None

    # Красная у давящей
    red_side = red1 if side == "home" else red2
    red_opp  = red2 if side == "home" else red1
    if red_side > 0:
        return None

    # Поздно
    if minute > MAX_MINUTE:
        return None

    # Динамика
    dyns = {w: get_dyn(gid, minute, w) for w in DYNAMIC_WINDOWS}

    def dxg_side(d):
        return (d["dxg1"] if side == "home" else d["dxg2"]) if d else None

    dyn_xg_5  = dxg_side(dyns.get(5))
    dyn_xg_10 = dxg_side(dyns.get(10))
    dyn_xg_15 = dxg_side(dyns.get(15))

    # Decay
    decay_check = dyns.get(DECAY_WINDOW_MIN)
    if decay_check and minute > 40:
        d_side = dxg_side(decay_check)
        if d_side is not None and d_side < DECAY_MIN_DXG:
            return None

    # Conversion
    conv = p_sh_all / max(p_att_abs, 1)

    # Скорость xG
    speed_xg = None
    if dyns.get(5) and dyns[5]["minutes"] > 0:
        speed_xg = dxg_side(dyns[5]) / dyns[5]["minutes"]

    # Уровень A
    is_A = (
        p_xg >= A_XG_DIFF and
        p_sh_all >= A_SHOTS_ALL and
        p_sh_on >= A_SHOTS_ON and
        p_att >= A_ATT_DIFF and
        p_corners >= A_CORNERS_DIFF and
        conv >= A_ATT_CONV
    )
    # Уровень B
    is_B = (
        p_xg >= B_XG_DIFF and
        p_sh_all >= B_SHOTS_ALL and
        p_sh_on >= B_SHOTS_ON and
        p_att >= B_ATT_DIFF and
        p_corners >= B_CORNERS_DIFF and
        conv >= B_ATT_CONV
    )
    if not is_A and not is_B:
        return None

    if is_B and dyn_xg_10 is not None and dyn_xg_10 >= 0.3:
        is_A = True

    level = "A" if is_A else "B"
    signal_type = "🔥🔥 СИЛЬНЫЙ СИГНАЛ" if is_A else "🟢 СИГНАЛ НА ГОЛ"

    # Value-фильтр по кэфу
    min_odd = A_MIN_ODD if is_A else B_MIN_ODD
    if odd_tb is not None and odd_tb < min_odd:
        print(f"   💸 Пропуск {score} — кэф {odd_tb} < {min_odd}", flush=True)
        return None

    o1 = (game.get("opponent1") or {}).get("fullName", "?")
    o2 = (game.get("opponent2") or {}).get("fullName", "?")
    dominant = o1 if side == "home" else o2
    total = s1 + s2

    return {
        "game_id":   gid,
        "team1":     o1, "team2": o2,
        "match":     f"{o1} — {o2}",
        "league":    LEAGUE_IDS.get(liga_id, ""),
        "score":     score, "minute": minute,
        "xg":        f"{xg1:.2f} — {xg2:.2f}",
        "xg_diff":   round(p_xg, 2),
        "shots_all": f"{shots_all1} — {shots_all2}",
        "shots_on":  f"{shots_on1} — {shots_on2}",
        "attacks":   f"{att1} — {att2}",
        "corners":   f"{corners1} — {corners2}",
        "poss":      f"{poss1}% — {poss2}%",
        "yellow":    f"{yellow1} — {yellow2}",
        "red":       f"{red1} — {red2}",
        "subs":      f"{subs1} — {subs2}",
        "key_pass":  f"{kp1} — {kp2}",
        "conv":      round(conv, 2),
        "speed_xg":  round(speed_xg, 3) if speed_xg else None,
        "dyn_xg_5":  round(dyn_xg_5, 2) if dyn_xg_5 is not None else None,
        "dyn_xg_10": round(dyn_xg_10, 2) if dyn_xg_10 is not None else None,
        "dyn_xg_15": round(dyn_xg_15, 2) if dyn_xg_15 is not None else None,
        "dominant":  dominant,
        "red_opp":   red_opp,
        "signal":    signal_type,
        "level":     level,
        "odd_tb":    odd_tb,
        "tb_line":   total + 0.5,
        "tb_line2":  total + 1.5,
    }

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

def fmt_opt(v):
    return f"{v}" if v is not None else "—"

def format_signal(s):
    odd = f"💰 Кэф ТБ {s['tb_line']}: <b>{s['odd_tb']}</b>" if s['odd_tb'] else "💰 Кэф: —"
    conv = f"📊 Conversion: <b>{s['conv']}</b>"
    speed = f"⚡ Скорость xG: <b>{s['speed_xg']}</b>/мин" if s['speed_xg'] else "⚡ Скорость: —"
    dyn = (f"📈 ΔxG: 5м={fmt_opt(s['dyn_xg_5'])} | "
           f"10м={fmt_opt(s['dyn_xg_10'])} | "
           f"15м={fmt_opt(s['dyn_xg_15'])}")
    red_note = f"\n🟥 Красная у соперника!" if s['red_opp'] > 0 else ""

    return (
        f"{s['signal']} (уровень {s['level']})\n"
        f"{s['league']}\n"
        f"⚽ <b>{s['match']}</b>\n"
        f"📊 Счёт: <b>{s['score']}</b> | ⏱ {s['minute']}'\n"
        f"🎯 xG: {s['xg']} (Δ {s['xg_diff']})\n"
        f"🥅 Удары: {s['shots_all']} (в створ {s['shots_on']})\n"
        f"⚔️ Опасные атаки: {s['attacks']}\n"
        f"🌐 Владение: {s['poss']}\n"
        f"🚩 Углы: {s['corners']}\n"
        f"🎯 Ключевые: {s['key_pass']}\n"
        f"🟨 {s['yellow']} | 🟥 {s['red']}\n"
        f"🔄 Замены: {s['subs']}{red_note}\n"
        f"👉 Давит: <b>{s['dominant']}</b>\n"
        f"{dyn}\n"
        f"{speed}\n"
        f"{conv}\n"
        f"{odd}\n"
        f"💡 <b>ТБ {s['tb_line']} / ТБ {s['tb_line2']}</b>"
    )

def format_drop_signal(league, match, score, minute, drops):
    lines = [f"📉 <b>ДРОП КЭФА</b>", league, f"⚽ <b>{match}</b>",
             f"📊 Счёт: <b>{score}</b> | ⏱ {minute}'", ""]
    for d in drops:
        lines.append(f"• {d['label']}: {d['from']} → {d['to']} "
                     f"({d['change_pct']}% за {d['window_sec']}с)")
    lines.append("💡 Умные деньги идут на событие")
    return "\n".join(lines)

def format_with_result(base_text, result_line):
    return f"{base_text}\n\n{result_line}"

# =====================================================================
# RUSCORE
# =====================================================================
def fetch_ruscore_events(date_str):
    params = dict(RUSCORE_PARAMS)
    params["date"] = date_str
    try:
        r = requests.get(RUSCORE_URL, params=params, headers=RUSCORE_HEADERS, timeout=15)
        print(f"📅 ruscore: {r.status_code}", flush=True)
        if r.status_code != 200:
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
    return (s.lower().replace(" ", "").replace("-", "").replace("'", "")
            .replace("ё", "е").replace(".", "").strip())

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
                    edit_telegram(info["message_id