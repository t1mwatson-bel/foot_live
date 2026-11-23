import os
import sqlite3
import time
from datetime import datetime

DATA_DIR = os.getenv("DATA_DIR", "/app")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "bot_stats.db")


def _backup_broken_database():
    """Перемещает нечитаемую БД в резервный файл, не удаляя её."""
    if not os.path.exists(DB_PATH):
        return None

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{DB_PATH}.broken_{stamp}.bak"
    suffix = 1
    while os.path.exists(backup_path):
        backup_path = f"{DB_PATH}.broken_{stamp}_{suffix}.bak"
        suffix += 1

    os.replace(DB_PATH, backup_path)
    for extra in (DB_PATH + "-wal", DB_PATH + "-shm"):
        if os.path.exists(extra):
            try:
                os.replace(extra, backup_path + extra[len(DB_PATH):])
            except OSError:
                pass

    print(
        f"⚠️ Старая SQLite-база повреждена или имеет неверный формат. "
        f"Она сохранена как {backup_path}. Создаю новую базу.",
        flush=True,
    )
    return backup_path


def _database_is_healthy():
    """Проверяет SQLite до запуска миграций."""
    if not os.path.exists(DB_PATH) or os.path.getsize(DB_PATH) == 0:
        return True

    try:
        with open(DB_PATH, "rb") as file:
            header = file.read(16)
        if header != b"SQLite format 3\x00":
            return False

        conn = sqlite3.connect(DB_PATH, timeout=10)
        try:
            result = conn.execute("PRAGMA quick_check").fetchone()
            return bool(result and result[0] == "ok")
        finally:
            conn.close()
    except (sqlite3.DatabaseError, OSError):
        return False


def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Проверяет БД, создаёт таблицы и добавляет недостающие поля."""
    if not _database_is_healthy():
        _backup_broken_database()

    try:
        with get_connection() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
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
                for row in conn.execute("PRAGMA table_info(live_signals)").fetchall()
            }
            for column, sql_type in migrations.items():
                if column not in existing:
                    conn.execute(
                        f"ALTER TABLE live_signals ADD COLUMN {column} {sql_type}"
                    )

            conn.execute("CREATE INDEX IF NOT EXISTS idx_live_status ON live_signals(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_live_sent_at ON live_signals(sent_at)")
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_live_telegram_retry
                ON live_signals(status, telegram_updated, telegram_retry_after)
            """)
            conn.commit()
    except sqlite3.DatabaseError:
        # Защита на случай ошибки, выявленной только во время миграции.
        _backup_broken_database()
        with get_connection() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    match_slug TEXT UNIQUE, match_name TEXT, league TEXT,
                    start_time INTEGER, odds REAL, score INTEGER,
                    xg_home REAL, xg_away REAL, home_team TEXT, away_team TEXT,
                    status TEXT DEFAULT 'PENDING', profit REAL DEFAULT 0.0,
                    sent_at INTEGER
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS live_signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    game_id TEXT UNIQUE, match_name TEXT, league TEXT,
                    minute INTEGER, score TEXT, strategy TEXT, dominant TEXT,
                    odds REAL, status TEXT DEFAULT 'PENDING',
                    profit REAL DEFAULT 0.0, sent_at INTEGER,
                    team1 TEXT, team2 TEXT, old_s1 INTEGER, old_s2 INTEGER,
                    date_str TEXT, signal_ts INTEGER, message_id INTEGER,
                    base_text TEXT, check_after INTEGER DEFAULT 0,
                    attempts INTEGER DEFAULT 0, final_score TEXT,
                    result_updated_at INTEGER,
                    telegram_updated INTEGER DEFAULT 0,
                    telegram_retry_after INTEGER DEFAULT 0,
                    telegram_edit_attempts INTEGER DEFAULT 0,
                    telegram_result_text TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_live_status ON live_signals(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_live_sent_at ON live_signals(sent_at)")
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_live_telegram_retry
                ON live_signals(status, telegram_updated, telegram_retry_after)
            """)
            conn.commit()

    print(f"✅ База данных готова: {DB_PATH}", flush=True)


def save_signal(data):
    now = int(time.time())
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO signals (
                match_slug, match_name, league, start_time, odds, score,
                xg_home, xg_away, home_team, away_team, status, profit, sent_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', 0, ?)
            ON CONFLICT(match_slug) DO NOTHING
        """, (
            data.get("match_slug"), data.get("match_name"), data.get("league"),
            data.get("start_time"), data.get("odds"), data.get("score"),
            data.get("xg_home"), data.get("xg_away"), data.get("home_team"),
            data.get("away_team"), data.get("sent_at", now),
        ))


def save_live_signal(data):
    now = int(time.time())
    game_id = str(data.get("game_id", "")).strip()
    if not game_id:
        print("❌ Нельзя сохранить сигнал без game_id", flush=True)
        return False

    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM live_signals WHERE game_id = ?", (game_id,)
        ).fetchone()
        if existing:
            return True

        conn.execute("""
            INSERT INTO live_signals (
                game_id, match_name, league, minute, score, strategy, dominant,
                odds, status, profit, sent_at, team1, team2, old_s1, old_s2,
                date_str, signal_ts, message_id, base_text, check_after,
                attempts, telegram_updated, telegram_retry_after,
                telegram_edit_attempts
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0)
        """, (
            game_id, data.get("match_name"), data.get("league"),
            data.get("minute", 0), data.get("score"), data.get("strategy"),
            data.get("dominant"), data.get("odds"), data.get("sent_at", now),
            data.get("team1"), data.get("team2"), data.get("old_s1", 0),
            data.get("old_s2", 0), data.get("date_str"),
            data.get("signal_ts", now), data.get("message_id"),
            data.get("base_text"), data.get("check_after", now),
            data.get("attempts", 0),
        ))
        return True


def update_live_signal_check(game_id, data):
    allowed = {
        "team1", "team2", "old_s1", "old_s2", "date_str", "signal_ts",
        "message_id", "base_text", "check_after", "attempts",
    }
    fields = {key: value for key, value in data.items() if key in allowed}
    if not fields:
        return False
    assignments = ", ".join(f"{key} = ?" for key in fields)
    with get_connection() as conn:
        cur = conn.execute(
            f"UPDATE live_signals SET {assignments} WHERE game_id = ? AND status = 'PENDING'",
            (*fields.values(), str(game_id)),
        )
        return cur.rowcount > 0


def update_live_result(game_id, is_goal_scored, final_score=None):
    """Записывает исход один раз; прибыль считается на единицу ставки."""
    status = "WIN" if is_goal_scored else "LOSE"
    now = int(time.time())
    with get_connection() as conn:
        row = conn.execute(
            "SELECT status, odds FROM live_signals WHERE game_id = ?",
            (str(game_id),),
        ).fetchone()
        if row is None:
            print(f"❌ Не найден сигнал для записи результата: {game_id}", flush=True)
            return False
        if row["status"] != "PENDING":
            return row["status"] == status

        odds = float(row["odds"] or 1.0)
        profit = max(0.0, odds - 1.0) if is_goal_scored else -1.0
        cur = conn.execute("""
            UPDATE live_signals
            SET status = ?, profit = ?, final_score = ?, result_updated_at = ?
            WHERE game_id = ? AND status = 'PENDING'
        """, (status, profit, final_score, now, str(game_id)))
        return cur.rowcount > 0


def is_live_signal_sent(game_id):
    with get_connection() as conn:
        row = conn.execute("""
            SELECT 1 FROM live_signals
            WHERE game_id = ? AND status IN ('PENDING', 'WIN', 'LOSE') LIMIT 1
        """, (str(game_id),)).fetchone()
        return row is not None


def get_live_signals():
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM live_signals ORDER BY sent_at DESC, id DESC"
        ).fetchall()
        return [dict(row) for row in rows]


def get_pending_live_signals():
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT * FROM live_signals
            WHERE status = 'PENDING' ORDER BY sent_at ASC, id ASC
        """).fetchall()
        return [dict(row) for row in rows]


def get_live_stats():
    with get_connection() as conn:
        row = conn.execute("""
            SELECT COUNT(*) AS total,
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
    with get_connection() as conn:
        cur = conn.execute(
            "UPDATE live_signals SET telegram_result_text = ? WHERE game_id = ?",
            (result_text, str(game_id)),
        )
        return cur.rowcount > 0


def get_live_telegram_pending():
    now = int(time.time())
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT * FROM live_signals
            WHERE status IN ('WIN', 'LOSE')
              AND COALESCE(telegram_updated, 0) = 0
              AND message_id IS NOT NULL
              AND COALESCE(base_text, '') != ''
              AND COALESCE(telegram_retry_after, 0) <= ?
            ORDER BY result_updated_at ASC, id ASC
        """, (now,)).fetchall()
        return [dict(row) for row in rows]


def mark_live_telegram_updated(game_id):
    with get_connection() as conn:
        cur = conn.execute("""
            UPDATE live_signals
            SET telegram_updated = 1, telegram_retry_after = 0
            WHERE game_id = ?
        """, (str(game_id),))
        return cur.rowcount > 0


def schedule_live_telegram_retry(game_id, delay=60):
    retry_after = int(time.time()) + max(30, int(delay))
    with get_connection() as conn:
        cur = conn.execute("""
            UPDATE live_signals
            SET telegram_retry_after = ?,
                telegram_edit_attempts = COALESCE(telegram_edit_attempts, 0) + 1
            WHERE game_id = ? AND COALESCE(telegram_updated, 0) = 0
        """, (retry_after, str(game_id)))
        return cur.rowcount > 0
