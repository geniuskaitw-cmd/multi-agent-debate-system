"""API 路由模組

端點：
- POST /debates — 建立辯論（可帶自訂設定）
- GET /debates/{id} — 查詢狀態（含所有中間結果）
- GET /debates/{id}/stream — SSE 即時推送
- GET /settings/defaults — 取得預設 prompt
"""

import asyncio
import logging
import uuid

from fastapi import APIRouter, HTTPException, BackgroundTasks
from sse_starlette.sse import EventSourceResponse

from models import (
    DebateConfig, DebateCreateRequest, DebateCreateResponse,
    DebatePhase, DebateState, DebateStatusResponse, PhaseUpdate,
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


async def _run_debate_task(session_id: str) -> None:
    state = debates.get(session_id)
    if not state:
        return
    await run_debate(state, lambda evt: _push_event(session_id, evt))


@router.post("/debates", response_model=DebateCreateResponse)
async def create_debate(request: DebateCreateRequest, background_tasks: BackgroundTasks):
    session_id = str(uuid.uuid4())
    config = request.config or DebateConfig()
    state = DebateState(
        session_id=session_id,
        user_input=request.user_input,
        config=config,
        total_rounds=config.rounds,
    )
    debates[session_id] = state
    background_tasks.add_task(_run_debate_task, session_id)
    logger.info("建立辯論: %s (rounds=%d)", session_id, config.rounds)
    return DebateCreateResponse(session_id=session_id)


@router.get("/debates/{session_id}", response_model=DebateStatusResponse)
async def get_debate_status(session_id: str):
    state = debates.get(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="會話不存在")
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


@router.get("/debates/{session_id}/stream")
async def stream_debate(session_id: str):
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


@router.get("/settings/defaults")
async def get_default_settings():
    """回傳預設的 system prompts，供前端設定面板使用"""
    return {
        "prompt_a": get_agent_a_prompt(1),
        "prompt_b": get_agent_b_prompt(1),
        "prompt_c": get_agent_c_prompt(),
        "prompt_d": get_agent_d_prompt(),
        "default_rounds": 3,
    }
