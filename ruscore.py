```python
import requests
from datetime import datetime, timedelta

from config import *


# ============================================================
# RUSCORE — ПОЛУЧЕНИЕ СОБЫТИЙ
# ============================================================

def fetch_ruscore_events(date_str):
    params = dict(RUSCORE_PARAMS)
    params["date"] = date_str

    try:
        response = requests.get(
            RUSCORE_URL,
            params=params,
            headers=RUSCORE_HEADERS,
            timeout=20
        )

        if response.status_code != 200:
            print(
                f"❌ Ruscore HTTP {response.status_code}: "
                f"{response.text[:500]}"
            )
            return []

        payload = response.json()
        data = payload.get("data", [])

        if not isinstance(data, list):
            print("⚠️ Ruscore: поле data не является списком")
            return []

        events = []

        for item in data:
            if not isinstance(item, dict):
                continue

            # Новый формат: каждый элемент data — матч.
            if item.get("home") and item.get("away"):
                competition = item.get("competition") or {}
                item["_league"] = competition.get(
                    "name",
                    item.get("_league", "")
                )
                events.append(item)
                continue

            # Старый формат: внутри блока лиги есть events.
            block_name = item.get("name", "")

            for event in item.get("events", []):
                if not isinstance(event, dict):
                    continue

                event["_league"] = block_name
                events.append(event)

        print(
            f"📥 Ruscore: дата {date_str}, "
            f"получено событий: {len(events)}"
        )

        return events

    except requests.RequestException as error:
        print(f"❌ Ошибка запроса Ruscore: {error}")
        return []

    except (ValueError, TypeError, AttributeError) as error:
        print(f"❌ Ошибка разбора Ruscore JSON: {error}")
        return []


# ============================================================
# НОРМАЛИЗАЦИЯ НАЗВАНИЙ КОМАНД
# ============================================================

def normalize_name(name):
    if not name:
        return ""

    name = str(name).lower().replace("ё", "е")

    # Убираем пробелы, знаки препинания и дефисы.
    return "".join(char for char in name if char.isalnum())


def teams_match(name1, name2):
    """
    Сравнивает названия команд без учёта регистра,
    пробелов, дефисов и знаков препинания.
    """
    a = normalize_name(name1)
    b = normalize_name(name2)

    if not a or not b:
        return False

    return a == b or a in b or b in a


# ============================================================
# ПОИСК МАТЧА
# ============================================================

def find_match(events, team1, team2):
    for event in events:
        home = (event.get("home") or {}).get("name", "")
        away = (event.get("away") or {}).get("name", "")

        # Обычный порядок: хозяева — гости.
        if teams_match(team1, home) and teams_match(team2, away):
            return event

        # Обратный порядок.
        if teams_match(team1, away) and teams_match(team2, home):
            return event

    return None


# ============================================================
# РАЗБОР ИТОГОВОГО СЧЁТА
# ============================================================

def parse_score_from_ruscore(event):
    """
    Читает счёт только из известных полей score.
    Если формат неизвестен или счёта нет — возвращает None.
    """

    score_data = event.get("score")

    if isinstance(score_data, dict):
        # На случай, если API возвращает счёт объектом.
        candidates = [
            score_data.get("overall"),
            score_data
        ]
    elif isinstance(score_data, list):
        candidates = score_data
    else:
        candidates = []

    for item in candidates:
        if not isinstance(item, dict):
            continue

        score_type = str(item.get("type", "")).lower()

        # Не используем счёт отдельных таймов.
        if score_type and score_type not in (
            "overall", "total", "full"
        ):
            continue

        home_score = item.get("home")
        away_score = item.get("away")

        if home_score is None or away_score is None:
            continue

        try:
            # Пустая строка не является нулём.
            if str(home_score).strip() == "":
                continue
            if str(away_score).strip() == "":
                continue

            home_score = int(home_score)
            away_score = int(away_score)

            if home_score < 0 or away_score < 0:
                continue

            return home_score, away_score

        except (ValueError, TypeError):
            continue

    return None, None


def parse_score_for_match(event, team1, team2):
    home_score, away_score = parse_score_from_ruscore(event)

    if home_score is None or away_score is None:
        return None, None

    home = (event.get("home") or {}).get("name", "")
    away = (event.get("away") or {}).get("name", "")

    if teams_match(team1, home) and teams_match(team2, away):
        return home_score, away_score

    if teams_match(team1, away) and teams_match(team2, home):
        return away_score, home_score

    return None, None


# ============================================================
# ФИЛЬТР ЛИГ
# ============================================================

def is_our_league(name):
    if not name:
        return False

    filters = globals().get("RUSCORE_LEAGUES_FILTER", [])

    # Пустой список фильтров означает отсутствие фильтрации.
    if not filters:
        return True

    league = str(name).lower()

    return any(
        str(pattern).lower() in league
        for pattern in filters
        if pattern
    )


# ============================================================
# РАСПИСАНИЕ МАТЧЕЙ НА СЕГОДНЯ
# ============================================================

def get_today_schedule():
    today = datetime.now(MOSCOW_TZ).strftime("%Y-%m-%d")
    schedule = []

    for event in fetch_ruscore_events(today):
        league = event.get("_league", "")

        if not is_our_league(league):
            continue

        # В новом JSON время находится в datetime.
        time_value = event.get("datetime") or event.get("time")

        if not time_value:
            continue

        try:
            dt = datetime.fromisoformat(
                str(time_value).replace("Z", "+00:00")
            )

            if dt.tzinfo is None:
                dt = MOSCOW_TZ.localize(dt)
            else:
                dt = dt.astimezone(MOSCOW_TZ)

            schedule.append({
                "time": dt,
                "event_id": event.get("id"),
                "home": (event.get("home") or {}).get("name", ""),
                "away": (event.get("away") or {}).get("name", ""),
                "league": league
            })

        except (ValueError, TypeError, AttributeError) as error:
            print(
                f"⚠️ Ruscore: неверное время матча "
                f"{time_value!r}: {error}"
            )

    print(f"📅 Ruscore: матчей в расписании: {len(schedule)}")

    return schedule


# ============================================================
# ОБЪЕДИНЕНИЕ ВРЕМЕННЫХ ОКОН
# ============================================================

def get_windows(schedule):
    if not schedule:
        return []

    times = sorted(item["time"] for item in schedule)

    windows = [
        (start, start + timedelta(hours=2))
        for start in times
    ]

    merged = [windows[0]]

    for start, end in windows[1:]:
        last_start, last_end = merged[-1]

        if start <= last_end:
            merged[-1] = (
                last_start,
                max(last_end, end)
            )
        else:
            merged.append((start, end))

    return merged
```
