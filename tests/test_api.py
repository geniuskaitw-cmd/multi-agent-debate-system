"""API 端點測試

測試 POST /debates、GET /debates/{session_id}、GET /debates/{session_id}/stream 端點。
所有 LLM 呼叫使用 mock，不實際呼叫外部 API。
"""

import pytest
from unittest.mock import patch, AsyncMock
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from api import router, debates, _event_queues
from models import DebatePhase


@pytest.fixture
def app():
    """建立測試用 FastAPI 應用。"""
    test_app = FastAPI()
    test_app.include_router(router)
    return test_app


@pytest.fixture
def client(app):
    """建立測試用 HTTP 客戶端。"""
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture(autouse=True)
def clear_state():
    """每個測試前清空全域狀態。"""
    debates.clear()
    _event_queues.clear()
    yield
    debates.clear()
    _event_queues.clear()


@pytest.mark.asyncio
async def test_create_debate_success(client):
    """POST /debates 成功建立辯論會話。"""
    with patch("api._run_debate", new_callable=AsyncMock):
        response = await client.post(
            "/debates",
            json={"user_input": "如何提升團隊效率？"},
        )

    assert response.status_code == 200
    data = response.json()
    assert "session_id" in data
    assert data["status"] == "initiated"
    assert data["session_id"] in debates


@pytest.mark.asyncio
async def test_create_debate_empty_input(client):
    """POST /debates 空白輸入回傳 422。"""
    response = await client.post(
        "/debates",
        json={"user_input": "   "},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_debate_missing_input(client):
    """POST /debates 缺少 user_input 回傳 422。"""
    response = await client.post("/debates", json={})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_debate_status_success(client):
    """GET /debates/{session_id} 成功查詢辯論狀態。"""
    from models import DebateState

    state = DebateState(
        session_id="test-session-123",
        user_input="測試想法",
    )
    debates["test-session-123"] = state

    response = await client.get("/debates/test-session-123")
    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == "test-session-123"
    assert data["current_phase"] == "initiated"
    assert data["user_input"] == "測試想法"


@pytest.mark.asyncio
async def test_get_debate_status_not_found(client):
    """GET /debates/{session_id} 不存在的會話回傳 404。"""
    response = await client.get("/debates/nonexistent-id")
    assert response.status_code == 404
    assert response.json()["detail"] == "會話不存在"


@pytest.mark.asyncio
async def test_stream_debate_not_found(client):
    """GET /debates/{session_id}/stream 不存在的會話回傳 404。"""
    response = await client.get("/debates/nonexistent-id/stream")
    assert response.status_code == 404
