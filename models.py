"""資料模型模組

定義辯論流程中所有資料結構，使用 Pydantic v2 進行驗證。
包含辯論狀態、評分表、API 請求/回應模型。
"""

from enum import Enum
from typing import Optional
import uuid

from pydantic import BaseModel, Field, field_validator


class DebatePhase(str, Enum):
    """辯論階段列舉"""

    INITIATED = "initiated"
    PHASE_1 = "phase_1_initial_insights"
    PHASE_2 = "phase_2_cross_examination"
    PHASE_3 = "phase_3_final_revision"
    PHASE_4 = "phase_4_synthesis"
    PHASE_5 = "phase_5_scoring"
    COMPLETED = "completed"
    FAILED = "failed"


class DimensionScore(BaseModel):
    """單一維度評分"""

    score: int = Field(ge=1, le=10, description="1-10 整數分數")
    comment: str = Field(description="簡短評語")


class ProposalScore(BaseModel):
    """單一方案的五維度評分"""

    feasibility: DimensionScore  # 可行性
    innovation: DimensionScore  # 創新性
    risk_control: DimensionScore  # 風險控制
    cost_effectiveness: DimensionScore  # 成本效益
    overall_recommendation: DimensionScore  # 綜合推薦度


class ScoreCard(BaseModel):
    """完整評分表"""

    a3_score: ProposalScore  # Agent A 最終方案評分
    b3_score: ProposalScore  # Agent B 最終方案評分
    c1_score: ProposalScore  # Agent C 折衷方案評分
    recommended: str = Field(
        pattern=r"^(a3|b3|c1)$",
        description="綜合推薦度最高的方案標識",
    )
    rationale: str = Field(
        default="",
        description="綜合評分理由",
    )


class DebateState(BaseModel):
    """辯論全局狀態，作為 LangGraph 的 State Schema"""

    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_input: str

    # Agent A 回應（Phase 1/2/3）
    a1: Optional[str] = None  # 初步見解
    a2: Optional[str] = None  # 交叉回應
    a3: Optional[str] = None  # 最終修正

    # Agent B 回應（Phase 1/2/3）
    b1: Optional[str] = None
    b2: Optional[str] = None
    b3: Optional[str] = None

    # Agent C 回應（Phase 4）
    c1: Optional[str] = None  # 折衷方案

    # Agent D 回應（Phase 5）
    scores: Optional[ScoreCard] = None

    # 流程控制
    current_phase: DebatePhase = DebatePhase.INITIATED
    errors: list[str] = Field(default_factory=list)


class DebateCreateRequest(BaseModel):
    """建立辯論請求"""

    user_input: str = Field(min_length=1, description="原始想法文字")

    @field_validator("user_input")
    @classmethod
    def validate_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("輸入不可為空白")
        return v.strip()


class DebateCreateResponse(BaseModel):
    """建立辯論回應"""

    session_id: str
    status: str = "initiated"


class DebateStatusResponse(BaseModel):
    """辯論狀態查詢回應"""

    session_id: str
    current_phase: DebatePhase
    user_input: str
    a1: Optional[str] = None
    b1: Optional[str] = None
    a2: Optional[str] = None
    b2: Optional[str] = None
    a3: Optional[str] = None
    b3: Optional[str] = None
    c1: Optional[str] = None
    scores: Optional[ScoreCard] = None
    errors: list[str] = []


class PhaseUpdate(BaseModel):
    """SSE 階段更新事件"""

    event_type: str  # phase_start | phase_complete | debate_complete | error
    phase: DebatePhase
    data: Optional[dict] = None
    error_message: Optional[str] = None
