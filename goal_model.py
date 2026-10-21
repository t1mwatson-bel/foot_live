import json
import math
import os
import sqlite3
import time
from pathlib import Path


# ============================================================
# OLD ML — ТЕНЕВАЯ МОДЕЛЬ ФУТБОЛЬНЫХ СИГНАЛОВ
# ============================================================
# Модель только собирает данные и обучается.
# Она НЕ влияет на отправку существующих сигналов.
# Не импортируем live_logic.py: это предотвращает циклический импорт.
# ============================================================

DATA_DIR = Path(os.getenv("DATA_DIR", "/app"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

MODEL_DB = os.getenv(
    "FOOTBALL_MODEL_DB",
    str(DATA_DIR / "football_model.sqlite3"),
)

MODEL_FILE = os.getenv(
    "FOOTBALL_MODEL_FILE",
    str(DATA_DIR / "football_model.json"),
)

# Путь по умолчанию должен совпадать с database.py: DATA_DIR/bot_stats.db.
# Иначе ML может читать другую БД и не видеть результаты сигналов.
def find_bot_db():
    configured = os.getenv("FOOTBALL_BOT_DB")
    primary = str(Path(configured).expanduser()) if configured else str(DATA_DIR / "bot_stats.db")

    if os.path.isfile(primary):
        return primary

    # Запасные варианты используются только если основной файл отсутствует.
    candidates = [
        str(DATA_DIR / "bot_stats.db"),
        str(DATA_DIR / "data" / "bot_stats.db"),
        "/app/bot_stats.db",
        "/app/data/bot_stats.db",
        "bot_stats.db",
    ]
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate

    # Не создаём молча новую базу сигналов.
    return primary


BOT_DB = find_bot_db()

MIN_TRAINING_SAMPLES = 30
LEARNING_RATE = 0.05
L2 = 0.0005
EPOCHS = 3


# ============================================================
# ПРИЗНАКИ МАТЧА
# ============================================================

FEATURE_NAMES = [
    "minute",
    "score_total",
    "score_diff",
    "xg_total",
    "xg_diff",
    "shots_on_total",
    "shots_on_diff",
    "shots_total",
    "shots_diff",
    "attacks_total",
    "attacks_diff",
    "corners_total",
    "corners_diff",
    "red_total",
    "trend_available",
    "trend_xg",
    "trend_shots_on",
    "trend_shots",
    "trend_corners",
    "trend_attacks",
    "strategy_xg",
    "strategy_shots",
    "strategy_corners",
    "strategy_attacks",
    "strategy_combo",
    "odds",
]

SCALES = {
    "minute": 90,
    "score_total": 5,
    "score_diff": 4,
    "xg_total": 5,
    "xg_diff": 4,
    "shots_on_total": 15,
    "shots_on_diff": 10,
    "shots_total": 35,
    "shots_diff": 20,
    "attacks_total": 120,
    "attacks_diff": 80,
    "corners_total": 15,
    "corners_diff": 10,
    "red_total": 3,
    "trend_available": 1,
    "trend_xg": 2,
    "trend_shots_on": 8,
    "trend_shots": 15,
    "trend_corners": 6,
    "trend_attacks": 50,
    "strategy_xg": 1,
    "strategy_shots": 1,
    "strategy_corners": 1,
    "strategy_attacks": 1,
    "strategy_combo": 1,
    "odds": 3,
}


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

def number(value, default=0.0):
    try:
        if value is None or value == "":
            return float(default)

        if isinstance(value, str):
            value = value.replace(",", ".")

        result = float(value)

        if not math.isfinite(result):
            return float(default)

        return result

    except (TypeError, ValueError, OverflowError):
        return float(default)


def first_value(data, *keys, default=0):
    if not isinstance(data, dict):
        return default

    for key in keys:
        if key in data and data[key] is not None:
            return data[key]

    return default


def sigmoid(value):
    value = max(-30.0, min(30.0, number(value)))
    return 1.0 / (1.0 + math.exp(-value))


def normalize(value, name):
    scale = max(number(SCALES.get(name), 1.0), 1.0)
    value = number(value) / scale

    # Защита от экстремальных значений.
    return max(-5.0, min(5.0, value))


def get_strategy_name(strategy):
    if isinstance(strategy, dict):
        return str(
            strategy.get("name")
            or strategy.get("strategy")
            or strategy.get("title")
            or strategy.get("type")
            or ""
        ).strip().lower()

    return str(strategy or "").strip().lower()


def get_odds(strategy, odds=None):
    if odds is not None:
        return number(odds)

    if isinstance(strategy, dict):
        for key in ("actual_odd", "odds", "odd", "coefficient"):
            if strategy.get(key) is not None:
                return number(strategy[key])

    return 0.0


# ============================================================
# БАЗА ДАННЫХ МОДЕЛИ
# ============================================================

def connect_model_db():
    con = sqlite3.connect(MODEL_DB, timeout=15)
    con.row_factory = sqlite3.Row

    con.execute("""
        CREATE TABLE IF NOT EXISTS ml_samples (
            game_id TEXT PRIMARY KEY,
            match_name TEXT,
            strategy TEXT,
            features_json TEXT NOT NULL,
            odds REAL DEFAULT 0,
            outcome INTEGER,
            created_ts INTEGER NOT NULL,
            labeled_ts INTEGER
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS ml_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            weights_json TEXT NOT NULL,
            bias REAL NOT NULL,
            trained_samples INTEGER NOT NULL DEFAULT 0,
            updated_ts INTEGER NOT NULL
        )
    """)

    con.commit()
    return con


# ============================================================
# ПОДГОТОВКА ПРИЗНАКОВ
# ============================================================

def extract_features(match, strategy, odds=None):
    if not isinstance(match, dict):
        match = {}

    strategy_name = get_strategy_name(strategy)

    home_score = number(first_value(
        match, "home_score", "score_home", "home_goals",
        "score1", "team1_score", "s1", "old_s1",
    ))
    away_score = number(first_value(
        match, "away_score", "score_away", "away_goals",
        "score2", "team2_score", "s2", "old_s2",
    ))

    home_xg = number(first_value(
        match, "home_xg", "xg_home", "xG_home",
        "home_expected_goals", "xg1",
    ))
    away_xg = number(first_value(
        match, "away_xg", "xg_away", "xG_away",
        "away_expected_goals", "xg2",
    ))

    home_shots_on = number(first_value(
        match, "home_shots_on", "shots_on_home",
        "home_shots_on_target", "shotsOnTarget1", "shots_on1",
    ))
    away_shots_on = number(first_value(
        match, "away_shots_on", "shots_on_away",
        "away_shots_on_target", "shotsOnTarget2", "shots_on2",
    ))

    home_shots = number(first_value(
        match, "home_shots", "shots_home", "total_shots_home", "shots_all1",
    ))
    away_shots = number(first_value(
        match, "away_shots", "shots_away", "total_shots_away", "shots_all2",
    ))

    home_attacks = number(first_value(
        match, "home_attacks", "attacks_home",
        "dangerous_attacks_home", "home_dangerous_attacks", "att1",
    ))
    away_attacks = number(first_value(
        match, "away_attacks", "attacks_away",
        "dangerous_attacks_away", "away_dangerous_attacks", "att2",
    ))

    home_corners = number(first_value(
        match, "home_corners", "corners_home", "corners1",
    ))
    away_corners = number(first_value(
        match, "away_corners", "corners_away", "corners2",
    ))

    home_red = number(first_value(
        match, "home_red", "red_home", "home_red_cards", "red1",
    ))
    away_red = number(first_value(
        match, "away_red", "red_away", "away_red_cards", "red2",
    ))

    minute = number(first_value(
        match, "minute", "game_minute", "time_minute",
    ))

    trend = match.get("trend") or match.get("momentum") or {}
    if not isinstance(trend, dict):
        trend = {}
    # Поддержка полей динамики, если парсер передал их на верхнем уровне.
    trend = dict(trend)
    for source_key, target_key in (("xg_delta", "xg_delta"),
                                   ("shots_on_delta", "shots_on_delta"),
                                   ("shots_delta", "shots_delta"),
                                   ("corners_delta", "corners"),
                                   ("attacks_delta", "attacks")):
        if target_key not in trend and match.get(source_key) is not None:
            trend[target_key] = match[source_key]

    trend_available = bool(trend.get("available", bool(trend)))

    trend_xg = number(first_value(
        trend, "xg", "trend_xg", "xg_delta",
    ))
    trend_shots_on = number(first_value(
        trend, "shots_on", "shots_on_target", "trend_shots_on", "shots_on_delta",
    ))
    trend_shots = number(first_value(
        trend, "shots", "total_shots", "trend_shots", "shots_delta",
    ))
    trend_corners = number(first_value(
        trend, "corners", "trend_corners",
    ))
    trend_attacks = number(first_value(
        trend, "attacks", "dangerous_attacks", "trend_attacks",
    ))

    # Поддерживаем названия стратегий, использовавшиеся в OLD.
    strategy_xg = int("xg-мощь" in strategy_name or "xg" in strategy_name)
    strategy_shots = int("удары" in strategy_name or "shots" in strategy_name)
    strategy_corners = int("углы" in strategy_name or "углов" in strategy_name or "corners" in strategy_name)
    strategy_attacks = int(
        "опасные атаки" in strategy_name or "атаки" in strategy_name
    )
    strategy_combo = int("комбо" in strategy_name or "combo" in strategy_name)

    raw = {
        "minute": minute,
        "score_total": home_score + away_score,
        "score_diff": home_score - away_score,
        "xg_total": home_xg + away_xg,
        "xg_diff": home_xg - away_xg,
        "shots_on_total": home_shots_on + away_shots_on,
        "shots_on_diff": home_shots_on - away_shots_on,
        "shots_total": home_shots + away_shots,
        "shots_diff": home_shots - away_shots,
        "attacks_total": home_attacks + away_attacks,
        "attacks_diff": home_attacks - away_attacks,
        "corners_total": home_corners + away_corners,
        "corners_diff": home_corners - away_corners,
        "red_total": home_red + away_red,
        "trend_available": int(trend_available),
        "trend_xg": trend_xg,
        "trend_shots_on": trend_shots_on,
        "trend_shots": trend_shots,
        "trend_corners": trend_corners,
        "trend_attacks": trend_attacks,
        "strategy_xg": strategy_xg,
        "strategy_shots": strategy_shots,
        "strategy_corners": strategy_corners,
        "strategy_attacks": strategy_attacks,
        "strategy_combo": strategy_combo,
        "odds": get_odds(strategy, odds),
    }

    return {
        name: normalize(raw.get(name, 0), name)
        for name in FEATURE_NAMES
    }


# ============================================================
# СОХРАНЕНИЕ ПРИЗНАКОВ СИГНАЛА
# ============================================================

def observe(match, strategy, odds=None):
    """
    Сохраняет признаки отправленного сигнала.
    Возвращает True, если добавлена новая запись.
    ML не влияет на отправку сигнала.
    """
    if not isinstance(match, dict):
        return False

    game_id = first_value(
        match, "game_id", "id", "gameId", default=None
    )

    if game_id is None or str(game_id).strip() == "":
        print("⚠️ OLD ML: у сигнала отсутствует game_id", flush=True)
        return False

    strategy_name = get_strategy_name(strategy)
    actual_odds = get_odds(strategy, odds)
    features = extract_features(match, strategy, actual_odds)

    match_name = (
        match.get("match_name")
        or match.get("name")
        or match.get("match")
        or ""
    )

    if not match_name:
        home = first_value(
            match, "home", "home_name", "team1", default=""
        )
        away = first_value(
            match, "away", "away_name", "team2", default=""
        )
        match_name = f"{home} — {away}".strip(" —")

    con = None

    try:
        con = connect_model_db()

        cursor = con.execute("""
            INSERT OR IGNORE INTO ml_samples (
                game_id, match_name, strategy, features_json,
                odds, outcome, created_ts, labeled_ts
            )
            VALUES (?, ?, ?, ?, ?, NULL, ?, NULL)
        """, (
            str(game_id),
            str(match_name),
            strategy_name,
            json.dumps(features, ensure_ascii=False),
            actual_odds,
            int(time.time()),
        ))

        con.commit()
        return cursor.rowcount > 0

    except Exception as e:
        print(f"⚠️ OLD ML: ошибка сохранения признаков: {e}", flush=True)
        return False

    finally:
        if con:
            con.close()


# ============================================================
# СИНХРОНИЗАЦИЯ ПОДТВЕРЖДЁННЫХ РЕЗУЛЬТАТОВ
# ============================================================

def sync_confirmed_results():
    """
    Переносит подтверждённые WIN/LOSE из основной базы.
    Схема основной таблицы проверяется перед чтением.
    Возвращает количество новых размеченных примеров.
    """
    if not os.path.isfile(BOT_DB):
        return 0

    source = None
    target = None
    changed = 0

    try:
        source = sqlite3.connect(BOT_DB, timeout=15)
        source.row_factory = sqlite3.Row

        table = source.execute("""
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name = 'live_signals'
        """).fetchone()

        if not table:
            print(
                "⚠️ OLD ML: в основной базе нет таблицы live_signals",
                flush=True,
            )
            return 0

        columns = {
            row["name"]
            for row in source.execute(
                "PRAGMA table_info(live_signals)"
            ).fetchall()
        }

        game_col = next(
            (c for c in ("game_id", "match_id", "event_id") if c in columns),
            None,
        )
        status_col = next(
            (c for c in ("status", "result", "outcome") if c in columns),
            None,
        )

        if not game_col or not status_col:
            print(
                "⚠️ OLD ML: не найдены поля ID матча или результата "
                "в live_signals",
                flush=True,
            )
            return 0

        # Имена колонок берутся только из списка реальных полей таблицы.
        rows = source.execute(
            f'SELECT "{game_col}" AS game_id, '
            f'"{status_col}" AS status '
            f'FROM live_signals '
            f'WHERE UPPER("{status_col}") IN (?, ?)',
            ("WIN", "LOSE"),
        ).fetchall()

        target = connect_model_db()

        for row in rows:
            game_id = row["game_id"]
            status = str(row["status"] or "").strip().upper()

            if game_id is None:
                continue

            if status == "WIN":
                outcome = 1
            elif status == "LOSE":
                outcome = 0
            else:
                continue

            cursor = target.execute("""
                UPDATE ml_samples
                SET outcome = ?, labeled_ts = ?
                WHERE game_id = ? AND outcome IS NULL
            """, (
                outcome,
                int(time.time()),
                str(game_id),
            ))

            changed += max(cursor.rowcount, 0)

        target.commit()

        if changed:
            result = train()
            if result.get("trained"):
                print(
                    f"🧠 OLD ML: модель обучена на {result['samples']} подтверждённых сигналах",
                    flush=True,
                )
            else:
                print(
                    f"🧠 OLD ML: обучение пока не выполнено — {result.get('reason', 'недостаточно данных')} "
                    f"({result.get('samples', 0)}/{MIN_TRAINING_SAMPLES})",
                    flush=True,
                )

        return changed

    except Exception as e:
        print(
            f"⚠️ OLD ML: ошибка синхронизации результатов: {e}",
            flush=True,
        )
        return 0

    finally:
        if source:
            source.close()
        if target:
            target.close()


# ============================================================
# СОСТОЯНИЕ МОДЕЛИ
# ============================================================

def load_state(con):
    row = con.execute("""
        SELECT weights_json, bias, trained_samples
        FROM ml_state
        WHERE id = 1
    """).fetchone()

    if not row:
        return [0.0] * len(FEATURE_NAMES), 0.0, 0

    try:
        weights = json.loads(row["weights_json"])
    except (TypeError, ValueError, json.JSONDecodeError):
        weights = [0.0] * len(FEATURE_NAMES)

    if not isinstance(weights, list) or len(weights) != len(FEATURE_NAMES):
        weights = [0.0] * len(FEATURE_NAMES)

    weights = [number(value) for value in weights]
    bias = number(row["bias"])
    trained_samples = int(number(row["trained_samples"]))

    return weights, bias, trained_samples


def save_state(con, weights, bias, sample_count):
    now_ts = int(time.time())
    weights_json = json.dumps(weights)

    con.execute("""
        INSERT INTO ml_state (
            id, weights_json, bias, trained_samples, updated_ts
        )
        VALUES (1, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            weights_json = excluded.weights_json,
            bias = excluded.bias,
            trained_samples = excluded.trained_samples,
            updated_ts = excluded.updated_ts
    """, (
        weights_json,
        float(bias),
        int(sample_count),
        now_ts,
    ))

    con.commit()

    # Отдельный JSON нужен для просмотра состояния модели.
    model_path = Path(MODEL_FILE)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = model_path.with_suffix(model_path.suffix + ".tmp")

    payload = {
        "model": "OLD shadow logistic regression",
        "feature_names": FEATURE_NAMES,
        "weights": weights,
        "bias": float(bias),
        "trained_samples": int(sample_count),
        "updated_ts": now_ts,
    }

    try:
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temp_path, model_path)
    except Exception as e:
        print(f"⚠️ OLD ML: не удалось сохранить JSON модели: {e}", flush=True)
        try:
            if temp_path.exists():
                temp_path.unlink()
        except OSError:
            pass


# ============================================================
# ОБУЧЕНИЕ — ЛОГИСТИЧЕСКАЯ РЕГРЕССИЯ НА SGD
# ============================================================

def train():
    con = None

    try:
        con = connect_model_db()

        rows = con.execute("""
            SELECT features_json, outcome
            FROM ml_samples
            WHERE outcome IN (0, 1)
            ORDER BY labeled_ts ASC, created_ts ASC
        """).fetchall()

        samples = []

        for row in rows:
            try:
                feature_dict = json.loads(row["features_json"])
                vector = [
                    number(feature_dict.get(name, 0))
                    for name in FEATURE_NAMES
                ]
                outcome = int(row["outcome"])

                if outcome not in (0, 1):
                    continue

                samples.append((vector, outcome))

            except (TypeError, ValueError, json.JSONDecodeError):
                continue

        sample_count = len(samples)

        if sample_count < MIN_TRAINING_SAMPLES:
            return {
                "trained": False,
                "samples": sample_count,
                "reason": "мало подтверждённых примеров",
            }

        _, _, previous_samples = load_state(con)
        # Каждый запуск заново обучает модель на полной размеченной выборке,
        # чтобы повторные синхронизации не переобучали её на старых примерах.
        weights = [0.0] * len(FEATURE_NAMES)
        bias = 0.0

        # Несколько проходов по сохранённым подтверждённым исходам.
        for _ in range(EPOCHS):
            for vector, target in samples:
                prediction = sigmoid(
                    sum(w * x for w, x in zip(weights, vector)) + bias
                )
                error = prediction - target

                for i, value in enumerate(vector):
                    gradient = error * value + L2 * weights[i]
                    weights[i] -= LEARNING_RATE * gradient

                bias -= LEARNING_RATE * error

        save_state(con, weights, bias, sample_count)

        return {
            "trained": True,
            "samples": sample_count,
            "previous_samples": previous_samples,
        }

    except Exception as e:
        print(f"⚠️ OLD ML: ошибка обучения: {e}", flush=True)
        return {
            "trained": False,
            "samples": 0,
            "reason": str(e),
        }

    finally:
        if con:
            con.close()


# ============================================================
# ПРОГНОЗ МОДЕЛИ — ТОЛЬКО ДЛЯ АНАЛИЗА
# ============================================================

def predict(match, strategy, odds=None):
    """
    Возвращает вероятность от 0 до 1.
    Эта функция не отправляет и не блокирует сигналы.
    """
    con = None

    try:
        con = connect_model_db()
        weights, bias, trained_samples = load_state(con)

        if trained_samples < MIN_TRAINING_SAMPLES:
            return None

        features = extract_features(match, strategy, odds)
        vector = [features.get(name, 0.0) for name in FEATURE_NAMES]

        probability = sigmoid(
            sum(w * x for w, x in zip(weights, vector)) + bias
        )

        return round(probability, 4)

    except Exception as e:
        print(f"⚠️ OLD ML: ошибка расчёта вероятности: {e}", flush=True)
        return None

    finally:
        if con:
            con.close()


# ============================================================
# СТАТИСТИКА МОДЕЛИ
# ============================================================

def status():
    con = None

    try:
        con = connect_model_db()

        row = con.execute("""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN outcome IS NOT NULL THEN 1 ELSE 0 END) AS labeled,
                SUM(CASE WHEN outcome = 1 THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN outcome = 0 THEN 1 ELSE 0 END) AS losses
            FROM ml_samples
        """).fetchone()

        _, _, trained_samples = load_state(con)

        return {
            "total": int(row["total"] or 0),
            "labeled": int(row["labeled"] or 0),
            "wins": int(row["wins"] or 0),
            "losses": int(row["losses"] or 0),
            "trained_samples": trained_samples,
        }

    except Exception as e:
        print(f"⚠️ OLD ML: ошибка чтения статистики: {e}", flush=True)
        return {
            "total": 0,
            "labeled": 0,
            "wins": 0,
            "losses": 0,
            "trained_samples": 0,
        }

    finally:
        if con:
            con.close()