"""database.py 使用者 CRUD 函式測試"""

import aiosqlite
import pytest
import pytest_asyncio

from database import (
    init_db,
    create_user,
    get_user_by_username,
    insert_debate,
    update_debate,
    get_debate,
    list_debates,
    delete_debate,
)


@pytest_asyncio.fixture
async def db(tmp_path, monkeypatch):
    """建立暫時資料庫並初始化 schema。"""
    db_path = str(tmp_path / "test.db")
    monkeypatch.setenv("DATABASE_PATH", db_path)
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-key")

    await init_db()

    conn = await aiosqlite.connect(db_path)
    conn.row_factory = aiosqlite.Row
    try:
        yield conn
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_create_user_returns_id(db):
    """create_user 回傳正整數 user id。"""
    uid = await create_user(db, "alice", "hashed_pw")
    assert isinstance(uid, int)
    assert uid > 0


@pytest.mark.asyncio
async def test_create_user_duplicate_raises(db):
    """create_user 重複 username 拋出 IntegrityError。"""
    await create_user(db, "bob", "hash1")
    with pytest.raises(Exception) as exc_info:
        await create_user(db, "bob", "hash2")
    assert "UNIQUE constraint failed" in str(exc_info.value)


@pytest.mark.asyncio
async def test_get_user_by_username_found(db):
    """get_user_by_username 找到使用者時回傳正確 dict。"""
    await create_user(db, "carol", "hashed_carol")
    user = await get_user_by_username(db, "carol")

    assert user is not None
    assert user["username"] == "carol"
    assert user["password_hash"] == "hashed_carol"
    assert "id" in user
    assert "created_at" in user


@pytest.mark.asyncio
async def test_get_user_by_username_not_found(db):
    """get_user_by_username 找不到使用者時回傳 None。"""
    result = await get_user_by_username(db, "nobody")
    assert result is None


# --- Debate CRUD tests ---

@pytest_asyncio.fixture
async def user_id(db):
    """建立測試使用者並回傳 user id。"""
    return await create_user(db, "testuser", "hashed_pw")


@pytest.mark.asyncio
async def test_insert_and_get_debate(db, user_id):
    """insert_debate 後 get_debate 回傳正確資料。"""
    await insert_debate(db, "sess-1", user_id, "test input", '{"rounds":3}')
    row = await get_debate(db, "sess-1")

    assert row is not None
    assert row["session_id"] == "sess-1"
    assert row["user_id"] == user_id
    assert row["user_input"] == "test input"
    assert row["config"] == '{"rounds":3}'
    assert row["a_responses"] == "[]"
    assert row["b_responses"] == "[]"
    assert row["phase"] == "initiated"
    assert row["created_at"] is not None
    assert row["updated_at"] is not None


@pytest.mark.asyncio
async def test_get_debate_not_found(db):
    """get_debate 找不到時回傳 None。"""
    assert await get_debate(db, "nonexistent") is None


@pytest.mark.asyncio
async def test_update_debate_fields(db, user_id):
    """update_debate 更新指定欄位。"""
    await insert_debate(db, "sess-2", user_id, "input", "{}")
    await update_debate(db, "sess-2", phase="round_1", a_responses='["resp1"]')

    row = await get_debate(db, "sess-2")
    assert row["phase"] == "round_1"
    assert row["a_responses"] == '["resp1"]'


@pytest.mark.asyncio
async def test_update_debate_no_kwargs(db, user_id):
    """update_debate 無 kwargs 時不報錯。"""
    await insert_debate(db, "sess-3", user_id, "input", "{}")
    await update_debate(db, "sess-3")  # should be a no-op


@pytest.mark.asyncio
async def test_list_debates_pagination(db, user_id):
    """list_debates 分頁與排序正確。"""
    for i in range(5):
        await insert_debate(db, f"sess-{i}", user_id, f"input {i}", "{}")

    items, total = await list_debates(db, user_id, page=1, page_size=2)
    assert total == 5
    assert len(items) == 2

    items2, _ = await list_debates(db, user_id, page=3, page_size=2)
    assert len(items2) == 1


@pytest.mark.asyncio
async def test_list_debates_truncates_user_input(db, user_id):
    """list_debates 將 user_input 截斷至 50 字元。"""
    long_input = "A" * 100
    await insert_debate(db, "sess-long", user_id, long_input, "{}")

    items, _ = await list_debates(db, user_id, page=1, page_size=10)
    assert len(items[0]["user_input"]) == 50


@pytest.mark.asyncio
async def test_list_debates_empty(db, user_id):
    """list_debates 無資料時回傳空列表。"""
    items, total = await list_debates(db, user_id, page=1, page_size=10)
    assert items == []
    assert total == 0


@pytest.mark.asyncio
async def test_delete_debate(db, user_id):
    """delete_debate 刪除後 get_debate 回傳 None。"""
    await insert_debate(db, "sess-del", user_id, "to delete", "{}")
    await delete_debate(db, "sess-del")
    assert await get_debate(db, "sess-del") is None
