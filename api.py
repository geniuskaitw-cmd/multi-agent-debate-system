"""API 路由模組

提供前端所需的所有 FastAPI 端點：
- POST /debates — 建立新辯論會話
- GET /debates/{session_id} — 查詢辯論狀態
- GET /debates/{session_id}/stream — SSE 即時推送辯論進度
"""

import asyncio
import logging
import uuid

from fastapi import APIRouter, HTTPException, BackgroundTasks
from sse_starlette.sse import EventSourceResponse

from models import (
    DebateCreateRequest,
    DebateCreateResponse,
    DebatePhase,
    DebateState,
    DebateStatusResponse,
    PhaseUpdate,
)
from graph import build_debate_graph

logger = logging.getLogger(__name__)

router = APIRouter()

# 記憶體字典儲存辯論會話狀態
debates: dict[str, DebateState] = {}

# 每個 session 的 SSE 事件佇列
_event_queues: dict[str, list[asyncio.Queue]] = {}


def _push_event(session_id: str, event: PhaseUpdate) -> None:
    """將事件推送至該 session 的所有 SSE 佇列。"""
    for q in _event_queues.get(session_id, []):
        q.put_nowait(event)


async def _run_debate(session_id: str) -> None:
    """背景任務：執行辯論流程圖並即時更新狀態與推送 SSE 事件。"""
    state = debates.get(session_id)
    if state is None:
        return

    graph = build_debate_graph()

    # 定義階段順序，用於偵測階段變化
    phase_order = [
        DebatePhase.INITIATED,
        DebatePhase.PHASE_1,
        DebatePhase.PHASE_2,
        DebatePhase.PHASE_3,
        DebatePhase.PHASE_4,
        DebatePhase.PHASE_5,
        DebatePhase.COMPLETED,
    ]

    previous_phase = state.current_phase

    try:
        # 使用 astream 逐步取得狀態更新
        async for chunk in graph.astream(
            state.model_dump(),
            config={"recursion_limit": 50},
        ):
            # LangGraph astream 回傳 {node_name: state_update} 格式
            for _node_name, update in chunk.items():
                if isinstance(update, dict):
                    # 更新記憶體中的辯論狀態
                    for key, value in update.items():
                        if hasattr(state, key):
                            setattr(state, key, value)

            current_phase = state.current_phase

            # 偵測階段變化並推送事件
            if current_phase != previous_phase:
                # 推送前一階段完成事件
                if previous_phase in phase_order and previous_phase != DebatePhase.INITIATED:
                    _push_event(session_id, PhaseUpdate(
                        event_type="phase_complete",
                        phase=previous_phase,
                    ))

                # 推送新階段開始事件
                if current_phase == DebatePhase.COMPLETED:
                    _push_event(session_id, PhaseUpdate(
                        event_type="debate_complete",
                        phase=DebatePhase.COMPLETED,
                    ))
                elif current_phase == DebatePhase.FAILED:
                    _push_event(session_id, PhaseUpdate(
                        event_type="error",
                        phase=DebatePhase.FAILED,
                        error_message=state.errors[-1] if state.errors else "未知錯誤",
                    ))
                else:
                    _push_event(session_id, PhaseUpdate(
                        event_type="phase_start",
                        phase=current_phase,
                    ))

                previous_phase = current_phase

    except Exception as e:
        error_msg = f"辯論流程執行失敗: {e}"
        logger.error(error_msg)
        state.current_phase = DebatePhase.FAILED
        state.errors.append(error_msg)
        _push_event(session_id, PhaseUpdate(
            event_type="error",
            phase=DebatePhase.FAILED,
            error_message=error_msg,
        ))


@router.post("/debates", response_model=DebateCreateResponse)
async def create_debate(
    request: DebateCreateRequest,
    background_tasks: BackgroundTasks,
) -> DebateCreateResponse:
    """建立新辯論會話。

    驗證輸入非空白，建立 DebateState 並產生唯一 session_id，
    啟動背景辯論流程，回傳 session_id。
    """
    session_id = str(uuid.uuid4())

    state = DebateState(
        session_id=session_id,
        user_input=request.user_input,
    )

    debates[session_id] = state

    # 啟動背景辯論任務
    background_tasks.add_task(_run_debate, session_id)

    logger.info("建立辯論會話: %s", session_id)

    return DebateCreateResponse(
        session_id=session_id,
        status="initiated",
    )


@router.get("/debates/{session_id}", response_model=DebateStatusResponse)
async def get_debate_status(session_id: str) -> DebateStatusResponse:
    """查詢辯論會話狀態。

    回傳當前階段、所有已產出方案、評分表。
    會話不存在時回傳 404。
    """
    state = debates.get(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="會話不存在")

    return DebateStatusResponse(
        session_id=state.session_id,
        current_phase=state.current_phase,
        user_input=state.user_input,
        a1=state.a1,
        b1=state.b1,
        a2=state.a2,
        b2=state.b2,
        a3=state.a3,
        b3=state.b3,
        c1=state.c1,
        scores=state.scores,
        errors=state.errors,
    )


@router.get("/debates/{session_id}/stream")
async def stream_debate(session_id: str) -> EventSourceResponse:
    """SSE 端點，即時推送辯論進度。

    事件類型：
    - phase_start: 階段開始
    - phase_complete: 階段完成
    - debate_complete: 辯論完成
    - error: 錯誤發生
    """
    if session_id not in debates:
        raise HTTPException(status_code=404, detail="會話不存在")

    queue: asyncio.Queue[PhaseUpdate | None] = asyncio.Queue()

    # 註冊此連線的佇列
    if session_id not in _event_queues:
        _event_queues[session_id] = []
    _event_queues[session_id].append(queue)

    async def event_generator():
        try:
            while True:
                event = await asyncio.wait_for(queue.get(), timeout=60.0)
                if event is None:
                    break

                yield {
                    "event": event.event_type,
                    "data": event.model_dump_json(),
                }

                # 辯論完成或錯誤時結束串流
                if event.event_type in ("debate_complete", "error"):
                    break
        except asyncio.TimeoutError:
            # 發送心跳保持連線，繼續等待
            yield {"event": "heartbeat", "data": ""}
        finally:
            # 清理佇列
            if session_id in _event_queues:
                try:
                    _event_queues[session_id].remove(queue)
                except ValueError:
                    pass
                if not _event_queues[session_id]:
                    del _event_queues[session_id]

    return EventSourceResponse(event_generator())
