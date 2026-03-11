"""智能體節點模組

實作四個智能體的節點函數與 LLM 呼叫重試邏輯。
每個節點函數接收當前 DebateState 並回傳更新後的部分 State。
"""

import asyncio
import logging
import random

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage
from pydantic import ValidationError

from config import get_settings
from models import DebatePhase, DebateState, ScoreCard
from prompts import (
    get_agent_a_prompt,
    get_agent_b_prompt,
    get_agent_c_prompt,
    get_agent_d_prompt,
)

logger = logging.getLogger(__name__)


class LLMCallError(Exception):
    """LLM API 呼叫在重試耗盡後仍失敗時拋出的自訂例外。"""
    pass


async def call_llm_with_retry(
    model_name: str,
    system_prompt: str,
    user_message: str,
    max_retries: int = 3,
    timeout: int = 120,
    json_mode: bool = False,
) -> str:
    """呼叫 LLM API，含指數退避重試邏輯。

    Args:
        model_name: 模型名稱
        system_prompt: 系統提示詞
        user_message: 使用者訊息
        max_retries: 最大重試次數
        timeout: 逾時秒數
        json_mode: 是否啟用 JSON 輸出模式（啟用時會以 ScoreCard 驗證輸出）

    Returns:
        LLM 回應文字

    Raises:
        LLMCallError: 重試耗盡後仍失敗
    """
    settings = get_settings()

    llm = ChatGoogleGenerativeAI(
        model=model_name,
        google_api_key=settings.google_api_key,
    )

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_message),
    ]

    last_error: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            response = await asyncio.wait_for(
                llm.ainvoke(messages),
                timeout=timeout,
            )
            raw_content = response.content
            # Gemini 可能回傳 list[dict] 格式，需提取文字
            if isinstance(raw_content, list):
                content = "".join(
                    block.get("text", "") if isinstance(block, dict) else str(block)
                    for block in raw_content
                )
            else:
                content = str(raw_content)

            if json_mode:
                # 驗證 JSON 輸出是否符合 ScoreCard 結構
                ScoreCard.model_validate_json(content)

            return content

        except (asyncio.TimeoutError, ValidationError, Exception) as e:
            last_error = e
            logger.warning(
                "LLM 呼叫失敗 (attempt %d/%d, model=%s): %s",
                attempt + 1,
                max_retries + 1,
                model_name,
                str(e),
            )

            if attempt == max_retries:
                break

            # 指數退避 + 隨機抖動
            wait_time = (2 ** attempt) + random.uniform(0, 1)
            logger.info("等待 %.2f 秒後重試...", wait_time)
            await asyncio.sleep(wait_time)

            # JSON 驗證失敗時，將錯誤訊息附加至下一次呼叫的 prompt
            if json_mode and isinstance(e, ValidationError):
                error_detail = str(e)
                messages = [
                    SystemMessage(content=system_prompt),
                    HumanMessage(
                        content=(
                            f"{user_message}\n\n"
                            f"【注意】你上一次的輸出不符合 JSON Schema 要求，"
                            f"請修正以下錯誤並重新輸出：\n{error_detail}"
                        )
                    ),
                ]

    raise LLMCallError(
        f"LLM 呼叫在重試 {max_retries} 次後仍失敗 (model={model_name}): {last_error}"
    )


async def node_a(state: DebateState) -> dict:
    """Agent A 節點：根據當前階段產出 A1/A2/A3。

    根據 state.current_phase 決定行為：
    - PHASE_1: 接收 user_input，產出 A1
    - PHASE_2: 接收 B1，產出 A2
    - PHASE_3: 接收 B2，產出 A3
    """
    settings = get_settings()

    if state.current_phase == DebatePhase.PHASE_1:
        system_prompt = get_agent_a_prompt(1)
        user_message = state.user_input
        response = await call_llm_with_retry(
            model_name=settings.agent_a_model,
            system_prompt=system_prompt,
            user_message=user_message,
            max_retries=settings.llm_max_retries,
            timeout=settings.llm_timeout,
        )
        return {"a1": response}

    elif state.current_phase == DebatePhase.PHASE_2:
        system_prompt = get_agent_a_prompt(2)
        user_message = (
            f"原始想法：{state.user_input}\n\n"
            f"我的初步見解（A1）：{state.a1}\n\n"
            f"風險控制者的初步見解（B1）：{state.b1}"
        )
        response = await call_llm_with_retry(
            model_name=settings.agent_a_model,
            system_prompt=system_prompt,
            user_message=user_message,
            max_retries=settings.llm_max_retries,
            timeout=settings.llm_timeout,
        )
        return {"a2": response}

    elif state.current_phase == DebatePhase.PHASE_3:
        system_prompt = get_agent_a_prompt(3)
        user_message = (
            f"原始想法：{state.user_input}\n\n"
            f"我的初步見解（A1）：{state.a1}\n\n"
            f"我的交叉回應（A2）：{state.a2}\n\n"
            f"風險控制者的交叉回應（B2）：{state.b2}"
        )
        response = await call_llm_with_retry(
            model_name=settings.agent_a_model,
            system_prompt=system_prompt,
            user_message=user_message,
            max_retries=settings.llm_max_retries,
            timeout=settings.llm_timeout,
        )
        return {"a3": response}

    else:
        raise ValueError(f"Agent A 不應在 {state.current_phase} 階段被呼叫")


async def node_b(state: DebateState) -> dict:
    """Agent B 節點：根據當前階段產出 B1/B2/B3。

    根據 state.current_phase 決定行為：
    - PHASE_1: 接收 user_input，產出 B1
    - PHASE_2: 接收 A1，產出 B2
    - PHASE_3: 接收 A2，產出 B3
    """
    settings = get_settings()

    if state.current_phase == DebatePhase.PHASE_1:
        system_prompt = get_agent_b_prompt(1)
        user_message = state.user_input
        response = await call_llm_with_retry(
            model_name=settings.agent_b_model,
            system_prompt=system_prompt,
            user_message=user_message,
            max_retries=settings.llm_max_retries,
            timeout=settings.llm_timeout,
        )
        return {"b1": response}

    elif state.current_phase == DebatePhase.PHASE_2:
        system_prompt = get_agent_b_prompt(2)
        user_message = (
            f"原始想法：{state.user_input}\n\n"
            f"我的初步見解（B1）：{state.b1}\n\n"
            f"創新驅動者的初步見解（A1）：{state.a1}"
        )
        response = await call_llm_with_retry(
            model_name=settings.agent_b_model,
            system_prompt=system_prompt,
            user_message=user_message,
            max_retries=settings.llm_max_retries,
            timeout=settings.llm_timeout,
        )
        return {"b2": response}

    elif state.current_phase == DebatePhase.PHASE_3:
        system_prompt = get_agent_b_prompt(3)
        user_message = (
            f"原始想法：{state.user_input}\n\n"
            f"我的初步見解（B1）：{state.b1}\n\n"
            f"我的交叉回應（B2）：{state.b2}\n\n"
            f"創新驅動者的交叉回應（A2）：{state.a2}"
        )
        response = await call_llm_with_retry(
            model_name=settings.agent_b_model,
            system_prompt=system_prompt,
            user_message=user_message,
            max_retries=settings.llm_max_retries,
            timeout=settings.llm_timeout,
        )
        return {"b3": response}

    else:
        raise ValueError(f"Agent B 不應在 {state.current_phase} 階段被呼叫")


async def node_c(state: DebateState) -> dict:
    """Agent C 節點：接收 A3 與 B3，產出 C1。

    Agent C 為總結決策者，融合雙方最終方案的優勢，
    產出一份平衡的折衷方案。
    """
    settings = get_settings()
    system_prompt = get_agent_c_prompt()
    user_message = (
        f"原始想法：{state.user_input}\n\n"
        f"創新驅動者的最終方案（A3）：\n{state.a3}\n\n"
        f"風險控制者的最終方案（B3）：\n{state.b3}"
    )

    response = await call_llm_with_retry(
        model_name=settings.agent_c_model,
        system_prompt=system_prompt,
        user_message=user_message,
        max_retries=settings.llm_max_retries,
        timeout=settings.llm_timeout,
    )
    return {"c1": response}


async def node_d(state: DebateState) -> dict:
    """Agent D 節點：接收所有方案，產出 JSON 評分表。

    Agent D 為獨立評審，對 A3、B3、C1 進行五維度量化評分。
    使用 json_mode=True 強制 JSON 輸出，並以 ScoreCard 模型驗證。
    驗證失敗時會將錯誤訊息附加至重試 prompt 中引導模型修正。
    """
    settings = get_settings()
    system_prompt = get_agent_d_prompt()
    user_message = (
        f"原始問題：{state.user_input}\n\n"
        f"創新驅動者的最終方案（A3）：\n{state.a3}\n\n"
        f"風險控制者的最終方案（B3）：\n{state.b3}\n\n"
        f"總結決策者的折衷方案（C1）：\n{state.c1}"
    )

    try:
        response = await call_llm_with_retry(
            model_name=settings.agent_d_model,
            system_prompt=system_prompt,
            user_message=user_message,
            max_retries=settings.llm_max_retries,
            timeout=settings.llm_timeout,
            json_mode=True,
        )
        score_card = ScoreCard.model_validate_json(response)
        return {"scores": score_card}

    except LLMCallError as e:
        error_msg = f"Agent D 評分失敗: {e}"
        logger.error(error_msg)
        return {"errors": state.errors + [error_msg]}
