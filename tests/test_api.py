"""API 端點測試

測試 POST /debates、GET /debates/{session_id}、GET /debates/{session_id}/stream、
GET /settings/defaults 端點。所有 LLM 呼叫使用 mock，不實際呼叫外部 API。
已更新為支援 JWT 認證。
"""

import pytest
import pytest_asyncio
from unittest.mock import patch, AsyncMock

import aiosqlite
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from api import router, debates, _event_queues
from auth import auth_router
from config import get_settings
from database import init_db, get_db
from models import DebatePhase, DebateState


@pytest_asyncio.fixture
async def app(tmp_path, monkeypatch):
    """建立測試用 FastAPI 應用，含認證路由與測試資料庫。"""
    test_db = str(tmp_path / "test.db")
    monkeypatch.setenv("DATABASE_PATH", test_db)
    monkeypatch.setenv("JWT_SECRET", "test-secret-key")
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-key")

    await init_db()

    async def override_get_db():
        db = await aiosqlite.connect(test_db)
        db.row_factory = aiosqlite.Row
        try:
            yield db
        finally:
            await db.close()

    test_app = FastAPI()
    test_app.include_router(router)
    test_app.include_router(auth_router)
    test_app.dependency_overrides[get_db] = override_get_db

    yield test_app


@pytest_asyncio.fixture
async def client(app):
    """建立測試用 HTTP 客戶端。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture(autouse=True)
def clear_state():
    """每個測試前清空全域狀態。"""
    debates.clear()
    _event_queues.clear()
    yield
    debates.clear()
    _event_queues.clear()


async def get_auth_header(client: AsyncClient) -> dict:
    """註冊測試使用者並登入取得 JWT token。"""
    await client.post(
        "/auth/register",
        json={"username": "testuser", "password": "testpass123"},
    )
    resp = await client.post(
        "/auth/login",
        json={"username": "testuser", "password": "testpass123"},
    )
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_create_debate_success(client):
    """POST /debates 成功建立辯論會話（需認證）。"""
    headers = await get_auth_header(client)

    with patch("api._run_debate_task", new_callable=AsyncMock):
        response = await client.post(
            "/debates",
            json={"user_input": "如何提升團隊效率？"},
            headers=headers,
        )

    assert response.status_code == 200
    data = response.json()
    assert "session_id" in data
    assert data["status"] == "initiated"
    assert data["session_id"] in debates


@pytest.mark.asyncio
async def test_create_debate_empty_input(client):
    """POST /debates 空白輸入回傳 422。"""
    headers = await get_auth_header(client)
    response = await client.post(
        "/debates",
        json={"user_input": "   "},
        headers=headers,
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_debate_missing_input(client):
    """POST /debates 缺少 user_input 回傳 422。"""
    headers = await get_auth_header(client)
    response = await client.post("/debates", json={}, headers=headers)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_debate_no_auth(client):
    """POST /debates 無認證回傳 401。"""
    response = await client.post(
        "/debates",
        json={"user_input": "測試"},
    )
    assert response.status_code == 422  # missing Authorization header


@pytest.mark.asyncio
async def test_get_debate_status_success(client):
    """GET /debates/{session_id} 成功查詢辯論狀態（需認證）。"""
    headers = await get_auth_header(client)

    # 建立辯論以取得 session_id 並寫入 DB
    with patch("api._run_debate_task", new_callable=AsyncMock):
        create_resp = await client.post(
            "/debates",
            json={"user_input": "測試想法"},
            headers=headers,
        )
    session_id = create_resp.json()["session_id"]

    response = await client.get(f"/debates/{session_id}", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == session_id
    assert data["current_phase"] == "initiated"
    assert data["user_input"] == "測試想法"


@pytest.mark.asyncio
async def test_get_debate_status_not_found(client):
    """GET /debates/{session_id} 不存在的會話回傳 404。"""
    headers = await get_auth_header(client)
    response = await client.get("/debates/nonexistent-id", headers=headers)
    assert response.status_code == 404
    assert response.json()["detail"] == "會話不存在"


@pytest.mark.asyncio
async def test_stream_debate_not_found(client):
    """GET /debates/{session_id}/stream 不存在的會話回傳 404。"""
    headers = await get_auth_header(client)
    response = await client.get("/debates/nonexistent-id/stream", headers=headers)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_settings_defaults_no_auth(client):
    """GET /settings/defaults 無需認證即可存取。"""
    response = await client.get("/settings/defaults")
    assert response.status_code == 200
    data = response.json()
    assert "prompt_a" in data
    assert "prompt_b" in data
    assert "prompt_c" in data
    assert "prompt_d" in data
    assert "default_rounds" in data
