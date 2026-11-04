import time
from parse_nb_bet_html import parse_nb_bet_html
import threading
import traceback
from datetime import datetime

import requests
import web
import database as db
import goal_model as ml  # <--- Добавлен импорт модели для синхронизации

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

    # Очищаем старые антиспам-записи.
    # Активные проверки результатов не удаляем.
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
        and (now - schedule_updated_at).total_seconds()
        < SCHEDULE_REFRESH_SEC
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
        print(
            f"⚠️ Не удалось обновить расписание: {e}",
            flush=True,
        )


def is_match_time():
    # Сохраняем прежнее поведение:
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


def retry_telegram_results():
    """
    Повторно обновляет завершённые результаты в Telegram.

    Ошибка редактирования сообщения не должна останавливать
    мониторинг матчей и проверку остальных результатов.
    """
    try:
        retry_pending_telegram_updates()

    except Exception as e:
        print(
            f"❌ Ошибка повторного обновления Telegram: {e}",
            flush=True,
        )
        traceback.print_exc()


def check_results_safely():
    """Проверяет результаты матчей, не останавливая основной цикл."""
    try:
        check_pending_results(pending_checks)

    except Exception as e:
        print(
            f"❌ Ошибка проверки результатов: {e}",
            flush=True,
        )
        traceback.print_exc()


def bot_loop():
    print("🚀 PREMATCH-БОТ ЗАПУЩЕН (умная модель на nb-bet)", flush=True)
    while True:
        try:
            now = datetime.now(MOSCOW_TZ)
            print(f"\n🔄 [{now:%H:%M:%S}] Загрузка линии...", flush=True)

            games = get_prematch_games()
            count_ok = 0
            count_value = 0

            for game in games:
                parsed = parse_prematch_game(game)
                if not parsed:
                    continue

                # Фильтр: специальные/сборные
                t1 = parsed["team1"].lower()
                t2 = parsed["team2"].lower()
                if ("специальное" in t1 or "специальное" in t2
                        or t1 in ("хозяева", "гости") or t2 in ("хозяева", "гости")):
                    continue

                # Фильтр: тотал 2.5
                tb_25 = parsed["odds"]["TB"].get(2.5)
                if not tb_25 or not tb_25.get("over"):
                    continue

                count_ok += 1

                # Пытаемся достать данные с nb-bet
                nb_data = None
                if "Славия" in parsed["team1"] and "Арсенал" in parsed["team2"]:
                    try:
                        nb_data = parse_nb_bet_html("match_page.html")
                    except Exception as e:
                        print(f"⚠️ Ошибка парсинга nb-bet: {e}", flush=True)

                if nb_data and nb_data["avg_scored_home"] is not None:
                    # УМНАЯ модель — используем средние голы команд
                    lam_home = (nb_data["avg_scored_home"] + nb_data["avg_conceded_away"]) / 2
                    lam_away = (nb_data["avg_scored_away"] + nb_data["avg_conceded_home"]) / 2
                    lam_total = lam_home + lam_away

                    p_model = prob_over(2.5, lam_total)
                    coef_over = tb_25["over"]
                    p_book = 1 / coef_over
                    edge = p_model - p_book

                    print(
                        f"\n⚽ {parsed['team1']} — {parsed['team2']} (данные с nb-bet)"
                        f"\n   Лига: {parsed['liga']}"
                        f"\n   Начало: {parsed['start_time']:%d.%m %H:%M}"
                        f"\n   Кэф ТБ 2.5: {coef_over}"
                        f"\n   Средние голы: {parsed['team1']} — забивает {nb_data['avg_scored_home']}, пропускает {nb_data['avg_conceded_home']}"
                        f"\n                 {parsed['team2']} — забивает {nb_data['avg_scored_away']}, пропускает {nb_data['avg_conceded_away']}"
                        f"\n   Ожидаемые голы (lam): {lam_home:.2f} + {lam_away:.2f} = {lam_total:.2f}"
                        f"\n   Модель: {p_model:.1%} | Букмекер: {p_book:.1%} | Edge: {edge:+.1%}",
                        flush=True
                    )
                    if edge > 0.05:
                        count_value += 1
                        print(f"   🔥 ВАЛУЙ", flush=True)
                else:
                    # Матч без данных с nb-bet — пропускаем (не считаем)
                    print(
                        f"ℹ️ {parsed['team1']} — {parsed['team2']}: нет данных с nb-bet",
                        flush=True
                    )

            print(
                f"\n✅ Матчей с ТБ 2.5: {count_ok} | валуев: {count_value}",
                flush=True
            )
            print("💤 Спим 5 минут...", flush=True)
            time.sleep(300)

        except KeyboardInterrupt:
            print("⏹️ Остановка", flush=True)
            break
        except Exception as e:
            print(f"❌ Ошибка цикла: {e}", flush=True)
            traceback.print_exc()
            time.sleep(60)


if __name__ == "__main__":
    db.init_db()

    # Восстанавливаем незавершённые прогнозы из базы
    # до начала основного цикла.
    pending_checks.update(restore_pending_checks())

    web_thread = threading.Thread(
        target=run_web,
        daemon=True,
    )
    web_thread.start()

    bot_loop()
