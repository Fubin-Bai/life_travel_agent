"""保存本次旅行的内部结构化理解，不负责对话提取或更新。"""

from pydantic import BaseModel, ConfigDict, Field

from .person import NonEmptyString, TravelPace


class TripContext(BaseModel):
    """未来由对话逐渐形成；当前允许 fixture 直接构造，不是用户表单。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    purpose: NonEmptyString | None = None
    preferred_pace: TravelPace | None = None
    activity_preferences: list[NonEmptyString] = Field(
        default_factory=list, description="本次活动软偏好，尽量满足。"
    )
    required_activities: list[NonEmptyString] = Field(
        default_factory=list, description="本次明确要求应安排的活动。"
    )
    excluded_activities: list[NonEmptyString] = Field(
        default_factory=list, description="本次明确不要安排的活动。"
    )
