
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
    """Восстанавливает незавершённые проверки из SQLite после запуска."""
    restored = {}
    now = int(time.time())

    for row in db.get_pending_live_signals():
        game_id = str(row.get("game_id") or "")
        team1 = row.get("team1")
        team2 = row.get("team2")
        old_s1 = row.get("old_s1")
        old_s2 = row.get("old_s2")
        message_id = row.get("message_id")
        base_text = row.get("base_text") or ""

        # Старые записи без нужных данных нельзя проверять достоверно.
        if (
            not game_id or not team1 or not team2
            or old_s1 is None or old_s2 is None
            or not message_id or not base_text
        ):
            print(
                f"⚠️ Невозможно восстановить проверку старого сигнала "
                f"{game_id}: в базе не хватает данных",
                flush=True,
            )
            continue

        restored[game_id] = {
            "team1": team1,
            "team2": team2,
            "match": row.get("match_name") or f"{team1} — {team2}",
            "date_str": row.get("date_str") or datetime.now(MOSCOW_TZ).strftime("%Y-%m-%d"),
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

    print(f"♻️ Восстановлено проверок: {len(restored)}", flush=True)
    return restored


def persist_check(game_id, info):
    """Сохраняет изменившееся состояние текущей проверки."""
    db.update_live_signal_check(game_id, {
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


def is_finished_status(status):
    status = str(status or "").strip().lower().replace("ё", "е")
    finished_values = {
        "finished", "ended", "ft", "final", "complete", "completed",
        "завершен", "матч завершен", "окончен", "закончен",
        "матч окончен", "матч закончен",
    }
    return status in finished_values


def check_pending_results(pending_checks):
    """Проверяет голы после сигнала и сохраняет итог в базе."""
    if not pending_checks:
        return

    now = int(time.time())
    due_by_date = {}

    for key, info in list(pending_checks.items()):
        if now >= int(info.get("check_after", 0)):
            date_str = info.get("date_str") or datetime.now(MOSCOW_TZ).strftime("%Y-%m-%d")
            due_by_date.setdefault(date_str, []).append(key)

    for date_str, keys in due_by_date.items():
        events = fetch_ruscore_events(date_str)

        if not events:
            for key in keys:
                info = pending_checks.get(key)
                if not info:
                    continue
                info["attempts"] = info.get("attempts", 0) + 1
                info["check_after"] = now + CHECK_REPEAT_AFTER
                persist_check(key, info)
            print(f"⚠️ Источник результатов временно недоступен: {date_str}", flush=True)
            continue

        for key in keys:
            info = pending_checks.get(key)
            if not info:
                continue

            try:
                event = find_match(events, info["team1"], info["team2"])
            except Exception as e:
                print(f"⚠️ Ошибка поиска матча {info.get('match')}: {e}", flush=True)
                event = None

            if not event:
                # Не ставим проигрыш и не удаляем проверку из памяти.
                info["attempts"] = info.get("attempts", 0) + 1
                delay = CHECK_REPEAT_AFTER
                if info["attempts"] >= CHECK_MAX_ATTEMPTS:
                    delay = max(CHECK_REPEAT_AFTER, 3600)
                info["check_after"] = now + delay
                persist_check(key, info)
                print(
                    f"🔎 Матч пока не найден: {info.get('match')}; "
                    f"попытка {info['attempts']}. Продолжаем проверять.",
                    flush=True,
                )
                continue

            try:
                score1, score2 = parse_score_for_match(
                    event, info["team1"], info["team2"]
                )
            except Exception as e:
                print(f"⚠️ Ошибка разбора счёта {info.get('match')}: {e}", flush=True)
                score1, score2 = None, None

            if score1 is None or score2 is None:
                info["attempts"] = info.get("attempts", 0) + 1
                info["check_after"] = now + CHECK_REPEAT_AFTER
                persist_check(key, info)
                continue

            score1, score2 = int(score1), int(score2)
            status_obj = event.get("status") or {}
            status = status_obj.get("label", "") if isinstance(status_obj, dict) else str(status_obj)
            finished = is_finished_status(status)

            # Счёт должен увеличиться относительно счёта именно в момент сигнала.
            goal_scored = (
                score1 > int(info["old_s1"])
                or score2 > int(info["old_s2"])
            )

            final_score = f"{score1}-{score2}"

            if goal_scored:
                elapsed = max(0, (now - int(info["signal_ts"])) // 60)
                result_line = (
                    "✅ <b>ЗАШЛО</b>\n"
                    f"📊 Было: {info['old_s1']}-{info['old_s2']} "
                    f"({info['minute']}')\n"
                    f"📊 Стало: {final_score}\n"
                    f"⏱ ~{elapsed} мин"
                )
                db.update_live_result(key, True, final_score=final_score)
                edit_telegram(
                    info["message_id"],
                    format_with_result(info["base_text"], result_line),
                )
                log_result_record({
                    "record_type": "result",
                    "game_id": key,
                    "timestamp": now,
                    "match": info["match"],
                    "strategy": info["strategy"],
                    "odd": info.get("odd"),
                    "outcome": "hit",
                    "final_score": final_score,
                })
                print(f"✅ ЗАШЛО: {info['match']} [{info['strategy']}] {final_score}", flush=True)
                pending_checks.pop(key, None)
                continue

            if finished:
                result_line = (
                    "❌ <b>НЕ ЗАШЛО</b>\n"
                    f"📊 Итог: {final_score}\n"
                    "ℹ️ После сигнала новых голов не было."
                )
                db.update_live_result(key, False, final_score=final_score)
                edit_telegram(
                    info["message_id"],
                    format_with_result(info["base_text"], result_line),
                )
                log_result_record({
                    "record_type": "result",
                    "game_id": key,
                    "timestamp": now,
                    "match": info["match"],
                    "strategy": info["strategy"],
                    "odd": info.get("odd"),
                    "outcome": "miss",
                    "final_score": final_score,
                })
                print(f"❌ НЕ ЗАШЛО: {info['match']} [{info['strategy']}] {final_score}", flush=True)
                pending_checks.pop(key, None)
                continue

            info["attempts"] = info.get("attempts", 0) + 1
            info["check_after"] = now + CHECK_REPEAT_AFTER
            persist_check(key, info)


def format_signal_multi(p, strategies, odd):
    total = p["s1"] + p["s2"]
    tb1, tb2 = total + 0.5, total + 1.5
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


def try_send_signal(p, strategy, now_ts, p_game_cache, sent_signals, pending_checks):
    gid = p["game_id"]
    key = str(gid)

    # Защита от повторного сигнала по уже записанному матчу.
    if db.is_live_signal_sent(key):
        return False

    game = p_game_cache.get(gid) or p_game_cache.get(key) or {}
    odd = get_odd_total(game, p["s1"] + p["s2"])

    if odd is None:
        print(f"⚠️ Нет коэффициента для {p['match']}; сигнал не отправлен", flush=True)
        return False

    try:
        odd = float(odd)
    except (TypeError, ValueError):
        return False

    if odd < strategy["min_odd"]:
        return False

    # Один сигнал на матч; остальные стратегии не создают дубли.
    text = format_signal_multi(
        p, [f"{strategy['emoji']} {strategy['strategy']}"], odd
    )
    msg_id = send_telegram(text)

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

    saved = db.save_live_signal(signal_data)
    if not saved:
        print(
            f"⚠️ Сигнал отправлен в Telegram, но запись в БД не подтверждена: "
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

    # Сохраняем состояние повторно на случай, если запись создалась,
    # но часть метаданных в ней отсутствовала.
    db.update_live_signal_check(key, signal_data)

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

    print(f"📤 СИГНАЛ: {p['match']} | {strategy['strategy']} | кэф {odd:.2f}", flush=True)
    return True