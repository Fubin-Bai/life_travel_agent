"""Web 访谈传输契约，复用现有领域状态，不接受客户端注入状态。"""

from pydantic import BaseModel, ConfigDict, Field
from .interview import InterviewState
from .trip_context import TripContext


class InterviewMessage(BaseModel):
    """Trip ID 来自 URL，消息保留原文但拒绝纯空白。"""
    model_config = ConfigDict(extra="forbid", strict=True)
    user_message: str = Field(min_length=1, pattern=r"\S")


class InterviewResponse(BaseModel):
    """系统 ready 为最终门槛，模型建议分开保留；GET 不生成 assistant message。"""
    model_config = ConfigDict(extra="forbid", strict=True)
    trip_id: str
    assistant_message: str | None = None
    ready_to_plan: bool
    llm_ready_to_plan: bool | None = None
    context: TripContext
    state: InterviewState
    metrics: dict[str, str | int | float | None] | None = None
