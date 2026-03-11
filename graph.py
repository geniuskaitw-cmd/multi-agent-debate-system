"""LangGraph 狀態機建構模組

使用 LangGraph 的 StateGraph 建構辯論流程圖。
Phase 1-3 中 Agent A 與 Agent B 平行執行，
Phase 4 由 Agent C 單獨執行，Phase 5 由 Agent D 單獨執行。
"""

import asyncio
import logging

from langgraph.graph import StateGraph, END

from models import DebatePhase, DebateState
from agents import node_a, node_b, node_c, node_d

logger = logging.getLogger(__name__)


async def _parallel_ab(state: DebateState, phase: DebatePhase) -> dict:
    """平行執行 Agent A 與 Agent B，合併結果。

    先將 state 的 current_phase 設為指定階段，再呼叫 agent。
    """
    state_with_phase = state.model_copy(update={"current_phase": phase})
    result_a, result_b = await asyncio.gather(
        node_a(state_with_phase),
        node_b(state_with_phase),
    )
    merged = {}
    merged.update(result_a)
    merged.update(result_b)
    return merged


async def phase_1_node(state: DebateState) -> dict:
    """Phase 1：初步見解 — A1, B1 平行產出。"""
    logger.info("Phase 1: 初步見解開始")
    result = await _parallel_ab(state, DebatePhase.PHASE_1)
    result["current_phase"] = DebatePhase.PHASE_1
    return result


async def phase_2_node(state: DebateState) -> dict:
    """Phase 2：交叉詰問 — A2, B2 平行產出。"""
    logger.info("Phase 2: 交叉詰問開始")
    result = await _parallel_ab(state, DebatePhase.PHASE_2)
    result["current_phase"] = DebatePhase.PHASE_2
    return result


async def phase_3_node(state: DebateState) -> dict:
    """Phase 3：最終修正 — A3, B3 平行產出。"""
    logger.info("Phase 3: 最終修正開始")
    result = await _parallel_ab(state, DebatePhase.PHASE_3)
    result["current_phase"] = DebatePhase.PHASE_3
    return result


async def phase_4_node(state: DebateState) -> dict:
    """Phase 4：方案收斂 — Agent C 產出 C1。"""
    logger.info("Phase 4: 方案收斂開始")
    result = await node_c(state)
    result["current_phase"] = DebatePhase.PHASE_4
    return result


async def phase_5_node(state: DebateState) -> dict:
    """Phase 5：獨立評分 — Agent D 產出評分表。"""
    logger.info("Phase 5: 獨立評分開始")
    result = await node_d(state)
    if "errors" not in result or not result.get("errors"):
        result["current_phase"] = DebatePhase.PHASE_5
    else:
        result["current_phase"] = DebatePhase.FAILED
    return result


async def completion_node(state: DebateState) -> dict:
    """標記辯論完成。"""
    logger.info("辯論流程完成")
    return {"current_phase": DebatePhase.COMPLETED}


def phase_router(state: DebateState) -> str:
    """根據當前狀態決定下一個執行節點。

    路由邏輯：
    - INITIATED → phase_1
    - PHASE_1 → phase_2
    - PHASE_2 → phase_3
    - PHASE_3 → phase_4 (node_c)
    - PHASE_4 → phase_5 (node_d)
    - PHASE_5 → completion
    - FAILED → END
    """
    phase = state.current_phase

    if phase == DebatePhase.INITIATED:
        return "phase_1"
    elif phase == DebatePhase.PHASE_1:
        return "phase_2"
    elif phase == DebatePhase.PHASE_2:
        return "phase_3"
    elif phase == DebatePhase.PHASE_3:
        return "phase_4"
    elif phase == DebatePhase.PHASE_4:
        return "phase_5"
    elif phase == DebatePhase.PHASE_5:
        return "completion"
    elif phase == DebatePhase.FAILED:
        return END
    else:
        return END


def build_debate_graph():
    """建構並編譯辯論流程圖。

    Returns:
        編譯後的可執行工作流實例
    """
    graph = StateGraph(DebateState)

    # 加入節點
    graph.add_node("phase_1", phase_1_node)
    graph.add_node("phase_2", phase_2_node)
    graph.add_node("phase_3", phase_3_node)
    graph.add_node("phase_4", phase_4_node)
    graph.add_node("phase_5", phase_5_node)
    graph.add_node("completion", completion_node)

    # 設定入口點與路由
    graph.set_entry_point("phase_1")

    # Phase 1 完成後路由
    graph.add_conditional_edges("phase_1", phase_router)
    graph.add_conditional_edges("phase_2", phase_router)
    graph.add_conditional_edges("phase_3", phase_router)
    graph.add_conditional_edges("phase_4", phase_router)
    graph.add_conditional_edges("phase_5", phase_router)
    graph.add_edge("completion", END)

    return graph.compile()
