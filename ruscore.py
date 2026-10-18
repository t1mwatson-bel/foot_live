import requests
from datetime import datetime, timedelta
from config import *

# Словарь синонимов для команд, которые по-разному называются в 1xlite и Ruscore
TEAM_ALIASES = {
    "брайтон энд хав альбион": "брайтон",
    "брайтон": "брайтон",
    "кристал пэлэс": "кристал пэлэс",
    "кристал пэлас": "кристал пэлэс",
    "боруссия менхенгладбах": "боруссия менхенгладбах",
    "боруссия м": "боруссия менхенгладбах",
    "интер": "интер",
    "интернационале": "интер",
    "псж": "псж",
    "пари сен-жермен": "псж",
    "париж": "париж",
}

def normalize_name(name):
    """Приводит название команды к единому виду."""
    if not name:
        return ""
    # Приводим к нижнему регистру, убираем пробелы, дефисы, точки и т.д.
    n = (name.lower().replace(" ", "").replace("-", "").replace("'", "")
         .replace("ё", "е").replace(".", "").strip())
    
    # Проверяем словарь синонимов
    for alias, standard in TEAM_ALIASES.items():
        if n.startswith(alias.replace(" ", "")):
            return standard
            
    return n

def fetch_ruscore_events(date_str):
    """Получает все матчи на дату через API-статистику."""
    url = "https://api-statistics.ruscore.ru/v1/events"
    
    params = {
        "app_id": "ruscore",
        "api_key": RUSCORE_PARAMS.get("api_key", ""),
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
        
        for tournament in data.get("data", []):
            league_name = tournament.get("name", "")
            
            for ev in tournament.get("events", []):
                home = (ev.get("home") or {}).get("name", "")
                away = (ev.get("away") or {}).get("name", "")
                
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

def find_match(events, team1, team2):
    """Ищет матч по нормализованным именам."""
    n1 = normalize_name(team1)
    n2 = normalize_name(team2)
    
    # Берем первые 5 букв для поиска, чтобы "Брайтон" нашелся в "Брайтон энд Хав Альбион"
    t1 = n1[:5]
    t2 = n2[:5]

    for ev in events:
        home_name = normalize_name((ev.get("home") or {}).get("name", ""))
        away_name = normalize_name((ev.get("away") or {}).get("name", ""))
        
        # Проверяем совпадение по началу названий
        h_match = (t1 in home_name) or (t2 in home_name)
        a_match = (t1 in away_name) or (t2 in away_name)
        
        if h_match and a_match:
            return ev
            
    return None

def parse_score_from_ruscore(ev):
    for s in (ev.get("score") or []):
        if s.get("type") == "overall":
            h, a = s.get("home"), s.get("away")
            if h is None or a is None: return None, None
            return h, a
    return None, None

def parse_score_for_match(ev, team1, team2):
    """Возвращает счет в том порядке, в котором команды записаны в сигнале."""
    h_score, a_score = parse_score_from_ruscore(ev)
    if h_score is None or a_score is None: 
        return None, None
        
    home = normalize_name((ev.get("home") or {}).get("name", ""))
    away = normalize_name((ev.get("away") or {}).get("name", ""))
    n1 = normalize_name(team1)
    n2 = normalize_name(team2)
    
    # Если хозяева в Ruscore совпадают с хозяевами в сигнале
    if (n1[:5] in home) and (n2[:5] in away): 
        return h_score, a_score
        
    # Если команды поменялись местами
    if (n1[:5] in away) and (n2[:5] in home): 
        return a_score, h_score
        
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