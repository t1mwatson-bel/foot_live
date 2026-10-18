
import time
import threading
from datetime import datetime

import requests
import web
import database as db

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
)
from ruscore import get_today_schedule, get_windows


p_game_cache = {}
sent_signals = {}
pending_checks = {}
last_scores = {}
recent_snapshots = {}
schedule_windows = []
schedule_updated_at = None


def get_live_games():
    try:
        url = f"{BASE_URL}/service-api/main-live-feed/v3/games1x2"
        params = {
            "cfView": 3,
            "count": 40,
            "fcountry": 1,
            "gr": 2336,
            "grMode": 4,
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
            print(
                f"❌ Ошибка 1xlite: {response.text[:200]}",
                flush=True,
            )
            return []

        data = response.json()

        if not isinstance(data, list):
            print(
                f"❌ 1xlite вернул неожиданный тип: {type(data)}",
                flush=True,
            )
            return []

        print(f"📊 Матчей в ответе API: {len(data)}", flush=True)
        return [game for game in data if isinstance(game, dict)]

    except Exception as e:
        print(f"❌ Ошибка получения матчей: {e}", flush=True)
        return []


def monitor():
    global p_game_cache, sent_signals, pending_checks
    global last_scores, recent_snapshots

    games = get_live_games()
    if not games:
        return

    now_ts = int(time.time())

    # Храним оба варианта ID: число и строку.
    # Это защищает от несовпадения типа game_id при поиске коэффициента.
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

            update_match_history(parsed, now_ts, recent_snapshots)

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
                    # Не создаём второй сигнал по тому же матчу
                    # в рамках одного прохода.
                    break

        except Exception as e:
            print(
                f"❌ Ошибка обработки отдельного матча "
                f"{game.get('id')}: {e}",
                flush=True,
            )

    # Старые антиспам-записи очищаем, но активные проверки
    # не удаляем из pending_checks.
    sent_signals = {
        key: value
        for key, value in sent_signals.items()
        if now_ts - value.get("ts", now_ts) < 14400
    }


def refresh_schedule_if_needed():
    global schedule_windows, schedule_updated_at

    now = datetime.now(MOSCOW_TZ)

    if (
        schedule_updated_at
        and (now - schedule_updated_at).total_seconds() < SCHEDULE_REFRESH_SEC
    ):
        return

    try:
        schedule = get_today_schedule()
        schedule_windows = get_windows(schedule)
        schedule_updated_at = now
        print(
            f"📅 Расписание обновлено. Окон: {len(schedule_windows)}",
            flush=True,
        )
    except Exception as e:
        print(f"⚠️ Не удалось обновить расписание: {e}", flush=True)


def is_match_time():
    # Сохраняем прежнее поведение текущей версии бота:
    # мониторинг API не зависит от расписания Ruscore.
    return True


def run_web():
    """Запускает сайт в отдельном потоке."""
    try:
        web.app.run(
            host="0.0.0.0",
            port=3000,
            use_reloader=False,
            threaded=True,
        )
    except Exception as e:
        print(f"❌ Ошибка запуска сайта: {e}", flush=True)


def bot_loop():
    print("🚀 LIVE-БОТ OLD ЗАПУЩЕН", flush=True)

    while True:
        try:
            now = datetime.now(MOSCOW_TZ)
            now_str = now.strftime("%H:%M")

            # Проверки результатов запускаются независимо от мониторинга.
            check_pending_results(pending_checks)

            if SLEEP_HOUR_START <= now.hour < SLEEP_HOUR_END:
                print(f"😴 Ночной режим ({now_str}); проверка результатов продолжается", flush=True)
                time.sleep(60)
                continue

            refresh_schedule_if_needed()

            if is_match_time():
                monitor()

            # Повторная проверка после обработки текущих матчей.
            check_pending_results(pending_checks)

            time.sleep(UPDATE_INTERVAL)

        except KeyboardInterrupt:
            print("⏹️ Остановка по команде", flush=True)
            break

        except Exception as e:
            print(f"❌ Ошибка основного цикла: {e}", flush=True)
            import traceback
            traceback.print_exc()

            # Не оставляем результаты без проверки из-за ошибки цикла.
            try:
                check_pending_results(pending_checks)
            except Exception as check_error:
                print(
                    f"❌ Ошибка проверки результатов: {check_error}",
                    flush=True,
                )

            time.sleep(30)


if __name__ == "__main__":
    db.init_db()

    # Восстанавливаем незавершённые прогнозы до начала основного цикла.
    pending_checks.update(restore_pending_checks())

    web_thread = threading.Thread(target=run_web, daemon=True)
    web_thread.start()

    bot_loop()