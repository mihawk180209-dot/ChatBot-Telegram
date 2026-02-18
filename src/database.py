# src/database.py
import os
import aiosqlite
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)
DB_FILE = os.getenv("DB_FILE", "bot_memory.db")

# ╔══════════════════════════════════════════════════════════╗
# ║              💾 DATABASE INITIALIZATION                  ║
# ╚══════════════════════════════════════════════════════════╝

async def _get_existing_columns(db: aiosqlite.Connection, table: str) -> set[str]:
    """Get set of existing column names for a table."""
    columns = set()
    try:
        async with db.execute(f"PRAGMA table_info({table})") as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                columns.add(row[1])
    except Exception as e:
        logger.warning(f"⚠️ Could not read columns for {table}: {e}")
    return columns


async def _migrate_tables(db: aiosqlite.Connection):
    """
    Safely add new columns to existing tables.
    
    SQLite restriction: ALTER TABLE ADD COLUMN cannot use non-constant defaults
    like CURRENT_TIMESTAMP. So we use constant defaults ('', 0) during ALTER,
    then backfill with actual values.
    """

    # ── Column additions (constant defaults only!) ───────────
    migrations = [
        # (table, column, type_with_constant_default)
        ("user_stats", "first_seen",       "TEXT DEFAULT ''"),
        ("user_stats", "last_active",      "TEXT DEFAULT ''"),
        ("user_stats", "total_chars_sent", "INTEGER DEFAULT 0"),
        ("user_stats", "reset_count",      "INTEGER DEFAULT 0"),
        ("chat_history", "char_count",     "INTEGER DEFAULT 0"),
    ]

    migrated_columns = []

    for table, column, col_type in migrations:
        existing = await _get_existing_columns(db, table)
        if column not in existing:
            try:
                await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
                migrated_columns.append(f"{table}.{column}")
                logger.info(f"📦 Migration: Added {table}.{column}")
            except Exception as e:
                logger.error(f"❌ Migration failed for {table}.{column}: {e}")

    # ── Backfill empty timestamps with current time ──────────
    if "user_stats.first_seen" in migrated_columns or "user_stats.last_active" in migrated_columns:
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        try:
            await db.execute(
                "UPDATE user_stats SET first_seen = ? WHERE first_seen = '' OR first_seen IS NULL",
                (now_str,),
            )
            await db.execute(
                "UPDATE user_stats SET last_active = ? WHERE last_active = '' OR last_active IS NULL",
                (now_str,),
            )
            logger.info(f"📦 Backfilled timestamps for existing users with: {now_str}")
        except Exception as e:
            logger.warning(f"⚠️ Timestamp backfill failed: {e}")

    if migrated_columns:
        logger.info(f"📦 Migration complete: {len(migrated_columns)} columns added")


async def _has_column(db: aiosqlite.Connection, table: str, column: str) -> bool:
    """Quick check if a specific column exists in a table."""
    columns = await _get_existing_columns(db, table)
    return column in columns


async def init_db():
    """Initialize database with all required tables and indexes."""
    async with aiosqlite.connect(DB_FILE) as db:
        # ── Chat history table ───────────────────────────────
        await db.execute("""
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # ── User stats table (base) ─────────────────────────
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_stats (
                user_id INTEGER PRIMARY KEY,
                message_count INTEGER DEFAULT 0
            )
        """)

        # ── Run migrations ───────────────────────────────────
        await _migrate_tables(db)

        # ── Performance indexes ──────────────────────────────
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_chat_user_id 
            ON chat_history(user_id)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_chat_timestamp 
            ON chat_history(timestamp)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_chat_user_time 
            ON chat_history(user_id, id DESC)
        """)

        await db.commit()

    # ── Log database info ────────────────────────────────────
    info = await get_db_info()
    logger.info(
        f"💾 Database initialized | "
        f"Users: {info['total_users']} | "
        f"Messages: {info['total_messages']} | "
        f"Size: {info['db_size']} | "
        f"File: {DB_FILE}"
    )


# ╔══════════════════════════════════════════════════════════╗
# ║              💬 CHAT HISTORY OPERATIONS                  ║
# ╚══════════════════════════════════════════════════════════╝

async def add_message(user_id: int, role: str, content: str):
    """Store a message and update user stats atomically."""
    char_count = len(content)
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    async with aiosqlite.connect(DB_FILE) as db:
        # ── Check which columns exist ────────────────────────
        has_char_count = await _has_column(db, "chat_history", "char_count")
        has_last_active = await _has_column(db, "user_stats", "last_active")
        has_total_chars = await _has_column(db, "user_stats", "total_chars_sent")
        has_first_seen = await _has_column(db, "user_stats", "first_seen")

        # ── Insert chat message ──────────────────────────────
        if has_char_count:
            await db.execute(
                "INSERT INTO chat_history (user_id, role, content, char_count) VALUES (?, ?, ?, ?)",
                (user_id, role, content, char_count),
            )
        else:
            await db.execute(
                "INSERT INTO chat_history (user_id, role, content) VALUES (?, ?, ?)",
                (user_id, role, content),
            )

        # ── Update user stats (only for user messages) ──────
        if role == "user":
            if has_last_active and has_total_chars and has_first_seen:
                await db.execute(
                    """
                    INSERT INTO user_stats (user_id, message_count, first_seen, last_active, total_chars_sent)
                    VALUES (?, 1, ?, ?, ?)
                    ON CONFLICT(user_id) DO UPDATE SET
                        message_count = message_count + 1,
                        last_active = ?,
                        total_chars_sent = total_chars_sent + ?
                    """,
                    (user_id, now_str, now_str, char_count, now_str, char_count),
                )
            else:
                await db.execute(
                    """
                    INSERT INTO user_stats (user_id, message_count) 
                    VALUES (?, 1)
                    ON CONFLICT(user_id) DO UPDATE SET message_count = message_count + 1
                    """,
                    (user_id,),
                )

        await db.commit()


async def get_history(user_id: int, limit: int = 10) -> list:
    """Fetch recent conversation history in chronological order."""
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute(
            "SELECT role, content FROM chat_history WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        ) as cursor:
            rows = await cursor.fetchall()
            return [{"role": row[0], "content": row[1]} for row in reversed(rows)]


async def clear_history(user_id: int):
    """Clear all chat history for a user and increment reset counter if column exists."""
    async with aiosqlite.connect(DB_FILE) as db:
        # ── Count messages being deleted ─────────────────────
        async with db.execute(
            "SELECT COUNT(*) FROM chat_history WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            deleted_count = row[0] if row else 0

        # ── Delete history ───────────────────────────────────
        await db.execute(
            "DELETE FROM chat_history WHERE user_id = ?", (user_id,)
        )

        # ── Increment reset counter (safe) ───────────────────
        has_reset = await _has_column(db, "user_stats", "reset_count")
        has_active = await _has_column(db, "user_stats", "last_active")
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        if has_reset and has_active:
            await db.execute(
                "UPDATE user_stats SET reset_count = reset_count + 1, last_active = ? WHERE user_id = ?",
                (now_str, user_id),
            )
        elif has_reset:
            await db.execute(
                "UPDATE user_stats SET reset_count = reset_count + 1 WHERE user_id = ?",
                (user_id,),
            )

        await db.commit()

    if deleted_count > 0:
        logger.info(f"🧹 Cleared {deleted_count} messages for user {user_id}")


async def cleanup_old_history(ttl_hours: int = 24):
    """Remove chat history older than TTL."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=ttl_hours)
    cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")

    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM chat_history WHERE timestamp < ?", (cutoff_str,)
        ) as cursor:
            row = await cursor.fetchone()
            count = row[0] if row else 0

        if count > 0:
            await db.execute(
                "DELETE FROM chat_history WHERE timestamp < ?", (cutoff_str,)
            )
            await db.commit()
            logger.info(f"🧹 Cleanup: Removed {count} messages older than {ttl_hours}h")

    return count


# ╔══════════════════════════════════════════════════════════╗
# ║              📊 STATISTICS & ANALYTICS                   ║
# ╚══════════════════════════════════════════════════════════╝

async def get_global_stats() -> dict:
    """Get comprehensive global bot statistics."""
    async with aiosqlite.connect(DB_FILE) as db:
        # ── Basic counts ─────────────────────────────────────
        async with db.execute(
            "SELECT COUNT(*), COALESCE(SUM(message_count), 0) FROM user_stats"
        ) as cursor:
            row = await cursor.fetchone()
            total_users = row[0] or 0
            total_messages = row[1] or 0

        # ── Active today ─────────────────────────────────────
        active_today = 0
        if await _has_column(db, "user_stats", "last_active"):
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            async with db.execute(
                "SELECT COUNT(*) FROM user_stats WHERE DATE(last_active) = ?",
                (today,),
            ) as cursor:
                row = await cursor.fetchone()
                active_today = row[0] or 0

        # ── Total chat entries ───────────────────────────────
        async with db.execute("SELECT COUNT(*) FROM chat_history") as cursor:
            row = await cursor.fetchone()
            total_history_entries = row[0] or 0

        # ── Total characters ─────────────────────────────────
        total_chars = 0
        if await _has_column(db, "user_stats", "total_chars_sent"):
            async with db.execute(
                "SELECT COALESCE(SUM(total_chars_sent), 0) FROM user_stats"
            ) as cursor:
                row = await cursor.fetchone()
                total_chars = row[0] or 0

        # ── Top users ────────────────────────────────────────
        async with db.execute(
            "SELECT user_id, message_count FROM user_stats ORDER BY message_count DESC LIMIT 5"
        ) as cursor:
            top_users = await cursor.fetchall()

    return {
        "total_users": total_users,
        "total_messages": total_messages,
        "active_today": active_today,
        "total_history_entries": total_history_entries,
        "total_chars_sent": total_chars,
        "top_users": [{"user_id": r[0], "messages": r[1]} for r in top_users],
    }


async def get_user_stats(user_id: int) -> dict:
    """Get detailed statistics for a specific user."""
    default = {
        "total_messages": 0,
        "first_seen": "N/A",
        "last_active": "N/A",
        "total_chars_sent": 0,
        "reset_count": 0,
    }

    async with aiosqlite.connect(DB_FILE) as db:
        existing = await _get_existing_columns(db, "user_stats")

        # ── Build SELECT dynamically ─────────────────────────
        select_cols = ["message_count"]
        col_keys = ["total_messages"]

        for col, key in [
            ("first_seen", "first_seen"),
            ("last_active", "last_active"),
            ("total_chars_sent", "total_chars_sent"),
            ("reset_count", "reset_count"),
        ]:
            if col in existing:
                select_cols.append(col)
                col_keys.append(key)

        query = f"SELECT {', '.join(select_cols)} FROM user_stats WHERE user_id = ?"

        async with db.execute(query, (user_id,)) as cursor:
            row = await cursor.fetchone()

            if not row:
                return default

            result = dict(default)
            for i, key in enumerate(col_keys):
                value = row[i]
                if value is None or value == '':
                    result[key] = default[key]
                else:
                    result[key] = value

            return result


async def get_db_info() -> dict:
    """Get database file info and summary stats."""
    try:
        size_bytes = os.path.getsize(DB_FILE)
        if size_bytes < 1024:
            db_size = f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            db_size = f"{size_bytes / 1024:.1f} KB"
        else:
            db_size = f"{size_bytes / (1024 * 1024):.2f} MB"
    except OSError:
        db_size = "N/A"

    try:
        async with aiosqlite.connect(DB_FILE) as db:
            async with db.execute("SELECT COUNT(*) FROM user_stats") as c:
                total_users = (await c.fetchone())[0] or 0
            async with db.execute("SELECT COUNT(*) FROM chat_history") as c:
                total_messages = (await c.fetchone())[0] or 0
    except Exception:
        total_users = 0
        total_messages = 0

    return {
        "db_file": DB_FILE,
        "db_size": db_size,
        "total_users": total_users,
        "total_messages": total_messages,
    }


# ╔══════════════════════════════════════════════════════════╗
# ║              🛡️ DATABASE MAINTENANCE                     ║
# ╚══════════════════════════════════════════════════════════╝

async def vacuum_db():
    """Reclaim unused space in the database file."""
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("VACUUM")
    logger.info("🗜️ Database vacuumed successfully")


async def get_table_sizes() -> dict:
    """Get row counts for all tables."""
    tables = {}
    async with aiosqlite.connect(DB_FILE) as db:
        for table in ("chat_history", "user_stats"):
            try:
                async with db.execute(f"SELECT COUNT(*) FROM {table}") as c:
                    tables[table] = (await c.fetchone())[0] or 0
            except Exception:
                tables[table] = -1
    return tables