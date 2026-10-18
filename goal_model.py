
import time
import threading
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
from ruscore import get_today_schedule, get_windows


# ============================================================
# СОСТОЯНИЕ БОТА
# ============================================================

p_game_cache = {}
sent_signals = {}
pending_checks = {}
last_scores = {}
recent_snapshots = {}

schedule_windows = []
schedule_updated_at = None

# ML: период обслуживания модели — 5 минут.
ML_MAINTENANCE_INTERVAL = 300
last_ml_maintenance = 0


# ============================================================
# OLD ML — ТЕНЕВОЕ ОБУЧЕНИЕ
# ============================================================

def maintain_ml(force=False):
    """
    Синхронизирует подтверждённые результаты и обучает модель
    при появлении новых размеченных примеров.

    Важно:
    ML не участвует в принятии решения об отправке сигнала.
    Стратегии и их пороги остаются без изменений.
    """
    global last_ml_maintenance

    now_ts = int(time.time())

    if (
        not force
        and now_ts - last_ml_maintenance < ML_MAINTENANCE_INTERVAL
    ):
        return

    last_ml_maintenance = now_ts

    try:
        # Переносим WIN/LOSE из основной базы в базу модели.
        synced = ml.sync_confirmed_results()

        if synced:
            print(
                f"🧠 OLD ML: синхронизировано результатов: {synced}",
                flush=True,
            )

        state = ml.status()

        total = int(state.get("total", 0))
        labeled = int(state.get("labeled", 0))
        wins = int(state.get("wins", 0))
        losses = int(state.get("losses", 0))
        trained = int(state.get("trained_samples", 0))

        print(
            f"🧠 OLD ML | примеров: {total} | "
            f"с результатом: {labeled} | "
            f"WIN: {wins} | LOSE: {losses} | "
            f"обучено на: {trained}",
            flush=True,
        )

        # Обучаем только при наличии минимального числа
        # подтверждённых исходов и новых результатов.
        if labeled >= 30 and labeled > trained:
            result = ml.train()

            if result.get("trained"):
                print(
                    f"✅ OLD ML: обучение завершено | "
                    f"примеры: {result.get('samples', 0)}",
                    flush=True,
                )
            else:
                print(
                    f"ℹ️ OLD ML: обучение пока не выполнено | "
                    f"{result.get('reason', 'нет данных')}",
                    flush=True,
                )

        elif labeled < 30:
            print(
                f"⏳ OLD ML: нужно минимум 30 подтверждённых "
                f"примеров; сейчас {labeled}",
                flush=True,
            )

        else:
            print(
                "ℹ️ OLD ML: новых результатов для обучения пока нет",
                flush=True,
            )

    except Exception as e:
        # Ошибка ML не должна останавливать основной бот.
        print(
            f"⚠️ OLD ML: ошибка обслуживания модели: {e}",
            flush=True,
        )


# ============================================================
# ПОЛУЧЕНИЕ LIVE-МАТЧЕЙ
# ============================================================

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

        print(
            f"🔎 1xlite HTTP: {response.status_code}",
            flush=True,
        )

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

        print(
            f"📊 Матчей в ответе API: {len(data)}",
            flush=True,
        )

        return [
            game
            for game in data
            if isinstance(game, dict)
        ]

    except Exception as e:
        print(
            f"❌ Ошибка получения матчей: {e}",
            flush=True,
        )
        return []


# ============================================================
# ОБРАБОТКА МАТЧЕЙ И СТРАТЕГИЙ
# ============================================================

def monitor():
    global p_game_cache, sent_signals, pending_checks
    global last_scores, recent_snapshots

    games = get_live_games()

    if not games:
        return

    now_ts = int(time.time())

    # Храним числовой ID и строковый ID.
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
            found_leagues[lid] = (
                found_leagues.get(lid, 0) + 1
            )

    if found_leagues:
        for lid, count in found_leagues.items():
            print(
                f"🏆 {LEAGUE_IDS[lid]}: {count}",
                flush=True,
            )
    else:
        print(
            "⚠️ В текущем ответе нет матчей из LEAGUE_IDS",
            flush=True,
        )

    for game in games:
        try:
            parsed = parse_game(game)

            if not parsed:
                continue

            gid = parsed["game_id"]

            update_match_history(
                parsed,
                now_ts,
                recent_snapshots,
            )

            if not common_ok(
                parsed,
                gid,
                now_ts,
                last_scores,
            ):
                continue

            # Порядок и пороги стратегий сохраняются.
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

                # ML здесь не блокирует и не разрешает сигналы.
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
            print(
                f"❌ Ошибка обработки отдельного матча "
                f"{game.get('id')}: {e}",
                flush=True,
            )

    # Очищаем старые антиспам-записи.
    sent_signals = {
        key: value
        for key, value in sent_signals.items()
        if now_ts - value.get("ts", now_ts) < 14400
    }


# ============================================================
# РАСПИСАНИЕ
# ============================================================

def refresh_schedule_if_needed():
    global schedule_windows, schedule_updated_at

    now = datetime.now(MOSCOW_TZ)

    if (
        schedule_updated_at
        and (now - schedule_updated_at).total_seconds()
        < SCHEDULE_REFRESH_SEC
    ):
        return

    try:
        schedule = get_today_schedule()
        schedule_windows = get_windows(schedule)
        schedule_updated_at = now

        print(
            f"📅 Расписание обновлено. "
            f"Окон: {len(schedule_windows)}",
            flush=True,
        )

    except Exception as e:
        print(
            f"⚠️ Не удалось обновить расписание: {e}",
            flush=True,
        )


def is_match_time():
    # Оставляем прежнее поведение:
    # мониторинг не зависит от расписания Ruscore.
    return True


# ============================================================
# ВЕБ-СЕРВЕР
# ============================================================

def run_web():
    try:
        web.app.run(
            host="0.0.0.0",
            port=3000,
            use_reloader=False,
            threaded=True,
        )

    except Exception as e:
        print(
            f"❌ Ошибка запуска сайта: {e}",
            flush=True,
        )


# ============================================================
# ГЛАВНЫЙ ЦИКЛ
# ============================================================

def bot_loop():
    print("🚀 LIVE-БОТ OLD ЗАПУЩЕН", flush=True)
    print(
        "🧠 OLD ML: теневой режим; "
        "модель не фильтрует сигналы",
        flush=True,
    )

    while True:
        try:
            now = datetime.now(MOSCOW_TZ)
            now_str = now.strftime("%H:%M")

            # Проверяем исходы независимо от режима мониторинга.
            check_pending_results(pending_checks)

            # Периодически синхронизируем результаты и обучаем ML.
            maintain_ml()

            if SLEEP_HOUR_START <= now.hour < SLEEP_HOUR_END:
                print(
                    f"😴 Ночной режим ({now_str}); "
                    "проверка результатов продолжается",
                    flush=True,
                )
                time.sleep(60)
                continue

            refresh_schedule_if_needed()

            if is_match_time():
                monitor()

            # Повторная проверка результатов после мониторинга.
            check_pending_results(pending_checks)

            # Если результат был подтверждён во время второй
            # проверки, обслуживание ML выполнится по расписанию.
            time.sleep(UPDATE_INTERVAL)

        except KeyboardInterrupt:
            print("⏹️ Остановка по команде", flush=True)
            break

        except Exception as e:
            print(
                f"❌ Ошибка основного цикла: {e}",
                flush=True,
            )

            import traceback
            traceback.print_exc()

            try:
                check_pending_results(pending_checks)
            except Exception as check_error:
                print(
                    f"❌ Ошибка проверки результатов: "
                    f"{check_error}",
                    flush=True,
                )

            # Ошибки ML обрабатываются отдельно.
            try:
                maintain_ml()
            except Exception as ml_error:
                print(
                    f"⚠️ OLD ML: ошибка обслуживания: {ml_error}",
                    flush=True,
                )

            time.sleep(30)


# ============================================================
# ЗАПУСК
# ============================================================

if __name__ == "__main__":
    db.init_db()

    # Восстанавливаем незавершённые сигналы из базы.
    pending_checks.update(restore_pending_checks())

    # При запуске сразу синхронизируем результаты.
    # Если накоплены новые размеченные данные, модель обучится.
    maintain_ml(force=True)

    web_thread = threading.Thread(
        target=run_web,
        daemon=True,
    )
    web_thread.start()

    bot_loop()