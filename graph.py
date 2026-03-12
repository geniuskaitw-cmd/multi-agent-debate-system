"""辯論流程引擎 — 支援動態輪數

不再使用 LangGraph 固定圖，改用 async 迴圈支援 N 輪辯論。
每輪 A/B 平行執行，最後 C → D 順序執行。
"""

import asyncio
import logging
from typing import Callable

from models import DebatePhase, DebateState, PhaseUpdate
from agents import run_agent_a, run_agent_b, run_agent_c, run_agent_d, LLMCallError

logger = logging.getLogger(__name__)


async def run_debate(state: DebateState, push_event: Callable[[PhaseUpdate], None]) -> None:
    """執行完整辯論流程。

    Args:
        state: 辯論狀態（會被原地修改）
        push_event: SSE 事件推送回呼
    """
    total = state.total_rounds

    try:
        # === 辯論輪次 ===
        for round_num in range(1, total + 1):
            state.current_phase = DebatePhase.DEBATING
            state.current_round = round_num

            push_event(PhaseUpdate(
                event_type="round_start", phase=DebatePhase.DEBATING,
                current_round=round_num, total_rounds=total,
            ))

            logger.info("Round %d/%d 開始", round_num, total)

            # A/B 平行
            a_resp, b_resp = await asyncio.gather(
                run_agent_a(state, round_num),
                run_agent_b(state, round_num),
            )
            state.a_responses.append(a_resp)
            state.b_responses.append(b_resp)

            push_event(PhaseUpdate(
                event_type="round_complete", phase=DebatePhase.DEBATING,
                current_round=round_num, total_rounds=total,
            ))

        # === 方案收斂 ===
        state.current_phase = DebatePhase.SYNTHESIS
        push_event(PhaseUpdate(event_type="synthesis_start", phase=DebatePhase.SYNTHESIS,
                               current_round=total, total_rounds=total))

        state.c1 = await run_agent_c(state)

        # === 獨立評分 ===
        state.current_phase = DebatePhase.SCORING
        push_event(PhaseUpdate(event_type="scoring_start", phase=DebatePhase.SCORING,
                               current_round=total, total_rounds=total))

        state.scores = await run_agent_d(state)

        # === 完成 ===
        state.current_phase = DebatePhase.COMPLETED
        push_event(PhaseUpdate(event_type="debate_complete", phase=DebatePhase.COMPLETED,
                               current_round=total, total_rounds=total))

    except (LLMCallError, Exception) as e:
        error_msg = f"辯論流程失敗: {e}"
        logger.error(error_msg)
        state.current_phase = DebatePhase.FAILED
        state.errors.append(error_msg)
        push_event(PhaseUpdate(
            event_type="error", phase=DebatePhase.FAILED,
            error_message=error_msg,
        ))
