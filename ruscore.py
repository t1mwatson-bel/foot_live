import requests
from datetime import datetime, timedelta
from config import *

def fetch_ruscore_events(date_str):
    """Получает все матчи на дату через API-статистику (с правильным счетом)."""
    url = "https://api-statistics.ruscore.ru/v1/events"
    
    params = {
        "app_id": "ruscore",
        "api_key": RUSCORE_PARAMS.get("api_key", ""), # Берем из config.py
        "lang": "ru",
        "tz": "Europe/Moscow",
        "date": date_str
    }
    
    try:
        r = requests.get(url, params=params, headers=RUSCORE_HEADERS, timeout=15)
        if r.status_code != 200:
            print(f"⚠️ Ruscore HTTP {r.status_code}", flush=True)
            return []
            
        data = r.json()
        events = []
        
        # Проходим по всем турнирам (data -> блоки)
        for tournament in data.get("data", []):
            league_name = tournament.get("name", "")
            
            # Проходим по матчам в турнире
            for ev in tournament.get("events", []):
                home = (ev.get("home") or {}).get("name", "")
                away = (ev.get("away") or {}).get("name", "")
                
                # Извлекаем счет (overall)
                h_score, a_score = None, None
                for s in ev.get("score", []):
                    if s.get("type") == "overall":
                        try:
                            h_score = int(s.get("home", 0))
                            a_score = int(s.get("away", 0))
                        except (ValueError, TypeError):
                            pass
                        break
                
                status = (ev.get("status") or {}).get("label", "")
                
                events.append({
                    "home": {"name": home},
                    "away": {"name": away},
                    "status": {"label": status},
                    "score": [{"type": "overall", "home": h_score, "away": a_score}],
                    "_league": league_name
                })
        return events
        
    except Exception as e:
        print(f"⚠️ Ошибка парсинга Ruscore: {e}", flush=True)
        return []

def normalize_name(s):
    if not s: return ""
    return (s.lower().replace(" ", "").replace("-", "").replace("'", "")
            .replace("ё", "е").replace(".", "").strip())

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
            if h is None or a is None: return None, None
            return h, a
    return None, None

def parse_score_for_match(ev, team1, team2):
    h_score, a_score = parse_score_from_ruscore(ev)
    if h_score is None or a_score is None: return None, None
    home = normalize_name((ev.get("home") or {}).get("name", ""))
    away = normalize_name((ev.get("away") or {}).get("name", ""))
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
        t = ev.get("time") # Ищем время в JSON
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
