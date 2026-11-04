import time
import threading
import traceback
from datetime import datetime
import requests
import web
import database as db
from config import *
from stats_parser import parse_prematch_game
from poisson_model import prob_over
from parse_nb_bet_html import parse_nb_bet_html

# ==== API линии 1xBet ====
LINE_URL = f"{BASE_URL}/service-api/main-line-feed/v3/games1x2"

def get_prematch_games():
    params = {
        "cfView": 3,
        "count": 40,
        "fcountry": 1,
        "gr": 2336,
        "grMode": 4,
        "lng": "ru",
        "ref": 1
    }
    try:
        r = requests.get(LINE_URL, headers=HEADERS, params=params, timeout=15)
        print(f"🔎 LINE HTTP: {r.status_code}", flush=True)
        if r.status_code != 200:
            print(f"❌ Ошибка: {r.text[:300]}", flush=True)
            return []
        if not r.text.strip().startswith(("[", "{")):
            print(f"❌ API вернул не JSON: {r.text[:200]}", flush=True)
            return []
        try:
            data = r.json()
        except Exception as e:
            print(f"❌ Ошибка разбора JSON: {e}", flush=True)
            return []
        if isinstance(data, list):
            print(f"📊 Получено матчей: {len(data)}", flush=True)
            return [g for g in data if isinstance(g, dict)]
        return []
    except Exception as e:
        print(f"❌ Исключение: {e}", flush=True)
        return []

def run_web():
    try:
        web.app.run(host="0.0.0.0", port=3000, use_reloader=False, threaded=True)
    except Exception as e:
        print(f"❌ Ошибка запуска сайта: {e}", flush=True)

def bot_loop():
    print("🚀 PREMATCH-БОТ ЗАПУЩЕН (умная модель на nb-bet)", flush=True)
    while True:
        try:
            now = datetime.now(MOSCOW_TZ)
            print(f"\n🔄 [{now:%H:%M:%S}] Загрузка линии...", flush=True)

            games = get_prematch_games()
            count_ok = 0
            count_value = 0

            for game in games:
                parsed = parse_prematch_game(game)
                if not parsed:
                    continue

                # Фильтр: специальные/сборные
                t1 = parsed["team1"].lower()
                t2 = parsed["team2"].lower()
                if ("специальное" in t1 or "специальное" in t2
                        or t1 in ("хозяева", "гости") or t2 in ("хозяева", "гости")):
                    continue

                # Фильтр: тотал 2.5
                tb_25 = parsed["odds"]["TB"].get(2.5)
                if not tb_25 or not tb_25.get("over"):
                    continue

                count_ok += 1

                # Пытаемся достать данные с nb-bet
                nb_data = None
                if "Славия" in parsed["team1"] and "Арсенал" in parsed["team2"]:
                    try:
                        nb_data = parse_nb_bet_html("match_page.html")
                    except Exception as e:
                        print(f"⚠️ Ошибка парсинга nb-bet: {e}", flush=True)

                if nb_data and nb_data["avg_scored_home"] is not None:
                    lam_home = (nb_data["avg_scored_home"] + nb_data["avg_conceded_away"]) / 2
                    lam_away = (nb_data["avg_scored_away"] + nb_data["avg_conceded_home"]) / 2
                    lam_total = lam_home + lam_away

                    p_model = prob_over(2.5, lam_total)
                    coef_over = tb_25["over"]
                    p_book = 1 / coef_over
                    edge = p_model - p_book

                    print(
                        f"\n⚽ {parsed['team1']} — {parsed['team2']} (данные с nb-bet)"
                        f"\n   Лига: {parsed['liga']}"
                        f"\n   Начало: {parsed['start_time']:%d.%m %H:%M}"
                        f"\n   Кэф ТБ 2.5: {coef_over}"
                        f"\n   Средние голы: {parsed['team1']} — забивает {nb_data['avg_scored_home']}, пропускает {nb_data['avg_conceded_home']}"
                        f"\n                 {parsed['team2']} — забивает {nb_data['avg_scored_away']}, пропускает {nb_data['avg_conceded_away']}"
                        f"\n   Ожидаемые голы (lam): {lam_home:.2f} + {lam_away:.2f} = {lam_total:.2f}"
                        f"\n   Модель: {p_model:.1%} | Букмекер: {p_book:.1%} | Edge: {edge:+.1%}",
                        flush=True
                    )
                    if edge > 0.05:
                        count_value += 1
                        print(f"   🔥 ВАЛУЙ", flush=True)
                else:
                    print(
                        f"ℹ️ {parsed['team1']} — {parsed['team2']}: нет данных с nb-bet",
                        flush=True
                    )

            print(
                f"\n✅ Матчей с ТБ 2.5: {count_ok} | валуев: {count_value}",
                flush=True
            )
            print("💤 Спим 5 минут...", flush=True)
            time.sleep(300)

        except KeyboardInterrupt:
            print("⏹️ Остановка", flush=True)
            break
        except Exception as e:
            print(f"❌ Ошибка цикла: {e}", flush=True)
            traceback.print_exc()
            time.sleep(60)

if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    bot_loop()
