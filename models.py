"""資料模型模組

定義辯論流程中所有資料結構，使用 Pydantic v2 進行驗證。
支援動態輪數辯論，所有中間結果皆保留。
"""

from enum import Enum
from typing import Optional
import uuid

from pydantic import BaseModel, Field, field_validator


class DebatePhase(str, Enum):
    INITIATED = "initiated"
    DEBATING = "debating"
    SYNTHESIS = "synthesis"
    SCORING = "scoring"
    COMPLETED = "completed"
    FAILED = "failed"


class DimensionScore(BaseModel):
    score: int = Field(ge=1, le=10)
    comment: str


class ProposalScore(BaseModel):
    feasibility: DimensionScore
    innovation: DimensionScore
    risk_control: DimensionScore
    cost_effectiveness: DimensionScore
    overall_recommendation: DimensionScore


class ScoreCard(BaseModel):
    a_score: ProposalScore
    b_score: ProposalScore
    c1_score: ProposalScore
    recommended: str = Field(pattern=r"^(a_final|b_final|c1)$")
    rationale: str = Field(default="")


class DebateConfig(BaseModel):
    """辯論設定，可由前端自訂"""
    rounds: int = Field(default=3, ge=1, le=10, description="辯論來回輪數")
    prompt_a: str = Field(default="", description="Agent A 自訂 system prompt（空字串則用預設）")
    prompt_b: str = Field(default="", description="Agent B 自訂 system prompt")
    prompt_c: str = Field(default="", description="Agent C 自訂 system prompt")
    prompt_d: str = Field(default="", description="Agent D 自訂 system prompt")


class DebateState(BaseModel):
    """辯論全局狀態，支援動態輪數"""
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_input: str
    config: DebateConfig = Field(default_factory=DebateConfig)

    # 動態輪數：a_responses[0]=A1, a_responses[1]=A2, ...
    a_responses: list[str] = Field(default_factory=list)
    b_responses: list[str] = Field(default_factory=list)

    # Agent C / D
    c1: Optional[str] = None
    scores: Optional[ScoreCard] = None

    # 流程控制
    current_phase: DebatePhase = DebatePhase.INITIATED
    current_round: int = 0  # 當前輪次 (1-based when running)
    total_rounds: int = 3
    errors: list[str] = Field(default_factory=list)


class DebateCreateRequest(BaseModel):
    user_input: str = Field(min_length=1)
    config: Optional[DebateConfig] = None

    @field_validator("user_input")
    @classmethod
    def validate_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("輸入不可為空白")
        return v.strip()


class DebateCreateResponse(BaseModel):
    session_id: str
    status: str = "initiated"


class DebateStatusResponse(BaseModel):
    session_id: str
    current_phase: DebatePhase
    current_round: int
    total_rounds: int
    user_input: str
    a_responses: list[str] = []
    b_responses: list[str] = []
    c1: Optional[str] = None
    scores: Optional[ScoreCard] = None
    errors: list[str] = []


class PhaseUpdate(BaseModel):
    event_type: str  # round_start | round_complete | synthesis_start | scoring_start | debate_complete | error
    phase: DebatePhase
    current_round: int = 0
    total_rounds: int = 0
    data: Optional[dict] = None
    error_message: Optional[str] = None
