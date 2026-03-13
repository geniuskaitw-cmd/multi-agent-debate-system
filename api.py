"""API 路由模組

端點：
- POST /debates — 建立辯論（可帶自訂設定）
- GET /debates — 分頁查詢辯論歷史
- GET /debates/{id} — 查詢狀態（含所有中間結果）
- GET /debates/{id}/stream — SSE 即時推送
- DELETE /debates/{id} — 刪除辯論紀錄
- GET /settings/defaults — 取得預設 prompt（無需認證）
"""

import asyncio
import json
import logging
import math
import uuid

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from sse_starlette.sse import EventSourceResponse

from auth import get_current_user
from config import get_settings
from database import (
    get_db,
    insert_debate,
    update_debate,
    get_debate as db_get_debate,
    list_debates as db_list_debates,
    delete_debate as db_delete_debate,
)
from models import (
    DebateConfig, DebateCreateRequest, DebateCreateResponse,
    DebatePhase, DebateState, DebateStatusResponse, PhaseUpdate,
    PaginatedDebateList, DebateListItem, ScoreCard,
)
from graph import run_debate
from prompts import get_agent_a_prompt, get_agent_b_prompt, get_agent_c_prompt, get_agent_d_prompt

logger = logging.getLogger(__name__)
router = APIRouter()

debates: dict[str, DebateState] = {}
_event_queues: dict[str, list[asyncio.Queue]] = {}


def _push_event(session_id: str, event: PhaseUpdate) -> None:
    for q in _event_queues.get(session_id, []):
        q.put_nowait(event)


async def _run_debate_task(session_id: str, db_path: str) -> None:
    """背景執行辯論流程，完成後將最終狀態持久化至 SQLite。"""
    state = debates.get(session_id)
    if not state:
        return

    await run_debate(state, lambda evt: _push_event(session_id, evt))

    # 持久化最終狀態至 SQLite
    try:
        async with aiosqlite.connect(db_path) as db:
            if state.current_phase == DebatePhase.FAILED:
                await update_debate(db, session_id, phase="failed")
            else:
                await update_debate(
                    db,
                    session_id,
                    a_responses=json.dumps(state.a_responses, ensure_ascii=False),
                    b_responses=json.dumps(state.b_responses, ensure_ascii=False),
                    c1=state.c1,
                    scores=state.scores.model_dump_json() if state.scores else None,
                    phase=state.current_phase.value,
                )
    except Exception as e:
        logger.warning("DB persist failed for %s: %s", session_id, e)


@router.post("/debates", response_model=DebateCreateResponse)
async def create_debate(
    request: DebateCreateRequest,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    session_id = str(uuid.uuid4())
    config = request.config or DebateConfig()
    state = DebateState(
        session_id=session_id,
        user_input=request.user_input,
        config=config,
        total_rounds=config.rounds,
    )
    debates[session_id] = state

    # 持久化至 SQLite
    await insert_debate(db, session_id, user["id"], request.user_input, config.model_dump_json())

    settings = get_settings()
    background_tasks.add_task(_run_debate_task, session_id, settings.database_path)
    logger.info("建立辯論: %s (rounds=%d, user=%s)", session_id, config.rounds, user["username"])
    return DebateCreateResponse(session_id=session_id)


@router.get("/debates", response_model=PaginatedDebateList)
async def list_debates_endpoint(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """分頁查詢使用者的辯論歷史列表。"""
    items, total = await db_list_debates(db, user["id"], page, page_size)
    total_pages = math.ceil(total / page_size) if total > 0 else 0
    return PaginatedDebateList(
        items=[DebateListItem(**item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/debates/{session_id}", response_model=DebateStatusResponse)
async def get_debate_status(
    session_id: str,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    # 先查記憶體（活躍辯論）
    state = debates.get(session_id)
    if state:
        return DebateStatusResponse(
            session_id=state.session_id,
            current_phase=state.current_phase,
            current_round=state.current_round,
            total_rounds=state.total_rounds,
            user_input=state.user_input,
            a_responses=state.a_responses,
            b_responses=state.b_responses,
            c1=state.c1,
            scores=state.scores,
            errors=state.errors,
        )

    # 查 SQLite（歷史辯論）
    row = await db_get_debate(db, session_id)
    if not row:
        raise HTTPException(status_code=404, detail="會話不存在")
    if row["user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="無權限存取此辯論")

    a_responses = json.loads(row["a_responses"]) if row["a_responses"] else []
    b_responses = json.loads(row["b_responses"]) if row["b_responses"] else []
    scores = ScoreCard.model_validate_json(row["scores"]) if row["scores"] else None
    config_data = json.loads(row["config"]) if row["config"] else {}
    total_rounds = config_data.get("rounds", 3)

    return DebateStatusResponse(
        session_id=row["session_id"],
        current_phase=row["phase"],
        current_round=0,
        total_rounds=total_rounds,
        user_input=row["user_input"],
        a_responses=a_responses,
        b_responses=b_responses,
        c1=row["c1"],
        scores=scores,
        errors=[],
    )


@router.get("/debates/{session_id}/stream")
async def stream_debate(
    session_id: str,
):
    """SSE 串流端點。不需要 JWT 認證 — session_id 本身即為存取憑證。
    EventSource API 不支援自訂 header，因此移除 get_current_user 依賴。"""
    if session_id not in debates:
        raise HTTPException(status_code=404, detail="會話不存在")

    queue: asyncio.Queue = asyncio.Queue()
    if session_id not in _event_queues:
        _event_queues[session_id] = []
    _event_queues[session_id].append(queue)

    async def gen():
        try:
            while True:
                event = await asyncio.wait_for(queue.get(), timeout=120.0)
                if event is None:
                    break
                yield {"event": event.event_type, "data": event.model_dump_json()}
                if event.event_type in ("debate_complete", "error"):
                    break
        except asyncio.TimeoutError:
            yield {"event": "heartbeat", "data": ""}
        finally:
            if session_id in _event_queues:
                try:
                    _event_queues[session_id].remove(queue)
                except ValueError:
                    pass
                if not _event_queues[session_id]:
                    del _event_queues[session_id]

    return EventSourceResponse(gen())



@router.delete("/debates/{session_id}")
async def delete_debate_endpoint(
    session_id: str,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """刪除辯論紀錄。驗證所有權後刪除 DB 紀錄與記憶體快取。"""
    row = await db_get_debate(db, session_id)
    if not row:
        raise HTTPException(status_code=404, detail="會話不存在")
    if row["user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="無權限存取此辯論")

    await db_delete_debate(db, session_id)
    debates.pop(session_id, None)
    return {"message": "辯論紀錄已刪除"}


@router.get("/settings/defaults")
async def get_default_settings():
    """回傳預設的 system prompts，供前端設定面板使用（無需認證）"""
    return {
        "prompt_a": get_agent_a_prompt(1),
        "prompt_b": get_agent_b_prompt(1),
        "prompt_c": get_agent_c_prompt(),
        "prompt_d": get_agent_d_prompt(),
        "default_rounds": 3,
    }
