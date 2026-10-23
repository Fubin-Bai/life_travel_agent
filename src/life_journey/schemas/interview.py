"""访谈状态与未来 LLM 输出协议，不生成问题、不存储对话历史。"""

from typing import Literal, Self, get_args

from pydantic import (
    BaseModel, ConfigDict, Field, SerializerFunctionWrapHandler,
    computed_field, model_serializer, model_validator,
)

from .person import NonEmptyString, TravelPace
from .trip_context import TripContext

InterviewTopic = Literal[
    "purpose", "preferred_pace", "activity_preferences",
    "required_activities", "excluded_activities", "special_requirements",
]
ConfirmationStatus = Literal["unknown", "confirmed"]
ALL_INTERVIEW_TOPICS: tuple[InterviewTopic, ...] = get_args(InterviewTopic)
MINIMUM_PLANNING_TOPICS: tuple[InterviewTopic, ...] = (
    "purpose", "preferred_pace", "required_activities", "excluded_activities",
)


class InterviewTopics(BaseModel):
    """确认状态独立于内容；confirmed 可以对应空列表或无具体偏好。"""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    purpose: ConfirmationStatus = "unknown"
    preferred_pace: ConfirmationStatus = "unknown"
    activity_preferences: ConfirmationStatus = "unknown"
    required_activities: ConfirmationStatus = "unknown"
    excluded_activities: ConfirmationStatus = "unknown"
    special_requirements: ConfirmationStatus = "unknown"


class InterviewState(BaseModel):
    """绑定一次旅行的内部状态；阶段与就绪值为只读派生结果。

    trip_setup_complete 是应用函数检查当前 Setup 后记录的快照，不由 LLM 提供。
    下一次判断必须重新检查当前 TravelContext，不能只信任旧快照。
    """

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    trip_id: NonEmptyString
    topics: InterviewTopics = Field(default_factory=InterviewTopics)
    trip_setup_complete: bool = False

    @computed_field
    @property
    def missing_topics(self) -> list[InterviewTopic]:
        """按固定主题顺序列出所有未知项，含不阻塞的建议主题。"""
        return [topic for topic in ALL_INTERVIEW_TOPICS if getattr(self.topics, topic) == "unknown"]

    @computed_field
    @property
    def ready_to_plan(self) -> bool:
        """唯一最低规则：完整 Setup 且四个必需主题均已确认。"""
        return self.trip_setup_complete and all(
            getattr(self.topics, topic) == "confirmed" for topic in MINIMUM_PLANNING_TOPICS
        )

    @computed_field
    @property
    def phase(self) -> Literal["interviewing", "ready_to_plan"]:
        """仅表示访谈是否达到最低条件，不执行 Planning。"""
        return "ready_to_plan" if self.ready_to_plan else "interviewing"


class TripContextUpdate(BaseModel):
    """只表达本轮增量；未出现字段不清空已有值。

    purpose / preferred_pace 的显式 None 表达明确无具体目的或节奏偏好。
    列表的省略代表不更新，[] 表达明确没有，显式 None 则拒绝。
    列表字段一旦提供，就是该字段新的完整值，不是待追加项；应用层不合并历史值。
    字段是否确认由 confirmed_topics 单独表达，不能仅凭更新内容推断。
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    purpose: NonEmptyString | None = None
    preferred_pace: TravelPace | None = None
    activity_preferences: list[NonEmptyString] | None = None
    required_activities: list[NonEmptyString] | None = None
    excluded_activities: list[NonEmptyString] | None = None

    @model_validator(mode="after")
    def reject_explicit_null_lists(self) -> Self:
        """列表只允许省略或传列表，避免 null 与明确没有相混淆。"""
        for field in ("activity_preferences", "required_activities", "excluded_activities"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} 不接受 null；无更新请省略，明确没有请用 []")
        return self

    @model_serializer(mode="wrap")
    def serialize_only_provided_fields(self, handler: SerializerFunctionWrapHandler) -> dict:
        """包括嵌套 JSON 序列化在内，只保留实际提供的字段，避免传输时丢失 unset 语义。"""
        return {key: value for key, value in handler(self).items() if key in self.model_fields_set}


class InterviewTurnResult(BaseModel):
    """一次未来 LLM 调用同时返回机器更新和单一 Assistant Turn；ready/missing 仍只作建议。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    context_update: TripContextUpdate
    confirmed_topics: list[InterviewTopic]
    missing_topics: list[InterviewTopic]
    ready_to_plan: bool
    assistant_message: str = Field(
        min_length=1, pattern=r"\S",
        description="单一 Assistant Turn：回应和必要追问在同一完整自然回复中；不要求问号，不用于推断状态。",
    )

    @model_validator(mode="after")
    def validate_turn_protocol(self) -> Self:
        """拒绝重复或矛盾主题；回复无需包含问题或问号。"""
        for field in ("confirmed_topics", "missing_topics"):
            topics = getattr(self, field)
            if len(topics) != len(set(topics)):
                raise ValueError(f"{field} 不允许重复主题")
        if set(self.confirmed_topics) & set(self.missing_topics):
            raise ValueError("同一主题不能同时属于 confirmed_topics 和 missing_topics")
        return self


class AppliedInterviewTurn(BaseModel):
    """一次原子应用的结果，分别保存更新后的情境、状态与 LLM 就绪建议。

    不回写 Trip，不触发 Planning。两种 ready 的差异留给未来 orchestration。
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    updated_context: TripContext
    updated_state: InterviewState
    llm_ready_to_plan: bool
    assistant_message: str = Field(
        min_length=1, pattern=r"\S", description="已校验的用户可读回复，原样透传，不参与状态判断。"
    )

    @computed_field
    @property
    def deterministic_ready_to_plan(self) -> bool:
        """系统最低门槛由更新后状态派生，不覆盖 LLM 原始建议。"""
        return self.updated_state.ready_to_plan
