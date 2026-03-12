"""智能體節點模組 — 支援動態輪數辯論

每個 agent 函數接收 DebateState 和輪次資訊，回傳回應文字。
"""

import asyncio
import logging
import random

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage
from pydantic import ValidationError

from config import get_settings
from models import DebateState, ScoreCard
from prompts import (
    get_agent_a_prompt,
    get_agent_b_prompt,
    get_agent_c_prompt,
    get_agent_d_prompt,
)

logger = logging.getLogger(__name__)


class LLMCallError(Exception):
    pass


async def call_llm_with_retry(
    model_name: str, system_prompt: str, user_message: str,
    max_retries: int = 3, timeout: int = 120, json_mode: bool = False,
) -> str:
    settings = get_settings()
    llm = ChatGoogleGenerativeAI(model=model_name, google_api_key=settings.google_api_key)
    messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_message)]
    last_error = None

    for attempt in range(max_retries + 1):
        try:
            response = await asyncio.wait_for(llm.ainvoke(messages), timeout=timeout)
            raw = response.content
            content = "".join(
                b.get("text", "") if isinstance(b, dict) else str(b) for b in raw
            ) if isinstance(raw, list) else str(raw)
            if json_mode:
                ScoreCard.model_validate_json(content)
            return content
        except Exception as e:
            last_error = e
            logger.warning("LLM fail (attempt %d/%d, %s): %s", attempt+1, max_retries+1, model_name, e)
            if attempt == max_retries:
                break
            wait = (2 ** attempt) + random.uniform(0, 1)
            await asyncio.sleep(wait)
            if json_mode and isinstance(e, ValidationError):
                messages = [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=f"{user_message}\n\n【注意】JSON 格式錯誤，請修正：\n{e}"),
                ]
    raise LLMCallError(f"LLM 重試耗盡 ({model_name}): {last_error}")


async def run_agent_a(state: DebateState, round_num: int) -> str:
    """Agent A 在第 round_num 輪的回應 (1-based)"""
    settings = get_settings()
    custom = state.config.prompt_a
    total = state.total_rounds

    if round_num == 1:
        sys_prompt = custom if custom else get_agent_a_prompt(1)
        user_msg = state.user_input
    else:
        phase = min(round_num, 3)  # prompt 最多到 phase 3
        sys_prompt = custom if custom else get_agent_a_prompt(phase)
        # 組合歷史上下文
        parts = [f"原始想法：{state.user_input}"]
        for i, (a, b) in enumerate(zip(state.a_responses, state.b_responses)):
            parts.append(f"\n第 {i+1} 輪 — 我的回應：\n{a}")
            parts.append(f"\n第 {i+1} 輪 — 對方回應：\n{b}")
        if round_num == total:
            parts.append("\n這是最後一輪，請產出你的最終方案。")
        user_msg = "\n".join(parts)

    return await call_llm_with_retry(
        model_name=settings.agent_a_model, system_prompt=sys_prompt,
        user_message=user_msg, max_retries=settings.llm_max_retries, timeout=settings.llm_timeout,
    )


async def run_agent_b(state: DebateState, round_num: int) -> str:
    """Agent B 在第 round_num 輪的回應 (1-based)"""
    settings = get_settings()
    custom = state.config.prompt_b
    total = state.total_rounds

    if round_num == 1:
        sys_prompt = custom if custom else get_agent_b_prompt(1)
        user_msg = state.user_input
    else:
        phase = min(round_num, 3)
        sys_prompt = custom if custom else get_agent_b_prompt(phase)
        parts = [f"原始想法：{state.user_input}"]
        for i, (a, b) in enumerate(zip(state.a_responses, state.b_responses)):
            parts.append(f"\n第 {i+1} 輪 — 對方回應：\n{a}")
            parts.append(f"\n第 {i+1} 輪 — 我的回應：\n{b}")
        if round_num == total:
            parts.append("\n這是最後一輪，請產出你的最終方案。")
        user_msg = "\n".join(parts)

    return await call_llm_with_retry(
        model_name=settings.agent_b_model, system_prompt=sys_prompt,
        user_message=user_msg, max_retries=settings.llm_max_retries, timeout=settings.llm_timeout,
    )


async def run_agent_c(state: DebateState) -> str:
    settings = get_settings()
    custom = state.config.prompt_c
    sys_prompt = custom if custom else get_agent_c_prompt()
    a_final = state.a_responses[-1] if state.a_responses else ""
    b_final = state.b_responses[-1] if state.b_responses else ""
    user_msg = f"原始想法：{state.user_input}\n\n創新方案最終版：\n{a_final}\n\n保守方案最終版：\n{b_final}"
    return await call_llm_with_retry(
        model_name=settings.agent_c_model, system_prompt=sys_prompt,
        user_message=user_msg, max_retries=settings.llm_max_retries, timeout=settings.llm_timeout,
    )


async def run_agent_d(state: DebateState) -> ScoreCard:
    settings = get_settings()
    custom = state.config.prompt_d
    sys_prompt = custom if custom else get_agent_d_prompt()
    a_final = state.a_responses[-1] if state.a_responses else ""
    b_final = state.b_responses[-1] if state.b_responses else ""
    user_msg = (
        f"原始問題：{state.user_input}\n\n"
        f"方案 A：\n{a_final}\n\n"
        f"方案 B：\n{b_final}\n\n"
        f"方案 C：\n{state.c1}"
    )
    response = await call_llm_with_retry(
        model_name=settings.agent_d_model, system_prompt=sys_prompt,
        user_message=user_msg, max_retries=settings.llm_max_retries,
        timeout=settings.llm_timeout, json_mode=True,
    )
    return ScoreCard.model_validate_json(response)
