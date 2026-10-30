
import os
import sqlite3
import time
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
    """Создаёт таблицы и добавляет отсутствующие поля без удаления истории."""
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
            "telegram_updated": "INTEGER DEFAULT 0",
            "telegram_retry_after": "INTEGER DEFAULT 0",
            "telegram_edit_attempts": "INTEGER DEFAULT 0",
            "telegram_result_text": "TEXT",
        }

        existing = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(live_signals)"
            ).fetchall()
        }

        for column, sql_type in migrations.items():
            if column not in existing:
                conn.execute(
                    f"ALTER TABLE live_signals "
                    f"ADD COLUMN {column} {sql_type}"
                )

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_live_status
            ON live_signals(status)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_live_sent_at
            ON live_signals(sent_at)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_live_telegram_retry
            ON live_signals(status, telegram_updated, telegram_retry_after)
        """)

    print(f"✅ База данных готова: {DB_PATH}", flush=True)


def save_signal(data):
    """Сохраняет обычный сигнал в таблицу signals."""
    now = int(time.time())

    with get_connection() as conn:
        conn.execute("""
            INSERT INTO signals (
                match_slug, match_name, league, start_time,
                odds, score, xg_home, xg_away,
                home_team, away_team, status, profit, sent_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', 0, ?)
            ON CONFLICT(match_slug) DO NOTHING
        """, (
            data.get("match_slug"),
            data.get("match_name"),
            data.get("league"),
            data.get("start_time"),
            data.get("odds"),
            data.get("score"),
            data.get("xg_home"),
            data.get("xg_away"),
            data.get("home_team"),
            data.get("away_team"),
            data.get("sent_at", now),
        ))


def save_live_signal(data):
    """Сохраняет лайв-сигнал и данные для последующей проверки результата."""
    now = int(time.time())
    game_id = str(data.get("game_id", ""))

    if not game_id:
        print("❌ Нельзя сохранить сигнал без game_id", flush=True)
        return False

    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM live_signals WHERE game_id = ?",
            (game_id,),
        ).fetchone()

        if existing:
            return True

        conn.execute("""
            INSERT INTO live_signals (
                game_id, match_name, league, minute, score,
                strategy, dominant, odds, status, profit, sent_at,
                team1, team2, old_s1, old_s2, date_str,
                signal_ts, message_id, base_text,
                check_after, attempts, telegram_updated,
                telegram_retry_after, telegram_edit_attempts
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', 0, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0
            )
        """, (
            game_id,
            data.get("match_name"),
            data.get("league"),
            data.get("minute", 0),
            data.get("score"),
            data.get("strategy"),
            data.get("dominant"),
            data.get("odds"),
            data.get("sent_at", now),
            data.get("team1"),
            data.get("team2"),
            data.get("old_s1", 0),
            data.get("old_s2", 0),
            data.get("date_str"),
            data.get("signal_ts", now),
            data.get("message_id"),
            data.get("base_text"),
            data.get("check_after", now),
            data.get("attempts", 0),
        ))

        return True


def update_live_result(game_id, is_goal_scored, final_score=None):
    """Фиксирует результат сигнала, не перезаписывая закрытый результат."""
    status = "WIN" if is_goal_scored else "LOSE"
    now = int(time.time())

    with get_connection() as conn:
        row = conn.execute("""
            SELECT status, odds
            FROM live_signals
            WHERE game_id = ?
        """, (str(game_id),)).fetchone()

        if row is None:
            print(
                f"❌ Не найден сигнал для записи результата: {game_id}",
                flush=True,
            )
            return False

        if row["status"] != "PENDING":
            return row["status"] in ("WIN", "LOSE")

        # Считаем чистую прибыль правильно
        odds = float(row["odds"] or 1.0)
        if is_goal_scored:
            profit = max(0.0, odds - 1.0)
        else:
            profit = -1.0

        cur = conn.execute("""
            UPDATE live_signals
            SET status = ?,
                profit = ?,
                final_score = ?,
                result_updated_at = ?
            WHERE game_id = ?
              AND status = 'PENDING'
        """, (
            status,
            profit,
            final_score,
            now,
            str(game_id),
        ))

        return cur.rowcount > 0


def is_live_signal_sent(game_id):
    """Проверяет, записан ли сигнал с таким ID."""
    with get_connection() as conn:
        row = conn.execute("""
            SELECT 1
            FROM live_signals
            WHERE game_id = ?
              AND status IN ('PENDING', 'WIN', 'LOSE')
            LIMIT 1
        """, (str(game_id),)).fetchone()

        return row is not None


def get_live_signals():
    """Возвращает все лайв-сигналы для сайта статистики."""
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT *
            FROM live_signals
            ORDER BY sent_at DESC, id DESC
        """).fetchall()

        return [dict(row) for row in rows]


def get_pending_live_signals():
    """Возвращает сигналы, ожидающие определения результата."""
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT *
            FROM live_signals
            WHERE status = 'PENDING'
            ORDER BY sent_at ASC, id ASC
        """).fetchall()

        return [dict(row) for row in rows]


def update_live_result(game_id, is_goal_scored, final_score=None):
    """Фиксирует результат сигнала, не перезаписывая закрытый результат."""
    status = "WIN" if is_goal_scored else "LOSE"
    profit = 1.0 if is_goal_scored else -1.0
    now = int(time.time())

    with get_connection() as conn:
        row = conn.execute("""
            SELECT status
            FROM live_signals
            WHERE game_id = ?
        """, (str(game_id),)).fetchone()

        if row is None:
            print(
                f"❌ Не найден сигнал для записи результата: {game_id}",
                flush=True,
            )
            return False

        if row["status"] != "PENDING":
            return row["status"] in ("WIN", "LOSE")

        cur = conn.execute("""
            UPDATE live_signals
            SET status = ?,
                profit = ?,
                final_score = ?,
                result_updated_at = ?
            WHERE game_id = ?
              AND status = 'PENDING'
        """, (
            status,
            profit,
            final_score,
            now,
            str(game_id),
        ))

        return cur.rowcount > 0


def get_live_stats():
    """Возвращает основные показатели лайв-статистики."""
    with get_connection() as conn:
        row = conn.execute("""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN status = 'WIN' THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN status = 'LOSE' THEN 1 ELSE 0 END) AS loses,
                SUM(CASE WHEN status = 'PENDING' THEN 1 ELSE 0 END) AS pending,
                COALESCE(SUM(profit), 0) AS profit
            FROM live_signals
        """).fetchone()

        return {
            "total": row["total"] or 0,
            "wins": row["wins"] or 0,
            "loses": row["loses"] or 0,
            "pending": row["pending"] or 0,
            "profit": row["profit"] or 0.0,
        }


def save_live_telegram_result(game_id, result_text):
    """Сохраняет сформированный текст результата для повторной отправки."""
    with get_connection() as conn:
        cur = conn.execute("""
            UPDATE live_signals
            SET telegram_result_text = ?
            WHERE game_id = ?
        """, (result_text, str(game_id)))

        return cur.rowcount > 0


def get_live_telegram_pending():
    """Возвращает завершённые сигналы, сообщения которых нужно обновить."""
    now = int(time.time())

    with get_connection() as conn:
        rows = conn.execute("""
            SELECT *
            FROM live_signals
            WHERE status IN ('WIN', 'LOSE')
              AND COALESCE(telegram_updated, 0) = 0
              AND message_id IS NOT NULL
              AND COALESCE(base_text, '') != ''
              AND COALESCE(telegram_retry_after, 0) <= ?
            ORDER BY result_updated_at ASC, id ASC
        """, (now,)).fetchall()

        return [dict(row) for row in rows]


def mark_live_telegram_updated(game_id):
    """Помечает сообщение как успешно обновлённое."""
    with get_connection() as conn:
        cur = conn.execute("""
            UPDATE live_signals
            SET telegram_updated = 1,
                telegram_retry_after = 0
            WHERE game_id = ?
        """, (str(game_id),))

        return cur.rowcount > 0


def schedule_live_telegram_retry(game_id, delay=60):
    """Планирует следующую попытку редактирования Telegram-сообщения."""
    retry_after = int(time.time()) + max(30, int(delay))

    with get_connection() as conn:
        cur = conn.execute("""
            UPDATE live_signals
            SET telegram_retry_after = ?,
                telegram_edit_attempts =
                    COALESCE(telegram_edit_attempts, 0) + 1
            WHERE game_id = ?
              AND COALESCE(telegram_updated, 0) = 0
        """, (retry_after, str(game_id)))

        return cur.rowcount > 0