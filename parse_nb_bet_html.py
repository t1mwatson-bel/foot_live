import json
import re

def parse_nb_bet_html(file_path="match_page.html"):
    """
    Парсит HTML-страницу nb-bet, вытаскивает JSON из тега __NEXT_DATA__
    и возвращает нужные данные: команды, кэфы, средние голы.
    """
    with open(file_path, "r", encoding="utf-8") as f:
        html = f.read()

    # Ищем тег <script id="__NEXT_DATA__" type="application/json">...</script>
    match = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html,
        re.DOTALL
    )
    if not match:
        print("❌ Не найден тег __NEXT_DATA__")
        return None

    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError as e:
        print(f"❌ Ошибка парсинга JSON: {e}")
        return None

    # Достаём матч
    try:
        match_data = data["props"]["initialState"]["pageSoccerEvent"]["match"]
    except KeyError:
        print("❌ Не найден блок pageSoccerEvent.match")
        return None

    # Команды
    team1 = match_data.get("7", {}).get("1", "?")
    team2 = match_data.get("8", {}).get("1", "?")

    # Кэфы 1X2 (источник "5")
    odds_1x2 = match_data.get("5", {})
    coef_1 = odds_1x2.get("1")
    coef_x = odds_1x2.get("2")
    coef_2 = odds_1x2.get("3")

    # Кэфы ТБ 2.5 (источник "5")
    # В JSON: "15": 1.806 — ТБ 2.5, "16": 2.167 — ТМ 2.5
    coef_tb_2_5 = odds_1x2.get("15")
    coef_tm_2_5 = odds_1x2.get("16")

    # Средние голы — они в тексте прогноза (поле "27.1")
    preview_text = match_data.get("27", {}).get("1", "")
    avg_scored_home, avg_conceded_home = extract_avg_goals(preview_text, team1)
    avg_scored_away, avg_conceded_away = extract_avg_goals(preview_text, team2)

    return {
        "team1": team1,
        "team2": team2,
        "coef_1": coef_1,
        "coef_x": coef_x,
        "coef_2": coef_2,
        "coef_tb_2_5": coef_tb_2_5,
        "coef_tm_2_5": coef_tm_2_5,
        "avg_scored_home": avg_scored_home,
        "avg_conceded_home": avg_conceded_home,
        "avg_scored_away": avg_scored_away,
        "avg_conceded_away": avg_conceded_away,
        "preview_text": preview_text,
    }

def extract_avg_goals(preview_text, team_name):
    """
    Из текста прогноза вытаскивает средние голы команды.
    Ищем фразу: "Команда {team_name} ... в среднем забивает X гола за игру, пропускает Y."
    """
    if not preview_text or not team_name:
        return None, None

    # Ищем упоминание команды и цифры
    pattern = rf"{re.escape(team_name)}.*?забивает\s+([\d.]+)\s+гол.*?пропускает\s+([\d.]+)"
    m = re.search(pattern, preview_text, re.DOTALL)
    if m:
        try:
            return float(m.group(1)), float(m.group(2))
        except ValueError:
            pass
    return None, None


if __name__ == "__main__":
    data = parse_nb_bet_html("match_page.html")
    if data:
        print(f"\n⚽ {data['team1']} — {data['team2']}")
        print(f"   1X2: {data['coef_1']} / {data['coef_x']} / {data['coef_2']}")
        print(f"   ТБ 2.5: {data['coef_tb_2_5']}  |  ТМ 2.5: {data['coef_tm_2_5']}")
        print(f"\n   Средние голы {data['team1']}:")
        print(f"      Забивает: {data['avg_scored_home']}")
        print(f"      Пропускает: {data['avg_conceded_home']}")
        print(f"   Средние голы {data['team2']}:")
        print(f"      Забивает: {data['avg_scored_away']}")
        print(f"      Пропускает: {data['avg_conceded_away']}")
