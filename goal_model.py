
# -*- coding: utf-8 -*-
"""
OLD Football — лёгкая ML-модель.
Режим: SHADOW (теневой).
Модель собирает признаки и обучается на подтверждённых результатах,
но сама не разрешает и не запрещает отправку прогнозов.
Используется только стандартная библиотека Python.
"""

import json
import math
import os
import sqlite3
import time
from pathlib import Path


# ============================================================
# ФАЙЛЫ
# ============================================================

DATA_DIR = os.getenv("DATA_DIR", "/app")

BOT_DB = os.getenv(
    "FOOTBALL_BOT_DB",
    os.path.join(DATA_DIR, "bot_stats.db")
)

MODEL_DB = os.getenv(
    "FOOTBALL_MODEL_DB",
    os.path.join(DATA_DIR, "football_model.sqlite3")
)

MODEL_FILE = os.getenv(
    "FOOTBALL_MODEL_FILE",
    os.path.join(DATA_DIR, "football_model.json")
)


# ============================================================
# НАСТРОЙКИ ОБУЧЕНИЯ
# ============================================================

MIN_TRAINING_SAMPLES = 30

LEARNING_RATE = 0.05
L2 = 0.0005

EPOCHS = 3

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

# Масштабирование признаков для стабильного обучения.
SCALES = {
    "minute": 90.0,
    "score_total": 5.0,
    "score_diff": 4.0,
    "xg_total": 5.0,
    "xg_diff": 4.0,
    "shots_on_total": 15.0,
    "shots_on_diff": 10.0,
    "shots_total": 35.0,
    "shots_diff": 20.0,
    "attacks_total": 120.0,
    "attacks_diff": 80.0,
    "corners_total": 15.0,
    "corners_diff": 10.0,
    "red_total": 3.0,
    "trend_available": 1.0,
    "trend_xg": 2.0,
    "trend_shots_on": 8.0,
    "trend_shots": 15.0,
    "trend_corners": 6.0,
    "trend_attacks": 50.0,
    "strategy_xg": 1.0,
    "strategy_shots": 1.0,
    "strategy_corners": 1.0,
    "strategy_attacks": 1.0,
    "strategy_combo": 1.0,
    "odds": 3.0,
}


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

def number(value, default=0.0):
    """Безопасно преобразует значение в число."""
    try:
        result = float(value or 0)

        if math.isfinite(result):
            return result

    except (TypeError, ValueError):
        pass

    return default


def sigmoid(value):
    """Преобразует результат модели в вероятность от 0 до 1."""
    value = max(-30.0, min(30.0, value))
    return 1.0 / (1.0 + math.exp(-value))


def connect_model_db():
    """Открывает БД модели и создаёт таблицы при необходимости."""
    Path(MODEL_DB).parent.mkdir(
        parents=True,
        exist_ok=True
    )

    con = sqlite3.connect(
        MODEL_DB,
        timeout=15
    )

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
# ПОДГОТОВКА ПРИЗНАКОВ МАТЧА
# ============================================================

def extract_features(match, strategy, odds=None):
    """
    Формирует числовые признаки из данных stats_parser.py.

    Используются статистика матча, динамика за последние минуты,
    выбранная стратегия и коэффициент.
    """

    trend = match.get("trend") or {}

    xg1 = number(match.get("xg1"))
    xg2 = number(match.get("xg2"))

    shots_on1 = number(match.get("shots_on1"))
    shots_on2 = number(match.get("shots_on2"))

    shots1 = number(match.get("shots_all1"))
    shots2 = number(match.get("shots_all2"))

    attacks1 = number(match.get("att1"))
    attacks2 = number(match.get("att2"))

    corners1 = number(match.get("corners1"))
    corners2 = number(match.get("corners2"))

    red1 = number(match.get("red1"))
    red2 = number(match.get("red2"))

    score1 = number(match.get("s1"))
    score2 = number(match.get("s2"))

    strategy_name = str(
        (strategy or {}).get("strategy", "")
    ).lower()

    raw = {
        "minute": number(match.get("minute")),

        "score_total": score1 + score2,
        "score_diff": abs(score1 - score2),

        "xg_total": xg1 + xg2,
        "xg_diff": abs(xg1 - xg2),

        "shots_on_total": shots_on1 + shots_on2,
        "shots_on_diff": abs(shots_on1 - shots_on2),

        "shots_total": shots1 + shots2,
        "shots_diff": abs(shots1 - shots2),

        "attacks_total": attacks1 + attacks2,
        "attacks_diff": abs(attacks1 - attacks2),

        "corners_total": corners1 + corners2,
        "corners_diff": abs(corners1 - corners2),

        "red_total": red1 + red2,

        "trend_available": (
            1.0 if trend.get("available") else 0.0
        ),

        "trend_xg": number(trend.get("xg_delta")),
        "trend_shots_on": number(
            trend.get("shots_on_delta")
        ),
        "trend_shots": number(
            trend.get("shots_delta")
        ),
        "trend_corners": number(
            trend.get("corners_delta")
        ),
        "trend_attacks": number(
            trend.get("attacks_delta")
        ),

        "strategy_xg": (
            1.0 if "xg-мощь" in strategy_name else 0.0
        ),

        "strategy_shots": (
            1.0
            if strategy_name == "удары"
            else 0.0
        ),

        "strategy_corners": (
            1.0
            if "углы" in strategy_name
            else 0.0
        ),

        "strategy_attacks": (
            1.0
            if "опасные атаки" in strategy_name
            else 0.0
        ),

        "strategy_combo": (
            1.0
            if "комбо" in strategy_name
            else 0.0
        ),

        "odds": number(
            odds,
            number((strategy or {}).get("actual_odd"))
        ),
    }

    # Нормализуем значения, чтобы большие числа
    # не перетягивали на себя всё обучение.
    result = {}

    for name in FEATURE_NAMES:
        scale = SCALES.get(name, 1.0)
        result[name] = raw.get(name, 0.0) / scale

    return result


# ============================================================
# СОХРАНЕНИЕ СИГНАЛА ДЛЯ ОБУЧЕНИЯ
# ============================================================

def observe(match, strategy, odds=None):
    """
    Сохраняет признаки отправленного сигнала.

    Один game_id — одна запись. Повторный вызов не создаёт
    дубликат и не перезаписывает ранее сохранённые признаки.
    """

    game_id = match.get("game_id")

    if game_id is None:
        return False

    features = extract_features(
        match,
        strategy,
        odds=odds
    )

    strategy_name = str(
        (strategy or {}).get("strategy", "")
    )

    actual_odds = number(
        odds,
        number((strategy or {}).get("actual_odd"))
    )

    con = connect_model_db()

    try:
        cursor = con.execute("""
            INSERT OR IGNORE INTO ml_samples (
                game_id,
                match_name,
                strategy,
                features_json,
                odds,
                outcome,
                created_ts,
                labeled_ts
            )
            VALUES (?, ?, ?, ?, ?, NULL, ?, NULL)
        """, (
            str(game_id),
            str(match.get("match", "")),
            strategy_name,
            json.dumps(
                features,
                ensure_ascii=False
            ),
            actual_odds,
            int(time.time()),
        ))

        con.commit()

        return cursor.rowcount > 0

    finally:
        con.close()


# ============================================================
# ПЕРЕНОС ПОДТВЕРЖДЁННЫХ РЕЗУЛЬТАТОВ ИЗ ОСНОВНОЙ БД
# ============================================================

def sync_confirmed_results():
    """
    Читает WIN/LOSE из bot_stats.db.

    WIN  = 1
    LOSE = 0

    PENDING никогда не считается проигрышем.
    """

    if not os.path.exists(BOT_DB):
        return 0

    model_con = connect_model_db()
    bot_con = None

    try:
        bot_con = sqlite3.connect(
            BOT_DB,
            timeout=10
        )

        bot_con.row_factory = sqlite3.Row

        columns = {
            row[1]
            for row in bot_con.execute(
                "PRAGMA table_info(live_signals)"
            )
        }

        if not {"game_id", "status"}.issubset(columns):
            print(
                "⚠️ OLD ML: в live_signals нет нужных колонок",
                flush=True
            )
            return 0

        rows = bot_con.execute("""
            SELECT game_id, status
            FROM live_signals
            WHERE status IN ('WIN', 'LOSE')
        """).fetchall()

        changed = 0

        for row in rows:
            outcome = (
                1
                if str(row["status"]).upper() == "WIN"
                else 0
            )

            cursor = model_con.execute("""
                UPDATE ml_samples
                SET outcome = ?, labeled_ts = ?
                WHERE game_id = ?
                  AND outcome IS NULL
            """, (
                outcome,
                int(time.time()),
                str(row["game_id"]),
            ))

            changed += cursor.rowcount

        model_con.commit()

        return changed

    except sqlite3.Error as error:
        print(
            f"⚠️ OLD ML: ошибка синхронизации результатов: {error}",
            flush=True
        )
        return 0

    finally:
        if bot_con is not None:
            bot_con.close()

        model_con.close()


# ============================================================
# ЗАГРУЗКА И СОХРАНЕНИЕ СОСТОЯНИЯ МОДЕЛИ
# ============================================================

def load_state(con):
    row = con.execute("""
        SELECT weights_json, bias, trained_samples
        FROM ml_state
        WHERE id = 1
    """).fetchone()

    if row is None:
        return [0.0] * len(FEATURE_NAMES), 0.0, 0

    try:
        weights = json.loads(row["weights_json"])

        if len(weights) != len(FEATURE_NAMES):
            raise ValueError("неверное количество весов")

        return (
            [float(value) for value in weights],
            float(row["bias"]),
            int(row["trained_samples"]),
        )

    except (ValueError, TypeError, json.JSONDecodeError):
        return [0.0] * len(FEATURE_NAMES), 0.0, 0


def save_state(con, weights, bias, sample_count):
    con.execute("""
        INSERT INTO ml_state (
            id,
            weights_json,
            bias,
            trained_samples,
            updated_ts
        )
        VALUES (1, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            weights_json = excluded.weights_json,
            bias = excluded.bias,
            trained_samples = excluded.trained_samples,
            updated_ts = excluded.updated_ts
    """, (
        json.dumps(weights),
        float(bias),
        int(sample_count),
        int(time.time()),
    ))

    con.commit()

    # Дополнительная копия состояния в JSON.
    # Если не удастся записать файл, основная БД сохранится.
    try:
        Path(MODEL_FILE).parent.mkdir(
            parents=True,
            exist_ok=True
        )

        temp_file = MODEL_FILE + ".tmp"

        with open(
            temp_file,
            "w",
            encoding="utf-8"
        ) as file:
            json.dump({
                "feature_names": FEATURE_NAMES,
                "weights": weights,
                "bias": bias,
                "trained_samples": sample_count,
                "updated_ts": int(time.time()),
            }, file, ensure_ascii=False, indent=2)

        os.replace(temp_file, MODEL_FILE)

    except OSError as error:
        print(
            f"⚠️ OLD ML: не удалось сохранить JSON модели: {error}",
            flush=True
        )


# ============================================================
# ОБУЧЕНИЕ
# ============================================================

def train():
    """
    Обучает логистическую регрессию простым SGD.

    До MIN_TRAINING_SAMPLES подтверждённых сигналов модель
    не обучается. Обучение запускается только по вызову train().
    """

    con = connect_model_db()

    try:
        rows = con.execute("""
            SELECT features_json, outcome
            FROM ml_samples
            WHERE outcome IN (0, 1)
            ORDER BY created_ts
        """).fetchall()

        data = []

        for row in rows:
            try:
                features = json.loads(
                    row["features_json"]
                )

                vector = [
                    number(features.get(name))
                    for name in FEATURE_NAMES
                ]

                data.append((
                    vector,
                    int(row["outcome"])
                ))

            except (TypeError, ValueError, json.JSONDecodeError):
                continue

        if len(data) < MIN_TRAINING_SAMPLES:
            return {
                "trained": False,
                "samples": len(data),
                "reason": "мало подтверждённых примеров",
            }

        weights, bias, previous_count = load_state(con)

        # Каждый обучающий проход начинается с текущих весов.
        # Небольшое число эпох ограничивает нагрузку на CPU.
        for _ in range(EPOCHS):
            for vector, target in data:
                score = sum(
                    weight * value
                    for weight, value in zip(weights, vector)
                ) + bias

                prediction = sigmoid(score)
                error = prediction - target

                for index, value in enumerate(vector):
                    gradient = (
                        error * value
                        + L2 * weights[index]
                    )

                    weights[index] -= (
                        LEARNING_RATE * gradient
                    )

                bias -= LEARNING_RATE * error

        save_state(
            con,
            weights,
            bias,
            len(data)
        )

        return {
            "trained": True,
            "samples": len(data),
            "previous_samples": previous_count,
        }

    finally:
        con.close()


# ============================================================
# ПРОГНОЗ МОДЕЛИ
# ============================================================

def predict(match, strategy, odds=None):
    """
    Возвращает вероятность 0..1.

    None означает, что пока недостаточно данных для обучения.
    Это только оценка модели, а не гарантия следующего гола.
    """

    con = connect_model_db()

    try:
        weights, bias, trained = load_state(con)

        if trained < MIN_TRAINING_SAMPLES:
            return None

        features = extract_features(
            match,
            strategy,
            odds=odds
        )

        vector = [
            features[name]
            for name in FEATURE_NAMES
        ]

        score = sum(
            weight * value
            for weight, value in zip(weights, vector)
        ) + bias

        return round(sigmoid(score), 4)

    finally:
        con.close()


# ============================================================
# СТАТИСТИКА МОДЕЛИ
# ============================================================

def status():
    """Возвращает число сохранённых, размеченных и выигранных сигналов."""

    con = connect_model_db()

    try:
        total = con.execute("""
            SELECT COUNT(*)
            FROM ml_samples
        """).fetchone()[0]

        labeled = con.execute("""
            SELECT COUNT(*)
            FROM ml_samples
            WHERE outcome IS NOT NULL
        """).fetchone()[0]

        wins = con.execute("""
            SELECT COUNT(*)
            FROM ml_samples
            WHERE outcome = 1
        """).fetchone()[0]

        _, _, trained = load_state(con)

        return {
            "total": total,
            "labeled": labeled,
            "wins": wins,
            "losses": labeled - wins,
            "trained_samples": trained,
        }

    finally:
        con.close()