"""独立人物、明确提供的个人偏好及可选的用户自述信息。"""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
TravelPace = Literal["slow", "moderate", "fast"]

Gender = Literal["female", "male", "other", "prefer_not_to_say"]

MBTIType = Literal[
    "ISTJ", "ISFJ", "INFJ", "INTJ", "ISTP", "ISFP", "INFP", "INTP",
    "ESTP", "ESFP", "ENFP", "ENTP", "ESTJ", "ESFJ", "ENFJ", "ENTJ",
]


class Person(BaseModel):
    """空列表表示未记录偏好；食物喜好不等于硬性饮食限制。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    person_id: NonEmptyString
    name: NonEmptyString
    gender: Gender | None = Field(default=None, description="用户明确提供的性别；不自动推断兴趣、体力或旅行偏好。")
    interests: list[NonEmptyString] = Field(default_factory=list)
    dislikes: list[NonEmptyString] = Field(default_factory=list)
    preferred_pace: TravelPace | None = None
    food_preferences: list[NonEmptyString] = Field(
        default_factory=list, description="明确的食物喜好，不承载硬性饮食限制。"
    )
    mbti: MBTIType | None = Field(
        default=None,
        description=(
            "仅保存用户明确输入的自我描述，不根据行为或聊天推断，"
            "不自动转化为旅行偏好；明确偏好始终优先。"
        ),
    )

    @field_validator("mbti", mode="before")
    @classmethod
    def strip_mbti_whitespace(cls, value: object) -> object:
        """只去除首尾空白，不纠正大小写或猜测人格类型。"""
        return value.strip() if isinstance(value, str) else value
