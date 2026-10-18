
import os
import sqlite3
from datetime import datetime

DATA_DIR = os.getenv("DATA_DIR", "/app")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "bot_stats.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def init_db():
    """Создаёт таблицы и добавляет недостающие поля без удаления истории."""
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_slug TEXT UNIQUE,
                match_name TEXT,
                league TEXT,
                start_time INTEGER,
                odds REAL,
                score INTEGER,
                xg_home REAL,
                xg_away REAL,
                home_team TEXT,
                away_team TEXT,
                status TEXT DEFAULT 'PENDING',
                profit REAL DEFAULT 0.0,
                sent_at INTEGER
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS live_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id TEXT UNIQUE,
                match_name TEXT,
                league TEXT,
                minute INTEGER,
                score TEXT,
                strategy TEXT,
                dominant TEXT,
                odds REAL,
                status TEXT DEFAULT 'PENDING',
                profit REAL DEFAULT 0.0,
                sent_at INTEGER
            )
        """)

        # Дополнительные поля нужны для восстановления проверок после рестарта.
        migrations = {
            "team1": "TEXT",
            "team2": "TEXT",
            "old_s1": "INTEGER",
            "old_s2": "INTEGER",
            "date_str": "TEXT",
            "signal_ts": "INTEGER",
            "message_id": "INTEGER",
            "base_text": "TEXT",
            "check_after": "INTEGER DEFAULT 0",
            "attempts": "INTEGER DEFAULT 0",
            "final_score": "TEXT",
            "result_updated_at": "INTEGER",
        }

        existing = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(live_signals)").fetchall()
        }

        for column, sql_type in migrations.items():
            if column not in existing:
                conn.execute(
                    f"ALTER TABLE live_signals ADD COLUMN {column} {sql_type}"
                )

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_live_status
            ON live_signals(status)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_live_sent_at
            ON live_signals(sent_at)
        """)

    print(f"✅ База данных готова: {DB_PATH}", flush=True)


def save_signal(data):
    """Сохранение обычного, прематчевого прогноза."""
    try:
        with get_connection() as conn:
            cur = conn.execute("""
                INSERT OR IGNORE INTO signals (
                    match_slug, match_name, league, start_time, odds, score,
                    xg_home, xg_away, home_team, away_team, sent_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data.get("match_slug", ""),
                data.get("match", ""),
                data.get("league", ""),
                data.get("start_ts", 0),
                data.get("odd_tb25", 0.0),
                data.get("score", 0),
                data.get("home_stats", {}).get("avg_xg", 0.0),
                data.get("away_stats", {}).get("avg_xg", 0.0),
                data.get("team1", ""),
                data.get("team2", ""),
                int(datetime.now().timestamp()),
            ))
            return cur.rowcount > 0
    except Exception as e:
        print(f"❌ DB save_signal: {e}", flush=True)
        return False


def save_live_signal(data):
    """Сохраняет лайв-сигнал вместе с данными для проверки результата."""
    game_id = str(data.get("game_id", "")).strip()
    if not game_id:
        print("❌ DB: не сохранён лайв-сигнал без game_id", flush=True)
        return False

    now = int(datetime.now().timestamp())

    try:
        with get_connection() as conn:
            cur = conn.execute("""
                INSERT OR IGNORE INTO live_signals (
                    game_id, match_name, league, minute, score,
                    strategy, dominant, odds, sent_at,
                    team1, team2, old_s1, old_s2, date_str,
                    signal_ts, message_id, base_text,
                    check_after, attempts, status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING')
            """, (
                game_id,
                data.get("match", ""),
                data.get("league", ""),
                data.get("minute", 0),
                str(data.get("score", "0-0")),
                data.get("strategy", ""),
                data.get("dominant", ""),
                data.get("odds", 0.0),
                now,
                data.get("team1"),
                data.get("team2"),
                data.get("old_s1"),
                data.get("old_s2"),
                data.get("date_str"),
                data.get("signal_ts", now),
                data.get("message_id"),
                data.get("base_text", ""),
                data.get("check_after", 0),
                data.get("attempts", 0),
            ))

            if cur.rowcount > 0:
                return True

            # Запись с таким game_id уже существует: не создаём дубль.
            row = conn.execute(
                "SELECT status FROM live_signals WHERE game_id = ?",
                (game_id,),
            ).fetchone()

            return bool(row)

    except Exception as e:
        print(f"❌ DB save_live_signal: {e}", flush=True)
        return False


def update_live_signal_check(game_id, data):
    """Сохраняет состояние проверки и текст сообщения Telegram."""
    allowed = {
        "team1", "team2", "old_s1", "old_s2", "date_str",
        "signal_ts", "message_id", "base_text", "check_after",
        "attempts", "final_score",
    }

    updates = [(key, value) for key, value in data.items() if key in allowed]
    if not updates:
        return True

    assignments = ", ".join(f"{key} = ?" for key, _ in updates)
    values = [value for _, value in updates]
    values.append(str(game_id))

    try:
        with get_connection() as conn:
            conn.execute(
                f"UPDATE live_signals SET {assignments} "
                "WHERE game_id = ? AND status = 'PENDING'",
                values,
            )
        return True
    except Exception as e:
        print(f"❌ DB update_live_signal_check: {e}", flush=True)
        return False


def is_live_signal_sent(game_id):
    """Не допускает повторную отправку сигнала по тому же матчу."""
    try:
        with get_connection() as conn:
            row = conn.execute("""
                SELECT 1
                FROM live_signals
                WHERE game_id = ?
                  AND status IN ('PENDING', 'WIN', 'LOSE')
                LIMIT 1
            """, (str(game_id),)).fetchone()
            return row is not None
    except Exception as e:
        print(f"❌ DB is_live_signal_sent: {e}", flush=True)
        # При ошибке базы безопаснее не отправлять возможный дубль.
        return True


def mark_live_signal_sent(game_id):
    """Совместимость со старым кодом; не перезаписывает существующую запись."""
    try:
        with get_connection() as conn:
            conn.execute("""
                INSERT OR IGNORE INTO live_signals (
                    game_id, sent_at, status
                )
                VALUES (?, ?, 'PENDING')
            """, (str(game_id), int(datetime.now().timestamp())))
    except Exception as e:
        print(f"❌ DB mark_live_signal_sent: {e}", flush=True)


def get_all_signals():
    """Возвращает прематчевые прогнозы."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM signals ORDER BY sent_at DESC"
        ).fetchall()
        return [dict(row) for row in rows]


def get_live_signals():
    """Возвращает лайв-прогнозы для сайта."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM live_signals ORDER BY sent_at DESC"
        ).fetchall()
        return [dict(row) for row in rows]


def get_pending_signals():
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM signals WHERE status = 'PENDING'"
        ).fetchall()
        return [dict(row) for row in rows]


def get_pending_live_signals():
    """Возвращает незавершённые лайв-прогнозы для восстановления после рестарта."""
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT *
            FROM live_signals
            WHERE status = 'PENDING'
            ORDER BY sent_at ASC
        """).fetchall()
        return [dict(row) for row in rows]


def update_result(match_slug, goals_total):
    """Результат прематчевого прогноза на тотал больше 2.5."""
    try:
        with get_connection() as conn:
            row = conn.execute("""
                SELECT odds
                FROM signals
                WHERE match_slug = ? AND status = 'PENDING'
            """, (match_slug,)).fetchone()

            if not row:
                return False

            won = float(goals_total) > 2.5
            status = "WIN" if won else "LOSE"
            odds = float(row["odds"] or 0)
            profit = odds - 1.0 if won else -1.0

            conn.execute("""
                UPDATE signals
                SET status = ?, profit = ?
                WHERE match_slug = ? AND status = 'PENDING'
            """, (status, profit, match_slug))

        return True
    except Exception as e:
        print(f"❌ DB update_result: {e}", flush=True)
        return False


def update_live_result(game_id, is_goal_scored, final_score=None):
    """Фиксирует итог лайв-сигнала только один раз."""
    game_id = str(game_id)
    now = int(datetime.now().timestamp())

    try:
        with get_connection() as conn:
            row = conn.execute("""
                SELECT odds, status
                FROM live_signals
                WHERE game_id = ?
            """, (game_id,)).fetchone()

            if not row:
                print(f"⚠️ DB: сигнал {game_id} не найден для фиксации результата",
                      flush=True)
                return False

            if row["status"] != "PENDING":
                return row["status"] in ("WIN", "LOSE")

            won = bool(is_goal_scored)
            status = "WIN" if won else "LOSE"
            odds = float(row["odds"] or 0)
            profit = odds - 1.0 if won else -1.0

            cur = conn.execute("""
                UPDATE live_signals
                SET status = ?, profit = ?, final_score = ?,
                    result_updated_at = ?
                WHERE game_id = ? AND status = 'PENDING'
            """, (status, profit, final_score, now, game_id))

            return cur.rowcount > 0

    except Exception as e:
        print(f"❌ DB update_live_result: {e}", flush=True)
        return False


def get_stats():
    """Общая статистика прематчевых прогнозов."""
    with get_connection() as conn:
        row = conn.execute("""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN status = 'WIN' THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN status = 'LOSE' THEN 1 ELSE 0 END) AS loses
            FROM signals
        """).fetchone()

        return {
            "total": row["total"] or 0,
            "wins": row["wins"] or 0,
            "loses": row["loses"] or 0,
        }


def get_live_stats():
    """Статистика именно лайв-прогнозов."""
    with get_connection() as conn:
        row = conn.execute("""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN status = 'WIN' THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN status = 'LOSE' THEN 1 ELSE 0 END) AS loses,
                SUM(CASE WHEN status = 'PENDING' THEN 1 ELSE 0 END) AS pending,
                COALESCE(SUM(profit), 0) AS profit
            FROM live_signals
            WHERE game_id IS NOT NULL AND game_id != ''
        """).fetchone()

        return {
            "total": row["total"] or 0,
            "wins": row["wins"] or 0,
            "loses": row["loses"] or 0,
            "pending": row["pending"] or 0,
            "profit": float(row["profit"] or 0),
        }