import time
from datetime import datetime
from config import *
from telegram_bot import send_telegram, edit_telegram, format_with_result
from stats_parser import *
from ruscore import fetch_ruscore_events, find_match, parse_score_for_match

def log_result_record(record):
    try:
        with open(RESULTS_FILE, "a", encoding="utf-8") as f: f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except Exception as e: print(f"⚠️ Не удалось записать {RESULTS_FILE}: {e}", flush=True)

def check_pending_results(pending_checks):
    if not pending_checks: return
    now = int(time.time())
    by_date = {}
    for key, info in pending_checks.items():
        if now >= info.get("check_after", 0): by_date.setdefault(info["date_str"], []).append(key)
    for date_str, keys in by_date.items():
        events = fetch_ruscore_events(date_str)
        if not events:
            for k in keys: pending_checks[k]["check_after"] = now + CHECK_REPEAT_AFTER
            continue
        for k in keys:
            info = pending_checks.get(k)
            if not info: continue
            ev = find_match(events, info["team1"], info["team2"])
            if not ev:
                info["attempts"] = info.get("attempts", 0) + 1; info["check_after"] = now + CHECK_REPEAT_AFTER
                if info["attempts"] >= CHECK_MAX_ATTEMPTS:
                    edit_telegram(info["message_id"], format_with_result(info["base_text"], "❓ <b>РЕЗУЛЬТАТ НЕ НАЙДЕН</b>"))
                    del pending_checks[k]
                continue
            h_score, a_score = parse_score_for_match(ev, info["team1"], info["team2"])
            status = str((ev.get("status") or {}).get("label", "")).lower()
            if h_score is None: info["check_after"] = now + CHECK_REPEAT_AFTER; continue
            goal = (h_score > info["old_s1"]) or (a_score > info["old_s2"])
            finished = status in ("finished", "ended", "завершен", "завершён", "матч завершен", "матч завершён")
            if goal:
                elapsed = (now - info["signal_ts"]) // 60
                line = f"✅ <b>ЗАШЛО</b>\n📊 Было: {info['old_s1']}-{info['old_s2']} ({info['minute']}')\n📊 Стало: {h_score}-{a_score}\n⏱ ~{elapsed} мин"
                edit_telegram(info["message_id"], format_with_result(info["base_text"], line))
                log_result_record({"record_type": "result", "game_id": k, "timestamp": now, "match": info["match"], "strategy": info["strategy"], "odd": info.get("odd"), "outcome": "hit", "final_score": f"{h_score}-{a_score}"})
                print(f"✅ {info['match']} [{info['strategy']}]", flush=True); del pending_checks[k]; continue
            if finished:
                line = f"❌ <b>НЕ ЗАШЛО</b>\n📊 Итог: {h_score}-{a_score}"
                edit_telegram(info["message_id"], format_with_result(info["base_text"], line))
                log_result_record({"record_type": "result", "game_id": k, "timestamp": now, "match": info["match"], "strategy": info["strategy"], "odd": info.get("odd"), "outcome": "miss", "final_score": f"{h_score}-{a_score}"})
                print(f"❌ {info['match']} [{info['strategy']}]", flush=True); del pending_checks[k]; continue
            info["attempts"] = info.get("attempts", 0) + 1; info["check_after"] = now + CHECK_REPEAT_AFTER
            if info["attempts"] >= CHECK_MAX_ATTEMPTS:
                edit_telegram(info["message_id"], format_with_result(info["base_text"], f"⏱ <b>БЕЗ РЕЗУЛЬТАТА</b> ({h_score}-{a_score})"))
                del pending_checks[k]

def format_signal_multi(p, strategies, odd):
    total = p["s1"] + p["s2"]; tb1, tb2 = total + 0.5, total + 1.5
    trend = p.get("trend", {})
    trend_line = f"📈 За 5–10 мин: xG +{trend['xg_delta']:.2f}, створ +{trend['shots_on_delta']}, удары +{trend['shots_delta']}\n" if trend.get("available") else "📈 Динамика: собирается история\n"
    odd_line = f"💰 Кэф ТБ {tb1}: <b>{odd:.2f}</b>" if odd is not None else "💰 Кэф: недоступен"
    return (f"🎯 <b>СИГНАЛ OLD — следующий гол до конца матча</b>\n{p['league']}\n⚽ <b>{p['match']}</b>\n"
            f"📊 Счёт: <b>{p['score']}</b> | ⏱ {p['minute']}'\n🎯 xG: {p['xg1']:.2f} — {p['xg2']:.2f}\n"
            f"🥅 Удары: {p['shots_all1']} — {p['shots_all2']} (в створ {p['shots_on1']} — {p['shots_on2']})\n"
            f"⚔️ Опасные атаки: {p['att1']} — {p['att2']}\n🚩 Углы: {p['corners1']} — {p['corners2']}\n"
            f"{trend_line}{odd_line}\n🧠 Фильтры: {', '.join(strategies)}\n💡 Цель: хотя бы один гол до финального свистка; это оценка, не гарантия.")

def try_send_signal(p, strategy, now_ts, p_game_cache, sent_signals, pending_checks):
    gid, key = p["game_id"], str(p["game_id"])
    odd = get_odd_total(p_game_cache.get(gid, {}), p["s1"] + p["s2"])
    if odd is None: return False
    try: odd = float(odd)
    except: return False
    if odd < strategy["min_odd"]: return False
    existing = sent_signals.get(key)
    if not existing:
        text = format_signal_multi(p, [f"{strategy['emoji']} {strategy['strategy']}"], odd)
        msg_id = send_telegram(text)
        if not msg_id: return False
        sent_signals[key] = {"ts": now_ts, "message_id": msg_id, "base_text": text, "strategies": [f"{strategy['emoji']} {strategy['strategy']}"], "last_p": p}
        log_result_record({"record_type": "signal", "game_id": gid, "timestamp": now_ts, "match": p["match"], "league": p["league"], "strategy": strategy["strategy"], "odd": odd})
        today = datetime.now(MOSCOW_TZ).strftime("%Y-%m-%d")
        pending_checks[key] = {"team1": p["team1"], "team2": p["team2"], "match": p["match"], "date_str": today, "old_s1": p["s1"], "old_s2": p["s2"], "minute": p["minute"], "signal_ts": now_ts, "message_id": msg_id, "base_text": text, "strategy": strategy["strategy"], "odd": odd, "check_after": now_ts + CHECK_FIRST_AFTER, "attempts": 0}
        time.sleep(1); return True
    return False
