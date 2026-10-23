"""用户创建输入，不包含系统生成字段，也不负责创建内部模型。"""

from datetime import date
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .person import Gender, MBTIType, NonEmptyString, TravelPace
from .relationship import RelationshipType
from .trip import TripBudget


class PersonCreate(BaseModel):
    """用户明确提供的人物信息；MBTI 仅为自述，不生成偏好。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    name: NonEmptyString
    gender: Gender | None = Field(default=None, description="用户明确提供，可不填写，不推断偏好或体力。")
    interests: list[NonEmptyString] = Field(default_factory=list)
    dislikes: list[NonEmptyString] = Field(default_factory=list)
    preferred_pace: TravelPace | None = None
    food_preferences: list[NonEmptyString] = Field(
        default_factory=list, description="明确的食物喜好，不承载硬性饮食限制。"
    )
    mbti: MBTIType | None = Field(
        default=None, description="仅接受用户明确自述，不推断，不自动转化为旅行偏好。"
    )

    @field_validator("mbti", mode="before")
    @classmethod
    def strip_mbti_whitespace(cls, value: object) -> object:
        """只去除首尾空白，不猜测类型或更正大小写。"""
        return value.strip() if isinstance(value, str) else value


class RelationshipCreate(BaseModel):
    """用户选择两个已有 Person ID 和固定关系类型，不查询人物集合。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    person_a_id: NonEmptyString
    person_b_id: NonEmptyString
    relationship_type: RelationshipType = Field(
        description=(
            "spouse 明确婚姻，partner 不声明婚姻状态，sibling 明确兄弟姐妹，"
            "family 只表示家庭关系，不推断 parent/child；A/B 无方向。"
        )
    )
    shared_travel_preferences: list[NonEmptyString] = Field(default_factory=list)
    preferred_pace_together: TravelPace | None = None

    @model_validator(mode="after")
    def reject_self_relationship(self) -> Self:
        """在 ID 去空白后拒绝自身关系。"""
        if self.person_a_id == self.person_b_id:
            raise ValueError("关系必须连接两个不同的人物 ID")
        return self


class TripCreate(BaseModel):
    """初始 Trip Setup，仅接受基础信息；对话情境由应用层初始化为空。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    participant_ids: list[NonEmptyString] = Field(min_length=1)
    destination: NonEmptyString
    start_date: date
    end_date: date
    budget: TripBudget

    @field_validator("participant_ids")
    @classmethod
    def reject_duplicate_participants(cls, value: list[str]) -> list[str]:
        """去空白后检查重复，不静默去重，保留选择顺序。"""
        if len(value) != len(set(value)):
            raise ValueError("participant_ids 不能包含重复人物 ID")
        return value

    @model_validator(mode="after")
    def validate_date_order(self) -> Self:
        """允许同日和历史旅行，结束日期不得早于开始日期。"""
        if self.end_date < self.start_date:
            raise ValueError("end_date 不能早于 start_date")
        return self
