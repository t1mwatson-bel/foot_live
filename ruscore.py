import requests
from datetime import datetime, timedelta
from config import *

def fetch_ruscore_events(date_str):
    params = dict(RUSCORE_PARAMS); params["date"] = date_str
    try:
        r = requests.get(RUSCORE_URL, params=params, headers=RUSCORE_HEADERS, timeout=15)
        if r.status_code != 200: return []
        events = []
        for block in r.json().get("data", []):
            for ev in block.get("events", []):
                ev["_league"] = block.get("name", ""); events.append(ev)
        return events
    except: return []

def normalize_name(s):
    if not s: return ""
    return (s.lower().replace(" ", "").replace("-", "").replace("'", "").replace("ё", "е").replace(".", "").strip())

def find_match(events, team1, team2):
    n1, n2 = normalize_name(team1), normalize_name(team2)
    for ev in events:
        h, a = normalize_name((ev.get("home") or {}).get("name", "")), normalize_name((ev.get("away") or {}).get("name", ""))
        if (n1 in h or h in n1) and (n2 in a or a in n2): return ev
        if (n1 in a or a in n1) and (n2 in h or h in n2): return ev
    return None

def parse_score_from_ruscore(ev):
    for s in (ev.get("score") or []):
        if s.get("type") == "overall":
            h, a = s.get("home"), s.get("away")
            if h == "" or a == "": return None, None
            try: return int(h), int(a)
            except: return None, None
    return None, None

def parse_score_for_match(ev, team1, team2):
    h_score, a_score = parse_score_from_ruscore(ev)
    if h_score is None or a_score is None: return None, None
    home, away = normalize_name((ev.get("home") or {}).get("name", "")), normalize_name((ev.get("away") or {}).get("name", ""))
    n1, n2 = normalize_name(team1), normalize_name(team2)
    if (n1 in home or home in n1) and (n2 in away or away in n2): return h_score, a_score
    if (n1 in away or away in n1) and (n2 in home or home in n2): return a_score, h_score
    return None, None

def is_our_league(name):
    return any(p in name.lower() for p in RUSCORE_LEAGUES_FILTER) if name else False

def get_today_schedule():
    today = datetime.now(MOSCOW_TZ).strftime("%Y-%m-%d")
    schedule = []
    for ev in fetch_ruscore_events(today):
        if not is_our_league(ev.get("_league", "")): continue
        t = ev.get("time")
        if not t: continue
        try:
            dt = datetime.fromisoformat(t)
            schedule.append({"time": dt.astimezone(MOSCOW_TZ) if dt.tzinfo else MOSCOW_TZ.localize(dt)})
        except: continue
    return schedule

def get_windows(schedule):
    if not schedule: return []
    times = sorted([s["time"] for s in schedule])
    windows = [(t, t + timedelta(hours=2)) for t in times]
    merged = [windows[0]]
    for start, end in windows[1:]:
        ls, le = merged[-1]
        if start <= le: merged[-1] = (ls, max(le, end))
        else: merged.append((start, end))
    return merged
