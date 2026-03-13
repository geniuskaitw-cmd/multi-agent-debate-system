"""資料庫存取層

使用 aiosqlite 進行非同步 SQLite 存取，負責資料表建立與連線管理。
"""

import os
from collections.abc import AsyncGenerator

import aiosqlite

from config import get_settings


async def init_db() -> None:
    """建立資料庫檔案與資料表（若不存在）。

    由 main.py lifespan 呼叫。建立資料庫目錄（若不存在），
    接著建立 users 與 debates 資料表及索引。
    """
    settings = get_settings()
    db_path = settings.database_path

    # 建立資料庫目錄（若不存在）
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS debates (
                session_id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                user_input TEXT NOT NULL,
                config TEXT NOT NULL DEFAULT '{}',
                a_responses TEXT NOT NULL DEFAULT '[]',
                b_responses TEXT NOT NULL DEFAULT '[]',
                c1 TEXT,
                scores TEXT,
                phase TEXT NOT NULL DEFAULT 'initiated',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )

        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_debates_user_id ON debates(user_id)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_debates_created_at ON debates(created_at)"
        )

        await db.commit()


async def get_db() -> AsyncGenerator[aiosqlite.Connection, None]:
    """FastAPI 依賴注入用的 async generator，yield 一個 aiosqlite connection。

    Yields:
        aiosqlite.Connection: 已設定 row_factory 為 aiosqlite.Row 的連線
    """
    settings = get_settings()
    db = await aiosqlite.connect(settings.database_path)
    db.row_factory = aiosqlite.Row
    try:
        yield db
    finally:
        await db.close()

async def create_user(db: aiosqlite.Connection, username: str, password_hash: str) -> int:
    """插入新使用者，回傳 user id。username 重複時拋出 IntegrityError。"""
    cursor = await db.execute(
        "INSERT INTO users (username, password_hash) VALUES (?, ?)",
        (username, password_hash),
    )
    await db.commit()
    return cursor.lastrowid


async def get_user_by_username(db: aiosqlite.Connection, username: str) -> dict | None:
    """依 username 查詢使用者，回傳 {id, username, password_hash, created_at} 或 None。"""
    cursor = await db.execute(
        "SELECT id, username, password_hash, created_at FROM users WHERE username = ?",
        (username,),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    return {"id": row[0], "username": row[1], "password_hash": row[2], "created_at": row[3]}


async def insert_debate(
    db: aiosqlite.Connection,
    session_id: str,
    user_id: int,
    user_input: str,
    config_json: str,
) -> None:
    """插入新辯論紀錄，phase='initiated'，a_responses/b_responses 為空 JSON 陣列。"""
    await db.execute(
        """
        INSERT INTO debates (session_id, user_id, user_input, config, a_responses, b_responses, phase, created_at, updated_at)
        VALUES (?, ?, ?, ?, '[]', '[]', 'initiated', datetime('now'), datetime('now'))
        """,
        (session_id, user_id, user_input, config_json),
    )
    await db.commit()


async def update_debate(db: aiosqlite.Connection, session_id: str, **kwargs) -> None:
    """更新辯論紀錄的任意欄位（a_responses, b_responses, c1, scores, phase）。

    自動設定 updated_at 為當前時間。
    """
    if not kwargs:
        return
    allowed = {"a_responses", "b_responses", "c1", "scores", "phase"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    fields["updated_at"] = "datetime('now')"
    set_parts = []
    values = []
    for key, val in fields.items():
        if key == "updated_at":
            set_parts.append("updated_at = datetime('now')")
        else:
            set_parts.append(f"{key} = ?")
            values.append(val)
    values.append(session_id)
    await db.execute(
        f"UPDATE debates SET {', '.join(set_parts)} WHERE session_id = ?",
        values,
    )
    await db.commit()


async def get_debate(db: aiosqlite.Connection, session_id: str) -> dict | None:
    """依 session_id 查詢單筆辯論，回傳完整 row dict 或 None。"""
    cursor = await db.execute("SELECT * FROM debates WHERE session_id = ?", (session_id,))
    row = await cursor.fetchone()
    if row is None:
        return None
    return dict(row)


async def list_debates(
    db: aiosqlite.Connection, user_id: int, page: int, page_size: int
) -> tuple[list[dict], int]:
    """分頁查詢使用者的辯論列表，回傳 (items, total_count)。

    items 包含 session_id, user_input (前50字), phase, created_at, updated_at。
    依 created_at DESC 排序。
    """
    cursor = await db.execute(
        "SELECT COUNT(*) FROM debates WHERE user_id = ?", (user_id,)
    )
    row = await cursor.fetchone()
    total = row[0]

    offset = (page - 1) * page_size
    cursor = await db.execute(
        """
        SELECT session_id, SUBSTR(user_input, 1, 50) AS user_input, phase, created_at, updated_at
        FROM debates
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
        """,
        (user_id, page_size, offset),
    )
    rows = await cursor.fetchall()
    items = [dict(r) for r in rows]
    return items, total


async def delete_debate(db: aiosqlite.Connection, session_id: str) -> None:
    """刪除指定辯論紀錄。"""
    await db.execute("DELETE FROM debates WHERE session_id = ?", (session_id,))
    await db.commit()
