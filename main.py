import time
from datetime import datetime
from config import *
from telegram_bot import send_telegram
from stats_parser import parse_game, update_match_history, common_ok, strategy_xg, strategy_shots, strategy_corners, strategy_attacks, strategy_combo, get_1x2_odds
from live_logic import check_pending_results, try_send_signal
from ruscore import get_today_schedule, get_windows
import requests

p_game_cache = {}
sent_signals = {}
pending_checks = {}
last_scores = {}
recent_snapshots = {}
schedule_windows = []
schedule_updated_at = None

def get_live_games():
    try:
        r = requests.get(f"{BASE_URL}/service-api/main-live-feed/v3/games1x2", headers=HEADERS, params={"cfView": 3, "count": 40, "fcountry": 1, "gr": 2336, "grMode": 4, "lng": "ru", "ref": 1}, timeout=15)
        return [g for g in r.json() if isinstance(g, dict)] if r.status_code == 200 else []
    except: return []

def monitor():
    global p_game_cache, sent_signals, pending_checks, last_scores, recent_snapshots
    games = get_live_games()
    if not games: return
    now_ts = int(time.time())
    p_game_cache = {g.get("id"): g for g in games if isinstance(g, dict)}
    
    for game in games:
        p = parse_game(game)
        if not p: continue
        gid = p["game_id"]
        update_match_history(p, now_ts, recent_snapshots)
        
        if not common_ok(p, gid, now_ts, last_scores): continue

        for func in (strategy_xg, strategy_shots, strategy_corners, strategy_attacks, strategy_combo):
            strat = func(p)
            if strat and try_send_signal(p, strat, now_ts, p_game_cache, sent_signals, pending_checks):
                break

    sent_signals = {k: v for k, v in sent_signals.items() if now_ts - v["ts"] < 14400}

def refresh_schedule_if_needed():
    global schedule_windows, schedule_updated_at
    now = datetime.now(MOSCOW_TZ)
    if schedule_updated_at and (now - schedule_updated_at).total_seconds() < SCHEDULE_REFRESH_SEC: return
    schedule_windows = get_windows(get_today_schedule())
    schedule_updated_at = now

def is_match_time():
    if not schedule_windows: return False
    now = datetime.now(MOSCOW_TZ)
    return any(s <= now <= e for s, e in schedule_windows)

def main():
    print("🚀 LIVE-БОТ ЗАПУЩЕН", flush=True)
    while True:
        try:
            now_str = datetime.now(MOSCOW_TZ).strftime('%H:%M')
            if not (SLEEP_HOUR_START <= datetime.now(MOSCOW_TZ).hour < SLEEP_HOUR_END):
                refresh_schedule_if_needed()
                if is_match_time():
                    monitor()
                    check_pending_results(pending_checks)
                    time.sleep(UPDATE_INTERVAL)
                else:
                    print(f"💤 Матчей нет ({now_str})", flush=True)
                    check_pending_results(pending_checks)
                    time.sleep(600)
            else:
                print(f"😴 Ночь ({now_str})", flush=True)
                time.sleep(600)
        except Exception as e:
            print(f"❌ {e}", flush=True); time.sleep(30)

if __name__ == "__main__":
    main()
