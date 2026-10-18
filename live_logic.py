import time
import json
import goal_model as ml
import re
import requests
from datetime import datetime, timedelta

from config import *
from telegram_bot import send_telegram, edit_telegram, format_with_result
from stats_parser import *
from ruscore import fetch_ruscore_events, find_match, parse_score_for_match
import database as db


# ============================================================
# ЖУРНАЛ РЕЗУЛЬТАТОВ
# ============================================================

def log_result_record(record):
    try:
        with open(RESULTS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except Exception as e:
        print(f"⚠️ Не удалось записать {RESULTS_FILE}: {e}", flush=True)


# ============================================================
# ПОЛУЧЕНИЕ РЕЗУЛЬТАТОВ ИЗ 1XLITE
# ============================================================

def fetch_1xlite_live_games():
    """
    Получает текущую live-ленту.
    Используется для проверки уже отправленных сигналов.
    """
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

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            params=params,
            timeout=15,
        )

        if response.status_code != 200:
            print(
                f"⚠️ 1xLite live: HTTP {response.status_code}",
                flush=True,
            )
            return None

        data = response.json()

        if isinstance(data, list):
            return [g for g in data if isinstance(g, dict)]

        # Некоторые варианты API возвращают объект-обёртку.
        if isinstance(data, dict):
            for field in ("Value", "value", "games", "Games", "events", "Events"):
                value = data.get(field)
                if isinstance(value, list):
                    return [g for g in value if isinstance(g, dict)]

        print("⚠️ 1xLite live: неизвестный формат ответа", flush=True)
        return None

    except Exception as e:
        print(f"⚠️ Ошибка запроса live-ленты 1xLite: {e}", flush=True)
        return None


def fetch_1xlite_game_by_id(game_id):
    """
    Запрашивает конкретный матч по ID.
    Нужен, если матч уже исчез из ограниченной live-ленты.
    """
    url = f"{BASE_URL}/service-api/LiveFeed/GetGameZip"

    params = {
        "id": str(game_id),
        "lng": "ru",
        "cfview": 0,
        "isSubGames": "true",
        "GroupEvents": "true",
        "allEventsGroupSubGames": "true",
        "countevents": 250,
        "partner": 36,
    }

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            params=params,
            timeout=12,
        )

        if response.status_code != 200:
            print(
                f"⚠️ GetGameZip: HTTP {response.status_code}, ID={game_id}",
                flush=True,
            )
            return None

        data = response.json()

        if not isinstance(data, dict):
            print(
                f"⚠️ GetGameZip: ответ не является объектом, ID={game_id}",
                flush=True,
            )
            return None

        game = data.get("Value")

        if isinstance(game, dict):
            game["_requested_id"] = str(game_id)
            return game

        # На случай, если API возвращает сам матч без обёртки Value.
        if any(k in data for k in ("SC", "scores", "id", "ID")):
            data["_requested_id"] = str(game_id)
            return data

        print(
            f"⚠️ GetGameZip не вернул данные матча, ID={game_id}",
            flush=True,
        )
        return None

    except Exception as e:
        print(f"⚠️ Ошибка GetGameZip для ID={game_id}: {e}", flush=True)
        return None


def find_1xlite_game(games, game_id):
    """Ищет матч по точному ID."""
    if not games:
        return None

    target = str(game_id)

    for game in games:
        if not isinstance(game, dict):
            continue

        candidates = (
            game.get("id"),
            game.get("ID"),
            game.get("I"),
            game.get("_requested_id"),
        )

        if any(value is not None and str(value) == target for value in candidates):
            return game

    return None


def _parse_score_value(value):
    """Пытается разобрать счёт из строки или словаря."""
    if isinstance(value, str):
        match = re.search(
            r"^\s*(\d+)\s*[-:]\s*(\d+)\s*$",
            value,
        )
        if match:
            return int(match.group(1)), int(match.group(2))

    if isinstance(value, dict):
        home = value.get("home", value.get("s1", value.get("S1")))
        away = value.get("away", value.get("s2", value.get("S2")))

        try:
            if home is not None and away is not None:
                return int(home), int(away)
        except (TypeError, ValueError):
            pass

    return None, None


def parse_1xlite_score(game):
    """
    Разбирает счёт из разных известных вариантов ответа 1xLite.
    Не принимает отсутствие счёта за 0:0.
    """
    if not isinstance(game, dict):
        return None, None

    # Вариант обычной live-ленты.
    scores = game.get("scores") or {}

    if isinstance(scores, dict):
        for key in ("fullScore", "score", "currentScore", "result"):
            s1, s2 = _parse_score_value(scores.get(key))
            if s1 is not None and s2 is not None:
                return s1, s2

        # Некоторые ответы хранят команды и счёт непосредственно в scores.
        s1, s2 = _parse_score_value(scores)
        if s1 is not None and s2 is not None:
            return s1, s2

    # Вариант GetGameZip: SC.FS.S1 / SC.FS.S2.
    sc = game.get("SC") or {}

    if isinstance(sc, dict):
        fs = sc.get("FS") or {}

        if isinstance(fs, dict):
            try:
                s1 = fs.get("S1")
                s2 = fs.get("S2")

                if s1 is not None and s2 is not None:
                    return int(s1), int(s2)
            except (TypeError, ValueError):
                pass

        # Резервные поля, встречающиеся в отдельных ответах.
        for key in ("FS", "S", "score", "Score"):
            s1, s2 = _parse_score_value(sc.get(key))
            if s1 is not None and s2 is not None:
                return s1, s2

    # Резервные прямые поля.
    for key in ("fullScore", "score", "Score", "result"):
        s1, s2 = _parse_score_value(game.get(key))
        if s1 is not None and s2 is not None:
            return s1, s2

    return None, None


# ============================================================
# ПРОВЕРКА ЗАВЕРШЕНИЯ МАТЧА
# ============================================================

def _collect_status_text(value):
    """Собирает текстовые значения статусов из вложенных объектов."""
    parts = []

    if isinstance(value, dict):
        for key, nested in value.items():
            # Не используем содержимое счёта для определения статуса.
            if str(key).lower() in {
                "fs", "score", "scores", "s1", "s2", "value"
            }:
                if str(key).lower() in {"s1", "s2"}:
                    continue

            if isinstance(nested, (dict, list)):
                parts.extend(_collect_status_text(nested))
            elif nested is not None and isinstance(nested, str):
                parts.append(nested)

    elif isinstance(value, list):
        for nested in value:
            parts.extend(_collect_status_text(nested))

    return parts


def is_finished_status(status):
    """Распознаёт только явные текстовые признаки завершения матча."""
    if isinstance(status, dict):
        parts = _collect_status_text(status)
        text = " ".join(parts)
    else:
        text = str(status or "")

    text = text.lower().replace("ё", "е")
    text = " ".join(text.replace("_", " ").replace("-", " ").split())

    finished_values = {
        "finished",
        "ended",
        "ft",
        "final",
        "complete",
        "completed",
        "full time",
        "match finished",
        "match ended",
        "завершен",
        "завершена",
        "матч завершен",
        "окончен",
        "окончена",
        "закончен",
        "закончена",
        "матч окончен",
        "матч закончен",
        "игра завершена",
        "завершение матча",
    }

    if text in finished_values:
        return True

    # Не используем слишком широкие проверки вроде наличия слова "end"
    # внутри любого другого текста.
    prefixes = (
        "finished ",
        "ended ",
        "completed ",
        "full time ",
        "match finished ",
        "match ended ",
        "завершен ",
        "завершена ",
        "матч завершен ",
        "окончен ",
        "окончена ",
        "закончен ",
        "закончена ",
    )

    return text.startswith(prefixes)


def is_1xlite_finished(game):
    """
    Определяет завершение только по явным текстовым статусам.
    Числовой SC.I сам по себе не трактуем как финальный статус:
    без подтверждённой расшифровки это может привести к ложному проигрышу.
    """
    if not isinstance(game, dict):
        return False

    scores = game.get("scores") or {}
    sc = game.get("SC") or {}

    status_values = [
        game.get("status"),
        game.get("statusName"),
        game.get("statusText"),
        game.get("statusLine"),
        game.get("statusLineStr"),
        game.get("periodName"),
        game.get("currentPeriodName"),
    ]

    if isinstance(scores, dict):
        status_values.extend([
            scores.get("status"),
            scores.get("statusName"),
            scores.get("statusText"),
            scores.get("statusLine"),
            scores.get("statusLineStr"),
            scores.get("currentPeriodName"),
        ])

    if isinstance(sc, dict):
        status_values.extend([
            sc.get("status"),
            sc.get("statusName"),
            sc.get("statusText"),
            sc.get("periodName"),
            sc.get("currentPeriodName"),
        ])

    for value in status_values:
        if value is not None and is_finished_status(value):
            return True

    # Отдельные API могут отдавать логические флаги завершения.
    for container in (game, scores, sc):
        if not isinstance(container, dict):
            continue

        for field in ("isFinished", "finished", "isEnded", "ended"):
            value = container.get(field)

            if value is True or value == 1:
                return True

            if isinstance(value, str):
                if value.strip().lower() in ("true", "yes", "finished", "ended"):
                    return True

    return False


def get_ruscore_status(event):
    """Извлекает статус Ruscore из разных вариантов структуры."""
    if not isinstance(event, dict):
        return ""

    parts = []

    for key in (
        "status",
        "statusName",
        "statusText",
        "state",
        "period",
        "periodName",
        "matchStatus",
    ):
        value = event.get(key)

        if isinstance(value, dict):
            for subkey in ("label", "name", "text", "value", "short"):
                nested = value.get(subkey)
                if isinstance(nested, str):
                    parts.append(nested)
        elif isinstance(value, str):
            parts.append(value)

    return " ".join(parts)


# ============================================================
# ВОССТАНОВЛЕНИЕ ПРОВЕРОК ПОСЛЕ ПЕРЕЗАПУСКА
# ============================================================

def restore_pending_checks():
    """Восстанавливает ожидающие сигналы из базы данных."""
    restored = {}
    now = int(time.time())

    try:
        rows = db.get_pending_live_signals()
    except Exception as e:
        print(f"❌ Не удалось загрузить проверки из БД: {e}", flush=True)
        return restored

    for row in rows:
        key = str(row.get("game_id") or "").strip()

        if not key:
            continue

        match_name = str(row.get("match_name") or "").strip()
        team1 = str(row.get("team1") or "").strip()
        team2 = str(row.get("team2") or "").strip()

        if not team1 or not team2:
            for separator in (" — ", " – ", " - ", " vs ", " VS "):
                if separator in match_name:
                    parts = match_name.split(separator, 1)

                    if len(parts) == 2:
                        team1 = team1 or parts[0].strip()
                        team2 = team2 or parts[1].strip()
                        break

        old_s1 = row.get("old_s1")
        old_s2 = row.get("old_s2")

        if old_s1 is None or old_s2 is None:
            raw_score = str(row.get("score") or "").strip()
            match = re.search(
                r"^\s*(\d+)\s*[-:]\s*(\d+)\s*$",
                raw_score,
            )

            if match:
                old_s1 = int(match.group(1))
                old_s2 = int(match.group(2))

        if old_s1 is None or old_s2 is None:
            print(
                f"⚠️ Сигнал {key}: исходный счёт отсутствует; "
                "автоматическая проверка невозможна",
                flush=True,
            )
            continue

        try:
            old_s1 = int(old_s1)
            old_s2 = int(old_s2)
        except (TypeError, ValueError):
            print(f"⚠️ Сигнал {key}: некорректный исходный счёт", flush=True)
            continue

        sent_at = int(row.get("sent_at") or now)
        signal_ts = int(row.get("signal_ts") or sent_at)

        date_str = row.get("date_str")

        if not date_str:
            date_str = datetime.fromtimestamp(
                signal_ts,
                MOSCOW_TZ,
            ).strftime("%Y-%m-%d")

        message_id = row.get("message_id")

        try:
            message_id = int(message_id) if message_id else None
        except (TypeError, ValueError):
            message_id = None

        try:
            attempts = int(row.get("attempts") or 0)
        except (TypeError, ValueError):
            attempts = 0

        try:
            check_after = int(row.get("check_after") or now)
        except (TypeError, ValueError):
            check_after = now

        info = {
            "team1": team1,
            "team2": team2,
            "match": match_name or (
                f"{team1} — {team2}"
                if team1 and team2
                else f"Матч {key}"
            ),
            "date_str": date_str,
            "old_s1": old_s1,
            "old_s2": old_s2,
            "minute": int(row.get("minute") or 0),
            "signal_ts": signal_ts,
            "message_id": message_id,
            "base_text": row.get("base_text") or "",
            "strategy": row.get("strategy") or "не указана",
            "odd": row.get("odds"),
            "check_after": min(check_after, now),
            "attempts": attempts,
        }

        restored[key] = info

        try:
            persist_check(key, info)
        except Exception as e:
            print(
                f"⚠️ Не удалось обновить данные сигнала {key}: {e}",
                flush=True,
            )

        if not team1 or not team2:
            print(
                f"⚠️ Сигнал {key}: не хватает названий команд "
                "для поиска в Ruscore",
                flush=True,
            )

    print(
        f"♻️ Восстановлено ожидающих проверок: {len(restored)}",
        flush=True,
    )

    return restored


def persist_check(game_id, info):
    try:
        return db.update_live_signal_check(
            str(game_id),
            {
                "team1": info.get("team1"),
                "team2": info.get("team2"),
                "old_s1": info.get("old_s1"),
                "old_s2": info.get("old_s2"),
                "date_str": info.get("date_str"),
                "signal_ts": info.get("signal_ts"),
                "message_id": info.get("message_id"),
                "base_text": info.get("base_text"),
                "check_after": info.get("check_after"),
                "attempts": info.get("attempts", 0),
            },
        )
    except Exception as e:
        print(
            f"❌ Не удалось сохранить проверку {game_id}: {e}",
            flush=True,
        )
        return False


def _schedule_retry(key, info, now, delay=None):
    """Планирует следующую попытку проверки."""
    try:
        info["attempts"] = int(info.get("attempts", 0)) + 1
    except (TypeError, ValueError):
        info["attempts"] = 1

    if delay is None:
        delay = CHECK_REPEAT_AFTER

    # После большого количества неудачных попыток проверяем реже,
    # но не переводим сигнал автоматически в проигрыш.
    if info["attempts"] >= CHECK_MAX_ATTEMPTS:
        delay = max(int(delay), 3600)

    info["check_after"] = now + max(1, int(delay))
    persist_check(key, info)


# ============================================================
# ФИКСАЦИЯ РЕЗУЛЬТАТА
# ============================================================

def _finish_signal(key, info, won, score1, score2, now):
    """Сохраняет результат в БД, Telegram и JSONL."""
    final_score = f"{score1}-{score2}"

    if won:
        elapsed = max(
            0,
            (now - int(info.get("signal_ts") or now)) // 60,
        )

        result_line = (
            "✅ <b>ЗАШЛО</b>\n"
            f"📊 Было: {info.get('old_s1', 0)}-"
            f"{info.get('old_s2', 0)} "
            f"({info.get('minute', 0)}')\n"
            f"📊 Стало: {final_score}\n"
            f"⏱ ~{elapsed} мин"
        )

        outcome = "hit"
        label = "ЗАШЛО"

    else:
        result_line = (
            "❌ <b>НЕ ЗАШЛО</b>\n"
            f"📊 Итог: {final_score}\n"
            "ℹ️ После сигнала новых голов не было."
        )

        outcome = "miss"
        label = "НЕ ЗАШЛО"

    try:
        saved = db.update_live_result(
            str(key),
            bool(won),
            final_score=final_score,
        )
    except Exception as e:
        print(f"❌ Ошибка записи результата в БД: {e}", flush=True)
        saved = False

    if not saved:
        print(
            f"❌ База не подтвердила результат: "
            f"{info.get('match')} ({key}); повторим проверку",
            flush=True,
        )

        _schedule_retry(key, info, now)
        return False

    if info.get("message_id") and info.get("base_text"):
        try:
            edit_telegram(
                info["message_id"],
                format_with_result(info["base_text"], result_line),
            )
        except Exception as e:
            print(
                f"⚠️ Результат сохранён, но Telegram не обновлён: {e}",
                flush=True,
            )
    else:
        print(
            f"ℹ️ Сигнал {key}: нет message_id или base_text; "
            "результат сохранён только в базе",
            flush=True,
        )

    log_result_record({
        "record_type": "result",
        "game_id": str(key),
        "timestamp": now,
        "match": info.get("match"),
        "strategy": info.get("strategy"),
        "odd": info.get("odd"),
        "outcome": outcome,
        "final_score": final_score,
    })

    print(
        f"{'✅' if won else '❌'} {label}: "
        f"{info.get('match')} | итог {final_score}",
        flush=True,
    )

    return True


# ============================================================
# ВСПОМОГАТЕЛЬНАЯ ПРОВЕРКА СЧЁТА
# ============================================================

def _has_new_goal(score1, score2, old_s1, old_s2):
    """Проверяет, увеличился ли счёт хотя бы одной команды."""
    if score1 is None or score2 is None:
        return False

    try:
        return int(score1) > int(old_s1) or int(score2) > int(old_s2)
    except (TypeError, ValueError):
        return False


def _get_dates_to_check(info, now):
    """Возвращает дату сигнала и соседние даты для поиска матча."""
    dates = []

    primary_date = info.get("date_str")

    if primary_date:
        dates.append(str(primary_date))

    try:
        signal_ts = int(info.get("signal_ts") or now)
        signal_date = datetime.fromtimestamp(
            signal_ts,
            MOSCOW_TZ,
        ).date()

        for offset in (0, -1, 1):
            candidate = (
                signal_date + timedelta(days=offset)
            ).strftime("%Y-%m-%d")

            if candidate not in dates:
                dates.append(candidate)

    except Exception:
        pass

    if not dates:
        dates.append(
            datetime.now(MOSCOW_TZ).strftime("%Y-%m-%d")
        )

    return dates


# ============================================================
# ОСНОВНАЯ ПРОВЕРКА РЕЗУЛЬТАТОВ
# ============================================================

def check_pending_results(pending_checks):
    if not pending_checks:
        return

    now = int(time.time())
    due_keys = []

    for key, info in list(pending_checks.items()):
        try:
            check_after = int(info.get("check_after") or 0)
        except (TypeError, ValueError):
            check_after = 0

        if now >= check_after:
            due_keys.append(str(key))

    if not due_keys:
        return

    print(
        f"🔍 Проверка результатов: ожидают {len(due_keys)} матч(ей)",
        flush=True,
    )

    # Один общий запрос live-ленты на весь цикл.
    live_games = fetch_1xlite_live_games()

    for key in due_keys:
        info = pending_checks.get(key)

        if not info:
            continue

        match_name = info.get("match") or key

        try:
            old_s1 = int(info["old_s1"])
            old_s2 = int(info["old_s2"])
        except (KeyError, TypeError, ValueError):
            print(
                f"⚠️ {match_name}: нет корректного исходного счёта",
                flush=True,
            )
            _schedule_retry(key, info, now)
            continue

        score1 = score2 = None
        finished = False
        live_game = find_1xlite_game(live_games, key)

        # ----------------------------------------------------
        # 1. 1XLITE LIVE-ЛЕНТА
        # ----------------------------------------------------

        if live_game is not None:
            score1, score2 = parse_1xlite_score(live_game)
            finished = is_1xlite_finished(live_game)

            print(
                f"📡 1xLite live: {match_name} | "
                f"счёт={score1}-{score2} | "
                f"завершён={finished}",
                flush=True,
            )

            if _has_new_goal(score1, score2, old_s1, old_s2):
                if _finish_signal(
                    key, info, True, score1, score2, now
                ):
                    pending_checks.pop(key, None)
                continue

            if (
                score1 is not None
                and score2 is not None
                and finished
            ):
                if _finish_signal(
                    key, info, False, score1, score2, now
                ):
                    pending_checks.pop(key, None)
                continue

        # ----------------------------------------------------
        # 2. ОТДЕЛЬНЫЙ ЗАПРОС МАТЧА ПО ID
        # ----------------------------------------------------
        # Live-лента ограничена количеством игр. Матч мог исчезнуть
        # из неё, поэтому пробуем получить его напрямую.
        if live_game is None or score1 is None or score2 is None or not finished:
            print(
                f"🔎 GetGameZip: запрашиваем матч ID={key} "
                f"({match_name})",
                flush=True,
            )

            detailed_game = fetch_1xlite_game_by_id(key)

            if detailed_game is not None:
                detail_s1, detail_s2 = parse_1xlite_score(detailed_game)
                detail_finished = is_1xlite_finished(detailed_game)

                sc = detailed_game.get("SC") or {}
                raw_status = sc.get("I") if isinstance(sc, dict) else None

                print(
                    f"📡 1xLite GetGameZip: {match_name} | "
                    f"счёт={detail_s1}-{detail_s2} | "
                    f"завершён={detail_finished} | "
                    f"SC.I={raw_status!r}",
                    flush=True,
                )

                # Если прямой запрос вернул счёт, используем его.
                if detail_s1 is not None and detail_s2 is not None:
                    score1, score2 = detail_s1, detail_s2
                    finished = detail_finished

                    if _has_new_goal(
                        score1, score2, old_s1, old_s2
                    ):
                        if _finish_signal(
                            key, info, True, score1, score2, now
                        ):
                            pending_checks.pop(key, None)
                        continue

                    if finished:
                        if _finish_signal(
                            key, info, False, score1, score2, now
                        ):
                            pending_checks.pop(key, None)
                        continue

        # ----------------------------------------------------
        # 3. RUSCORE — РЕЗЕРВНЫЙ ИСТОЧНИК
        # ----------------------------------------------------
        team1 = str(info.get("team1") or "").strip()
        team2 = str(info.get("team2") or "").strip()

        if team1 and team2:
            event = None
            event_date = None

            for date_str in _get_dates_to_check(info, now):
                try:
                    events = fetch_ruscore_events(date_str)
                except Exception as e:
                    print(
                        f"⚠️ Ошибка Ruscore ({date_str}): {e}",
                        flush=True,
                    )
                    continue

                if not events:
                    continue

                try:
                    candidate = find_match(events, team1, team2)
                except Exception as e:
                    print(
                        f"⚠️ Ошибка поиска Ruscore: {e}",
                        flush=True,
                    )
                    candidate = None

                if candidate:
                    event = candidate
                    event_date = date_str
                    break

            if event:
                try:
                    r_score1, r_score2 = parse_score_for_match(
                        event,
                        team1,
                        team2,
                    )
                except Exception as e:
                    print(
                        f"⚠️ Ошибка разбора счёта Ruscore: {e}",
                        flush=True,
                    )
                    r_score1 = r_score2 = None

                status_text = get_ruscore_status(event)
                r_finished = is_finished_status(status_text)

                print(
                    f"📋 Ruscore: {match_name} | "
                    f"дата={event_date} | "
                    f"счёт={r_score1}-{r_score2} | "
                    f"статус={status_text!r} | "
                    f"завершён={r_finished}",
                    flush=True,
                )

                try:
                    if r_score1 is not None and r_score2 is not None:
                        r_score1 = int(r_score1)
                        r_score2 = int(r_score2)
                except (TypeError, ValueError):
                    r_score1 = r_score2 = None

                if _has_new_goal(
                    r_score1, r_score2, old_s1, old_s2
                ):
                    if _finish_signal(
                        key, info, True, r_score1, r_score2, now
                    ):
                        pending_checks.pop(key, None)
                    continue

                if (
                    r_score1 is not None
                    and r_score2 is not None
                    and r_finished
                ):
                    if _finish_signal(
                        key, info, False, r_score1, r_score2, now
                    ):
                        pending_checks.pop(key, None)
                    continue

            else:
                print(
                    f"🔎 Матч не найден в Ruscore: {match_name}",
                    flush=True,
                )

        else:
            print(
                f"⚠️ {match_name}: нет названий обеих команд "
                "для поиска в Ruscore",
                flush=True,
            )

        # ----------------------------------------------------
        # 4. НЕТ ПОДТВЕРЖДЁННОГО ИСХОДА
        # ----------------------------------------------------
        # Не считаем отсутствие матча или статуса проигрышем.
        print(
            f"⏳ Ожидание: {match_name}. "
            "Исход пока не подтверждён; будет повторная проверка.",
            flush=True,
        )

        _schedule_retry(key, info, now)


# ============================================================
# ФОРМАТ СИГНАЛА
# ============================================================

def format_signal_multi(p, strategies, odd):
    total = p["s1"] + p["s2"]
    tb1 = total + 0.5
    trend = p.get("trend", {})

    if trend.get("available"):
        trend_line = (
            f"📈 За 5–10 мин: xG +{trend['xg_delta']:.2f}, "
            f"створ +{trend['shots_on_delta']}, "
            f"удары +{trend['shots_delta']}\n"
        )
    else:
        trend_line = "📈 Динамика: собирается история\n"

    odd_line = (
        f"💰 Кэф ТБ {tb1}: <b>{odd:.2f}</b>"
        if odd is not None
        else "💰 Кэф: недоступен"
    )

    return (
        "🎯 <b>СИГНАЛ OLD — следующий гол до конца матча</b>\n"
        f"{p['league']}\n"
        f"⚽ <b>{p['match']}</b>\n"
        f"📊 Счёт: <b>{p['score']}</b> | ⏱ {p['minute']}'\n"
        f"🎯 xG: {p['xg1']:.2f} — {p['xg2']:.2f}\n"
        f"🥅 Удары: {p['shots_all1']} — {p['shots_all2']} "
        f"(в створ {p['shots_on1']} — {p['shots_on2']})\n"
        f"⚔️ Опасные атаки: {p['att1']} — {p['att2']}\n"
        f"🚩 Углы: {p['corners1']} — {p['corners2']}\n"
        f"{trend_line}{odd_line}\n"
        f"🧠 Фильтры: {', '.join(strategies)}\n"
        "💡 Цель: хотя бы один гол до финального свистка; "
        "это оценка, не гарантия."
    )


# ============================================================
# ОТПРАВКА СИГНАЛА
# ============================================================

def try_send_signal(
    p, strategy, now_ts, p_game_cache, sent_signals, pending_checks
):
    gid = p["game_id"]
    key = str(gid)

    if db.is_live_signal_sent(key):
        return False

    game = p_game_cache.get(gid) or p_game_cache.get(key) or {}

    odd = get_odd_total(game, p["s1"] + p["s2"])

    if odd is None:
        print(
            f"⚠️ Нет коэффициента для {p['match']}; сигнал не отправлен",
            flush=True,
        )
        return False

    try:
        odd = float(odd)
    except (TypeError, ValueError):
        return False

    if odd < strategy["min_odd"]:
        return False

    text = format_signal_multi(
        p,
        [f"{strategy['emoji']} {strategy['strategy']}"],
        odd,
    )

    try:
        msg_id = send_telegram(text)
    except Exception as e:
        print(f"❌ Ошибка отправки Telegram: {e}", flush=True)
        return False

    if not msg_id:
        print(
            f"⚠️ Telegram не подтвердил отправку: {p['match']}",
            flush=True,
        )
        return False

    today = datetime.now(MOSCOW_TZ).strftime("%Y-%m-%d")
    check_after = now_ts + CHECK_FIRST_AFTER

    signal_data = {
        "game_id": key,
        "match": p["match"],
        "league": p["league"],
        "minute": p["minute"],
        "score": p["score"],
        "strategy": strategy["strategy"],
        "dominant": strategy["dominant"],
        "odds": odd,
        "team1": p["team1"],
        "team2": p["team2"],
        "old_s1": p["s1"],
        "old_s2": p["s2"],
        "date_str": today,
        "signal_ts": now_ts,
        "message_id": msg_id,
        "base_text": text,
        "check_after": check_after,
        "attempts": 0,
    }

    saved = db.save_live_signal(signal_data)

    if not saved:
        print(
            f"❌ Не удалось сохранить сигнал в БД: "
            f"{p['match']} ({key}). "
            "Автоматическая проверка может не восстановиться.",
            flush=True,
        )
        return False

    sent_signals[key] = {
        "ts": now_ts,
        "message_id": msg_id,
        "base_text": text,
        "strategies": [f"{strategy['emoji']} {strategy['strategy']}"],
        "last_p": p,
    }

    pending_checks[key] = {
        "team1": p["team1"],
        "team2": p["team2"],
        "match": p["match"],
        "date_str": today,
        "old_s1": int(p["s1"]),
        "old_s2": int(p["s2"]),
        "minute": int(p["minute"]),
        "signal_ts": now_ts,
        "message_id": msg_id,
        "base_text": text,
        "strategy": strategy["strategy"],
        "odd": odd,
        "check_after": check_after,
        "attempts": 0,
    }

    persist_check(key, pending_checks[key])

    log_result_record({
        "record_type": "signal",
        "game_id": key,
        "timestamp": now_ts,
        "match": p["match"],
        "league": p["league"],
        "strategy": strategy["strategy"],
        "odd": odd,
        "score_at_signal": p["score"],
    })

    print(
        f"📤 СИГНАЛ: {p['match']} | {strategy['strategy']} | "
        f"кэф {odd:.2f}; первая проверка через "
        f"{CHECK_FIRST_AFTER} сек.",
        flush=True,
    )

    return True
