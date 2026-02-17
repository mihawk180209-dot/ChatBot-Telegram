import aiosqlite
import json
import logging

logger = logging.getLogger(__name__)
DB_FILE = "bot_memory.db"

async def init_db():
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                role TEXT,
                content TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_stats (
                user_id INTEGER PRIMARY KEY,
                message_count INTEGER DEFAULT 0
            )
        """)
        await db.commit()
    logger.info("Database initialized.")

async def add_message(user_id: int, role: str, content: str):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            "INSERT INTO chat_history (user_id, role, content) VALUES (?, ?, ?)",
            (user_id, role, content)
        )
        # Update stats
        if role == "user":
            await db.execute("""
                INSERT INTO user_stats (user_id, message_count) 
                VALUES (?, 1)
                ON CONFLICT(user_id) DO UPDATE SET message_count = message_count + 1
            """, (user_id,))
        await db.commit()

async def get_history(user_id: int, limit: int = 10) -> list:
    """Fetch recent history, trimming to avoid token overflow."""
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute(
            "SELECT role, content FROM chat_history WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit)
        ) as cursor:
            rows = await cursor.fetchall()
            # Reverse to maintain chronological order
            return [{"role": row[0], "content": row[1]} for row in reversed(rows)]

async def clear_history(user_id: int):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("DELETE FROM chat_history WHERE user_id = ?", (user_id,))
        await db.commit()

async def get_global_stats() -> dict:
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("SELECT COUNT(*), SUM(message_count) FROM user_stats") as cursor:
            row = await cursor.fetchone()
            return {"total_users": row[0] or 0, "total_messages": row[1] or 0}