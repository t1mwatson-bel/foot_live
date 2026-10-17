from config import *
import json, time
from collections import deque

def parse_stats(game):
    stats = {}
    tablo = ((game.get("scores") or {}).get("tabloStats")) or {}
    for key, items in tablo.items():
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and item.get("name"): stats[item["name"]] = item
    return stats

def sv(stats, name, side="s1"):
    d = stats.get(name, {})
    try: return float(d.get(side, 0) or 0)
    except: return 0.0

def parse_game(game):
    if not isinstance(game, dict) or (game.get("sport") or {}).get("id") != 1: return None
    liga_id = (game.get("liga") or {}).get("id")
    if liga_id not in LEAGUE_IDS: return None
    scores = game.get("scores") or {}
    if (scores.get("currentPeriodName") == "Игра завершена" or scores.get("statusLineStr", "") == ""):
        if not scores.get("timer", {}).get("timeRun"): return None
    minute = (scores.get("timer") or {}).get("timeSec", 0) // 60
    score = scores.get("fullScore", "0-0")
    try: s1, s2 = map(int, score.split("-"))
    except: s1, s2 = 0, 0
    stats = parse_stats(game)
    o1 = (game.get("opponent1") or {}).get("fullName", "?")
    o2 = (game.get("opponent2") or {}).get("fullName", "?")
    return {
        "game_id": game.get("id"), "liga_id": liga_id, "league": LEAGUE_IDS.get(liga_id, ""),
        "team1": o1, "team2": o2, "match": f"{o1} — {o2}", "minute": minute, "score": score, "s1": s1, "s2": s2,
        "xg1": sv(stats, "xG", "s1"), "xg2": sv(stats, "xG", "s2"),
        "shots_on1": int(sv(stats, "Удары в створ", "s1")), "shots_on2": int(sv(stats, "Удары в створ", "s2")),
        "shots_all1": int(sv(stats, "Удары в створ", "s1") + sv(stats, "Удары в сторону ворот", "s1")),
        "shots_all2": int(sv(stats, "Удары в створ", "s2") + sv(stats, "Удары в сторону ворот", "s2")),
        "att1": int(sv(stats, "Опасные атаки", "s1")), "att2": int(sv(stats, "Опасные атаки", "s2")),
        "corners1": int(sv(stats, "Угловые", "s1")), "corners2": int(sv(stats, "Угловые", "s2")),
        "red1": int(sv(stats, "Красные карточки", "s1")), "red2": int(sv(stats, "Красные карточки", "s2")),
    }

def get_1x2_odds(game):
    odds = {}
    for grp in (game.get("eventGroups") or []):
        if grp.get("groupId") != 1: continue
        for e in (grp.get("events") or []):
            if not isinstance(e, list) or not e: continue
            item = e[0]
            if not isinstance(item, dict): continue
            t, c = item.get("T"), item.get("C")
            if t == 1: odds["П1"] = c
            elif t == 2: odds["X"] = c
            elif t == 3: odds["П2"] = c
        break
    return odds

def get_odd_total(game, total_goals):
    target = float(total_goals) + 0.5
    for grp in (game.get("centralBlockEventGroups") or []):
        if not isinstance(grp, dict) or grp.get("groupId") != 17: continue
        for event_list in (grp.get("events") or []):
            if not isinstance(event_list, list): continue
            for item in event_list:
                if not isinstance(item, dict) or item.get("type") != 9: continue
                try:
                    parameter, odd = float(item.get("parameter")), float(item.get("cf"))
                except: continue
                if abs(parameter - target) < 0.001 and odd > 1.0: return odd
    return None

def update_match_history(p, now_ts, recent_snapshots):
    gid = p.get("game_id")
    if gid is None: return
    hist = recent_snapshots.setdefault(gid, deque(maxlen=20))
    snapshot = {"ts": now_ts, "minute": p["minute"], "score": p["score"], "xg1": p["xg1"], "xg2": p["xg2"], "shots_on1": p["shots_on1"], "shots_on2": p["shots_on2"], "shots_all1": p["shots_all1"], "shots_all2": p["shots_all2"], "corners1": p["corners1"], "corners2": p["corners2"], "att1": p["att1"], "att2": p["att2"]}
    if hist and hist[-1]["ts"] == now_ts: hist[-1] = snapshot
    else: hist.append(snapshot)
    while hist and now_ts - hist[0]["ts"] > 900: hist.popleft()
    for old_gid in list(recent_snapshots):
        if not recent_snapshots[old_gid] or now_ts - recent_snapshots[old_gid][-1]["ts"] > 7200: del recent_snapshots[old_gid]
    reference = None
    for item in hist:
        if 300 <= (now_ts - item["ts"]) <= 900:
            reference = item; break
    p["trend"] = {"available": False, "xg_delta": 0.0, "shots_on_delta": 0, "shots_delta": 0, "corners_delta": 0, "attacks_delta": 0}
    if reference:
        p["trend"] = {"available": True, "xg_delta": round((p["xg1"] + p["xg2"]) - (reference["xg1"] + reference["xg2"]), 3), "shots_on_delta": (p["shots_on1"] + p["shots_on2"]) - (reference["shots_on1"] + reference["shots_on2"]), "shots_delta": (p["shots_all1"] + p["shots_all2"]) - (reference["shots_all1"] + reference["shots_all2"]), "corners_delta": (p["corners1"] + p["corners2"]) - (reference["corners1"] + reference["corners2"]), "attacks_delta": (p["att1"] + p["att2"]) - (reference["att1"] + reference["att2"])}

def has_real_threat(p):
    t_xg, t_sot, t_shots = p["xg1"] + p["xg2"], p["shots_on1"] + p["shots_on2"], p["shots_all1"] + p["shots_all2"]
    trend = p.get("trend", {})
    recent_pressure = trend.get("available") and (trend.get("xg_delta", 0) >= 0.15 or trend.get("shots_on_delta", 0) >= 1 or trend.get("shots_delta", 0) >= 3)
    return t_xg >= 0.70 or t_sot >= 3 or t_shots >= 8 or recent_pressure

def common_ok(p, gid, now_ts, last_scores):
    if p["minute"] > MAX_MINUTE: return False
    prev = last_scores.get(gid)
    if prev is None: last_scores[gid] = {"score": p["score"], "changed_at": 0}
    elif prev.get("score") != p["score"]:
        last_scores[gid] = {"score": p["score"], "changed_at": now_ts}; return False
    changed_at = last_scores.get(gid, {}).get("changed_at", 0)
    if changed_at and now_ts - changed_at < GOAL_COOLDOWN_SEC: return False
    return True

def strategy_xg(p):
    diff, on_diff = abs(p["xg1"] - p["xg2"]), abs(p["shots_on1"] - p["shots_on2"])
    if diff < S1_XG_DIFF or on_diff < S1_SHOTS_ON_DIFF: return None
    side = "home" if p["xg1"] > p["xg2"] else "away"
    if (p["red1"] if side == "home" else p["red2"]) > 0: return None
    return {"strategy": "xG-мощь", "emoji": "🟢", "dominant": p["team1"] if side == "home" else p["team2"], "key": f"xG {diff:.2f}, створ {on_diff}", "min_odd": S1_MIN_ODD}

def strategy_shots(p):
    diff, on_diff = abs(p["shots_all1"] - p["shots_all2"]), abs(p["shots_on1"] - p["shots_on2"])
    if diff < S2_SHOTS_DIFF or on_diff < S2_SHOTS_ON_DIFF: return None
    side = "home" if p["shots_all1"] > p["shots_all2"] else "away"
    if (p["red1"] if side == "home" else p["red2"]) > 0: return None
    return {"strategy": "Удары", "emoji": "🥅", "dominant": p["team1"] if side == "home" else p["team2"], "key": f"удары {diff}, створ {on_diff}", "min_odd": S2_MIN_ODD}

def strategy_corners(p):
    c_diff, a_diff = abs(p["corners1"] - p["corners2"]), abs(p["att1"] - p["att2"])
    if c_diff < S3_CORNERS_DIFF or a_diff < S3_ATT_DIFF or not has_real_threat(p): return None
    side = "home" if p["corners1"] > p["corners2"] else "away"
    if (p["red1"] if side == "home" else p["red2"]) > 0: return None
    return {"strategy": "Углы + атаки", "emoji": "🚩", "dominant": p["team1"] if side == "home" else p["team2"], "key": f"углы {c_diff}, атаки {a_diff}", "min_odd": S3_MIN_ODD}

def strategy_attacks(p):
    a_diff = abs(p["att1"] - p["att2"])
    if a_diff < S5_ATT_DIFF or not has_real_threat(p): return None
    side = "home" if p["att1"] > p["att2"] else "away"
    if (p["red1"] if side == "home" else p["red2"]) > 0: return None
    return {"strategy": "Опасные атаки", "emoji": "⚔️", "dominant": p["team1"] if side == "home" else p["team2"], "key": f"атаки {a_diff}", "min_odd": S5_MIN_ODD}

def strategy_combo(p):
    xg_diff, c_diff = abs(p["xg1"] - p["xg2"]), abs(p["corners1"] - p["corners2"])
    if xg_diff < S6_XG_DIFF or c_diff < S6_CORNERS_DIFF: return None
    side = "home" if p["xg1"] > p["xg2"] else "away"
    if (p["red1"] if side == "home" else p["red2"]) > 0: return None
    return {"strategy": "Комбо xG+углы", "emoji": "💡", "dominant": p["team1"] if side == "home" else p["team2"], "key": f"xG {xg_diff:.2f}, углы {c_diff}", "min_odd": S6_MIN_ODD}
