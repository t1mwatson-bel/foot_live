import time
import threading
import traceback
from datetime import datetime

import requests
import web
import database as db
import goal_model as ml

from config import *
from stats_parser import (
    parse_game,
    update_match_history,
    common_ok,
    strategy_xg,
    strategy_shots,
    strategy_corners,
    strategy_attacks,
    strategy_combo,
)
from live_logic import (
    check_pending_results,
    try_send_signal,
    restore_pending_checks,
    retry_pending_telegram_updates,
)
from ruscore import (
    get_today_schedule, 
    get_windows,
    fetch_ruscore_events,
    find_match,
    fetch_ruscore_lineups,
    enrich_with_ruscore
)


p_game_cache = {}
sent_signals = {}
pending_checks = {}
last_scores = {}
recent_snapshots = {}
schedule_windows = []
schedule_updated_at = None

# Кэш для событий Ruscore, чтобы не дёргать API каждую минуту
ruscore_events_cache = []
ruscore_cache_updated_at = None

def get_live_games():
    try:
        # Возвращаем правильный эндпоинт со статистикой
        url = f"{BASE_URL}/service-api/main-live-feed/v3/topGamesByStat"
        params = {
            "cfView": 3,
            "excludeSportIds": 66,
            "fcountry": 1,
            "gr": 2336,
            "lng": "ru",
            "ref": 1,
        }

        response = requests.get(
            url,
            headers=HEADERS,
            params=params,
            timeout=15,
        )

        print(f"🔎 1xlite HTTP: {response.status_code}", flush=True)

        if response.status_code != 200:
            print(f"❌ Ошибка 1xlite: {response.text[:200]}", flush=True)
            return []

        data = response.json()

        if not isinstance(data, list):
            print(f"❌ 1xlite вернул неожиданный тип: {type(data)}", flush=True)
            return []

        print(f"📊 Матчей в ответе API: {len(data)}", flush=True)
        return [game for game in data if isinstance(game, dict)]

    except Exception as e:
        print(f"❌ Ошибка получения матчей: {e}", flush=True)
        return []

def refresh_ruscore_events_if_needed():
    """Обновляет кэш матчей Ruscore раз в 10 минут."""
    global ruscore_events_cache, ruscore_cache_updated_at
    now = datetime.now(MOSCOW_TZ)
    
    if ruscore_cache_updated_at and (now - ruscore_cache_updated_at).total_seconds() < 600:
        return
        
    today = now.strftime("%Y-%m-%d")
    try:
        events = fetch_ruscore_events(today)
        if events:
            ruscore_events_cache = events
            ruscore_cache_updated_at = now
            print(f"📅 Ruscore кэш обновлён: {len(events)} матчей", flush=True)
    except Exception as e:
        print(f"⚠️ Ошибка обновления кэша Ruscore: {e}", flush=True)

def monitor():
    global p_game_cache, sent_signals, pending_checks
    global last_scores, recent_snapshots

    games = get_live_games()
    if not games:
        return

    now_ts = int(time.time())

    p_game_cache = {}

    for game in games:
        if not isinstance(game, dict):
            continue
        gid = game.get("id")
        if gid is not None:
            p_game_cache[gid] = game
            p_game_cache[str(gid)] = game

    found_leagues = {}

    for game in games:
        lid = (game.get("liga") or {}).get("id")
        if lid in LEAGUE_IDS:
            found_leagues[lid] = found_leagues.get(lid, 0) + 1

    if found_leagues:
        for lid, count in found_leagues.items():
            print(f"🏆 {LEAGUE_IDS[lid]}: {count}", flush=True)
    else:
        print("⚠️ В текущем ответе нет матчей из LEAGUE_IDS", flush=True)

    for game in games:
        try:
            parsed = parse_game(game)

            if not parsed:
                continue

            gid = parsed["game_id"]

            # --- ПОИСК И ОБОГАЩЕНИЕ ДАННЫМИ RUSCORE ---
            ruscore_event = find_match(ruscore_events_cache, parsed["team1"], parsed["team2"])
            if ruscore_event and ruscore_event.get("id"):
                # Подтягиваем травмы и составы
                ruscore_data = fetch_ruscore_lineups(ruscore_event["id"])
                if ruscore_data:
                    parsed = enrich_with_ruscore(parsed, ruscore_data)
            # ------------------------------------------

            update_match_history(
                parsed,
                now_ts,
                recent_snapshots,
            )

            if not common_ok(parsed, gid, now_ts, last_scores):
                continue

            for strategy_func in (
                strategy_xg,
                strategy_shots,
                strategy_corners,
                strategy_attacks,
                strategy_combo,
            ):
                strategy = strategy_func(parsed)

                if not strategy:
                    continue

                sent = try_send_signal(
                    parsed,
                    strategy,
                    now_ts,
                    p_game_cache,
                    sent_signals,
                    pending_checks,
                )

                if sent:
                    break

        except Exception as e:
            print(f"❌ Ошибка обработки отдельного матча {game.get('id')}: {e}", flush=True)
            traceback.print_exc()

    sent_signals = {
        key: value
        for key, value in sent_signals.items()
        if now_ts - value.get("ts", now_ts) < 14400
    }


def refresh_schedule_if_needed():
    global schedule_windows, schedule_updated_at

    now = datetime.now(MOSCOW_TZ)

    if (schedule_updated_at and (now - schedule_updated_at).total_seconds() < SCHEDULE_REFRESH_SEC):
        return

    try:
        schedule = get_today_schedule()
        schedule_windows = get_windows(schedule)
        schedule_updated_at = now
        print(f"📅 Расписание обновлено. Окон: {len(schedule_windows)}", flush=True)
    except Exception as e:
        print(f"⚠️ Не удалось обновить расписание: {e}", flush=True)


def is_match_time():
    return True

def run_web():
    try:
        web.app.run(host="0.0.0.0", port=3000, use_reloader=False, threaded=True)
    except Exception as e:
        print(f"❌ Ошибка запуска сайта: {e}", flush=True)


def retry_telegram_results():
    try:
        retry_pending_telegram_updates()
    except Exception as e:
        print(f"❌ Ошибка повторного обновления Telegram: {e}", flush=True)
        traceback.print_exc()


def check_results_safely():
    try:
        check_pending_results(pending_checks)
    except Exception as e:
        print(f"❌ Ошибка проверки результатов: {e}", flush=True)
        traceback.print_exc()


def bot_loop():
    print("🚀 LIVE-БОТ OLD ЗАПУЩЕН", flush=True)
    
    try:
        ml.sync_confirmed_results()
    except Exception as e:
        print(f"⚠️ Ошибка при старте синхронизации OLD ML: {e}", flush=True)

    while True:
        try:
            now = datetime.now(MOSCOW_TZ)
            now_str = now.strftime("%H:%M")

            check_results_safely()
            retry_telegram_results()

            if SLEEP_HOUR_START <= now.hour < SLEEP_HOUR_END:
                print(f"😴 Ночной режим ({now_str}); проверка результатов продолжается", flush=True)
                time.sleep(60)
                continue

            refresh_schedule_if_needed()
            # Обновляем кэш матчей Ruscore перед мониторингом
            refresh_ruscore_events_if_needed()

            if is_match_time():
                monitor()

            check_results_safely()
            retry_telegram_results()

            time.sleep(UPDATE_INTERVAL)

        except KeyboardInterrupt:
            print("⏹️ Остановка по команде", flush=True)
            break
        except Exception as e:
            print(f"❌ Ошибка основного цикла: {e}", flush=True)
            traceback.print_exc()
            check_results_safely()
            retry_telegram_results()
            time.sleep(30)


if __name__ == "__main__":
    db.init_db()
    pending_checks.update(restore_pending_checks())

    web_thread = threading.Thread(target=run_web, daemon=True)
    web_thread.start()

    bot_loop()
