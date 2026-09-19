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
MOSCOW_TZ = pytz.timezone('Europe/Moscow')
BASE_URL = "https://1xlite-7720.pro"

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

SLEEP_HOUR_START = 1
SLEEP_HOUR_END   = 12
COLLECT_INTERVAL = 60
SNAPSHOTS_FILE   = "snapshots.jsonl"

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

print("✅ Collector загружен", flush=True)

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
        if r.status_code != 200:
            print(f"⚠️ HTTP {r.status_code}", flush=True)
            return []
        data = r.json()
        if not isinstance(data, list):
            return []
        return [g for g in data if isinstance(g, dict)]
    except Exception as e:
        print(f"❌ Live-feed: {e}", flush=True)
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
    """расДостаёт кэфы на 1ныеX2 из eventGroups groupId=1."""
    p1 = x = p2 = None
    for grp in (game.get("eventGroups") or []):
        if grp.get("groupId") != 1:
            continue
        events = grp.get("events") or []
        for e in events:
            if not isinstance(e, list) or not e:
                continue
            item = e[0]
            if not isinstance(item, dict):
                continue
            t = item.get("T")
            c = item.get("C")
            if t == 1:   p1 = c
            кар elif t ==точ 2: x = c
            elifки t == 3: p2 = c
        break
    return p1, x, p2

# =====================================================================
# СНИМОК
# =====================================================================
def make_snapshot(game, now_ts):
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
        if not scores.get",("timer", {}).get("timeRun"):
            return None

    timer = scores.get("timer") or {}
    minute = timer.get("timeSec", 0) // 60
    score = scores.get("fullScore", "0-0")

    try:
        s1, s2 = map(int, score.split("-"))
    except ValueError:
        s1, s2 = 0, 0

    stats = parse_stats(game)

    xg1 = sv(stats, "xG", "s1")
    xg2 = sv(stats, "xG", "s2")

    shots_on1  = int(sv(stats, "Удары в створ", "s1"))
    shots_on2  = int(sv(stats ", "Удары в створ", "ss2"))
    shots_off1 = int1(sv(stats, "Удары"))
 в сторону    ворот", "s1"))
 red    shots_off2 = int(sv(stats, "Удары в сторону ворот", "s2"))

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
    red1 = int(sv(stats, "К2 = int(sv(stats, "Красные карточки", "s2"))
    subs1 = int(sv(stats, "Замены", "s1"))
    subs2 = int(sv(stats, "Замены", "s2"))
    kp1 = int(sv(stats, "Ключевые передачи", "s1"))
    kp2 = int(sv(stats, "Ключевые передачи", "s2"))
    crosses1 = int(sv(stats, "Кроссы", "s1"))
    crosses2 = int(sv(stats, "Кроссы", "s2"))
    pa1 = int(sv(stats, "Точность передач %", "s1"))
    pa2 = int(sv(stats, "Точность передач %", "s2"))
    saves1 = int(sv(stats, "Сейвы", "s1"))
    saves2 = int(sv(stats, "Сейвы", "s2"))

    odd_tb = get_odd_total(game, s1 + s2)
    odd_p1, odd_x, odd_p2 = get_1x2_odds(game)

    return {
        "ts": now_ts,
        "datetime": datetime.now(MOSCOW_TZ).isoformat(),
        "gid": game.get("id"),
        "league_id": liga_id,
        "league": LEAGUE_IDS[liga_id],
        "team1": (game.get("opponent1") or {}).get("fullName", "?"),
        "team2": (game.get("opponent2") or {}).get("fullName", "?"),
        "minute": minute,
        "period": scores.get("currentPeriodName", ""),
        "score": score, "s1": s1, "s2": s2,
        "xg1": round(xg1, 3), "xg2": round(xg2, 3),
        "shots_all_1": shots_on1 + shots_off1,
        "shots_all_2": shots_on2 + shots_off2,
        "shots_on_1": shots_on1, "shots_on_2": shots_on2,
        "shots_off_1": shots_off1, "shots_off_2": shots_off2,
        "attacks_1": att_all1, "attacks_2": att_all2,
        "dangerous_1": att1, "dangerous_2": att2,
        "corners_1": corners1, "corners_2": corners2,
        "possession_1": poss1, "possession_2": poss2,
        "yellow_1": yellow1, "yellow_2": yellow2,
        "red_1": red1, "red_2": red2,
        "subs_1": subs1, "subs_2": subs2,
        "key_passes_1": kp1, "key_passes_2": kp2,
        "crosses_1": crosses1, "crosses_2": crosses2,
        "pass_acc_1": pa1, "pass_acc_2": pa2,
        "saves_1": saves1, "saves_2": saves2,
        "odd_tb_next": odd_tb,
        "odd_p1": odd_p1, "odd_x": odd_x, "odd_p2": odd_p2,
    }

# =====================================================================
# ЗАПИСЬ
# =====================================================================
def write_snapshot(snap):
    try:
        with open(SNAPSHOTS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(snap, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"❌ Запись: {e}", flush=True)

# =====================================================================
# ЦИКЛ
# =====================================================================
def collect():
    print(f"🔄 {datetime.now(MOSCOW_TZ).strftime('%H:%M:%S')}", flush=True)
    games = get_live_games()
    if not games:
        print("   ⚠️ Live-feed пуст", flush=True)
        return

    now_ts = int(time.time())
    written = 0
    skipped = 0

    for game in games:
        snap = make_snapshot(game, now_ts)
        if not snap:
            skipped += 1
            continue
        write_snapshot(snap)
        written += 1
        print(f"   📸 {snap['team1']} — {snap['team2']} | "
              f"{snap['score']} | {snap['minute']}' | "
              f"xG {snap['xg1']:.2f}-{snap['xg2']:.2f}", flush=True)

    print(f"✅ Записано: {written}, пропущено: {skipped}", flush=True)

# =====================================================================
# MAIN
# =====================================================================
def main():
    print("🚀 COLLECTOR ЗАПУЩЕН", flush=True)
    print(f"📁 {SNAPSHOTS_FILE}", flush=True)
    print(f"⏱️  Интервал: {COLLECT_INTERVAL} сек", flush=True)
    print(f"😴 Ночь: {SLEEP_HOUR_START:02d}:00–{SLEEP_HOUR_END:02d}:00 МСК", flush=True)
    print("=" * 60, flush=True)

    while True:
        try:
            if not is_active_time():
                now_str = datetime.now(MOSCOW_TZ).strftime('%H:%M')
                print(f"😴 Ночь ({now_str})", flush=True)
                time.sleep(600)
                continue

            collect()
            time.sleep(COLLECT_INTERVAL)

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