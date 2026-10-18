
import time
import json
from datetime import datetime

from config import *
from telegram_bot import send_telegram, edit_telegram, format_with_result
from stats_parser import *
from ruscore import fetch_ruscore_events, find_match, parse_score_for_match
import database as db


def log_result_record(record):
    try:
        with open(RESULTS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except Exception as e:
        print(f"⚠️ Не удалось записать {RESULTS_FILE}: {e}", flush=True)


def restore_pending_checks():
    """Восстанавливает ожидающие проверки после перезапуска."""
    restored = {}
    now = int(time.time())

    try:
        rows = db.get_pending_live_signals()
    except Exception as e:
        print(f"❌ Не удалось загрузить проверки из БД: {e}", flush=True)
        return restored

    for row in rows:
        game_id = str(row.get("game_id") or "")
        team1 = row.get("team1")
        team2 = row.get("team2")
        old_s1 = row.get("old_s1")
        old_s2 = row.get("old_s2")
        message_id = row.get("message_id")
        base_text = row.get("base_text") or ""

        if (
            not game_id or not team1 or not team2
            or old_s1 is None or old_s2 is None
            or not message_id or not base_text
        ):
            print(
                f"⚠️ Сигнал {game_id}: недостаточно данных "
                "для автоматического восстановления проверки",
                flush=True,
            )
            continue

        restored[game_id] = {
            "team1": team1,
            "team2": team2,
            "match": row.get("match_name") or f"{team1} — {team2}",
            "date_str": row.get("date_str") or datetime.now(
                MOSCOW_TZ
            ).strftime("%Y-%m-%d"),
            "old_s1": int(old_s1),
            "old_s2": int(old_s2),
            "minute": int(row.get("minute") or 0),
            "signal_ts": int(row.get("signal_ts") or row.get("sent_at") or now),
            "message_id": int(message_id),
            "base_text": base_text,
            "strategy": row.get("strategy") or "не указана",
            "odd": row.get("odds"),
            "check_after": min(int(row.get("check_after") or now), now),
            "attempts": int(row.get("attempts") or 0),
        }

    print(f"♻️ Восстановлено ожидающих проверок: {len(restored)}", flush=True)
    return restored


def persist_check(game_id, info):
    """Сохраняет состояние проверки в базе."""
    try:
        return db.update_live_signal_check(str(game_id), {
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
        })
    except Exception as e:
        print(f"❌ Не удалось сохранить проверку {game_id}: {e}", flush=True)
        return False


def is_finished_status(status):
    """Проверяет распространённые статусы окончания матча."""
    if isinstance(status, dict):
        parts = [str(value) for value in status.values()]
        text = " ".join(parts)
    else:
        text = str(status or "")

    text = text.strip().lower().replace("ё", "е")
    text = " ".join(text.replace("_", " ").replace("-", " ").split())

    finished_values = {
        "finished", "ended", "ft", "final", "complete", "completed",
        "full time", "match finished", "match ended",
        "завершен", "матч завершен", "окончен", "закончен",
        "матч окончен", "матч закончен",
    }

    if text in finished_values:
        return True

    # Англоязычные статусы с дополнительным текстом.
    if text.startswith(("finished ", "ended ", "completed ", "full time ")):
        return True

    # Русские статусы с дополнительным текстом.
    if text.startswith(("завершен ", "матч завершен ", "окончен ", "закончен ")):
        return True

    return False


def _schedule_retry(key, info, now, delay=None):
    """Планирует повторную проверку, не объявляя неизвестный исход проигрышем."""
    info["attempts"] = int(info.get("attempts", 0)) + 1

    if delay is None:
        delay = CHECK_REPEAT_AFTER

    # Если матч долго не удаётся найти, продолжаем реже, но не бросаем его.
    if info["attempts"] >= CHECK_MAX_ATTEMPTS:
        delay = max(int(delay), 3600)

    info["check_after"] = now + max(1, int(delay))
    persist_check(key, info)


def _finish_signal(key, info, won, score1, score2, now):
    """Фиксирует результат в БД и обновляет сообщение Telegram."""
    final_score = f"{score1}-{score2}"

    if won:
        elapsed = max(0, (now - int(info["signal_ts"])) // 60)
        result_line = (
            "✅ <b>ЗАШЛО</b>\n"
            f"📊 Было: {info['old_s1']}-{info['old_s2']} "
            f"({info['minute']}')\n"
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

    # Сначала сохраняем исход в БД. Не удаляем ожидание, если запись не удалась.
    saved = db.update_live_result(
        str(key),
        bool(won),
        final_score=final_score,
    )

    if not saved:
        print(
            f"❌ Не удалось сохранить результат в БД: "
            f"{info.get('match')} ({key})",
            flush=True,
        )
        _schedule_retry(key, info, now)
        return False

    try:
        edit_telegram(
            info["message_id"],
            format_with_result(info["base_text"], result_line),
        )
    except Exception as e:
        # Результат уже зафиксирован в БД; повторно его не считаем.
        print(
            f"⚠️ Результат сохранён, но Telegram-сообщение не обновлено: {e}",
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


def check_pending_results(pending_checks):
    """Проверяет результат каждого сигнала, ожидающего завершения."""
    if not pending_checks:
        return

    now = int(time.time())
    due_by_date = {}

    for key, info in list(pending_checks.items()):
        try:
            check_after = int(info.get("check_after") or 0)
        except (TypeError, ValueError):
            check_after = 0

        if now >= check_after:
            date_str = info.get("date_str") or datetime.now(
                MOSCOW_TZ
            ).strftime("%Y-%m-%d")
            due_by_date.setdefault(date_str, []).append(str(key))

    for date_str, keys in due_by_date.items():
        print(
            f"🔍 Проверка Ruscore: дата={date_str}, "
            f"матчей={len(keys)}",
            flush=True,
        )

        try:
            events = fetch_ruscore_events(date_str)
        except Exception as e:
            print(f"❌ Ошибка запроса Ruscore: {e}", flush=True)
            events = None

        if not events:
            print(
                f"⚠️ Ruscore не вернул события за {date_str}. "
                "Повторим проверку позже.",
                flush=True,
            )
            for key in keys:
                info = pending_checks.get(key)
                if info:
                    _schedule_retry(key, info, now)
            continue

        print(f"📥 Ruscore вернул событий: {len(events)}", flush=True)

        for key in keys:
            info = pending_checks.get(key)
            if not info:
                continue

            match_name = info.get("match") or key

            try:
                event = find_match(
                    events,
                    info["team1"],
                    info["team2"],
                )
            except Exception as e:
                print(f"❌ Ошибка поиска {match_name}: {e}", flush=True)
                event = None

            if not event:
                print(
                    f"🔎 Матч не найден: {match_name}; "
                    f"команды: {info['team1']} / {info['team2']}",
                    flush=True,
                )
                _schedule_retry(key, info, now)
                continue

            try:
                score1, score2 = parse_score_for_match(
                    event,
                    info["team1"],
                    info["team2"],
                )
            except Exception as e:
                print(f"❌ Ошибка разбора счёта {match_name}: {e}", flush=True)
                score1, score2 = None, None

            status_obj = event.get("status") or {}
            if isinstance(status_obj, dict):
                status = status_obj.get("label", status_obj)
            else:
                status = status_obj

            print(
                f"📋 Матч: {match_name} | "
                f"счёт={score1}-{score2} | статус={status!r}",
                flush=True,
            )

            if score1 is None or score2 is None:
                print(f"⚠️ Счёт пока не распознан: {match_name}", flush=True)
                _schedule_retry(key, info, now)
                continue

            try:
                score1, score2 = int(score1), int(score2)
            except (TypeError, ValueError):
                print(f"⚠️ Некорректный счёт матча {match_name}", flush=True)
                _schedule_retry(key, info, now)
                continue

            old_s1 = int(info["old_s1"])
            old_s2 = int(info["old_s2"])

            # Если хотя бы одна команда забила после сигнала — прогноз успешен.
            goal_scored = score1 > old_s1 or score2 > old_s2
            finished = is_finished_status(status)

            if goal_scored:
                completed = _finish_signal(
                    key, info, True, score1, score2, now
                )
                if completed:
                    pending_checks.pop(key, None)
                continue

            if finished:
                completed = _finish_signal(
                    key, info, False, score1, score2, now
                )
                if completed:
                    pending_checks.pop(key, None)
                continue

            print(
                f"⏳ Матч ещё не завершён: {match_name}; "
                f"счёт {score1}-{score2}; статус={status!r}",
                flush=True,
            )
            _schedule_retry(key, info, now)


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
        if odd is not None else "💰 Кэф: недоступен"
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
        print(f"⚠️ Telegram не подтвердил отправку: {p['match']}", flush=True)
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

    # Сохраняем сигнал и данные для будущей проверки.
    saved = db.save_live_signal(signal_data)
    if not saved:
        print(
            f"⚠️ Не подтверждено сохранение сигнала в БД: "
            f"{p['match']} ({key})",
            flush=True,
        )

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