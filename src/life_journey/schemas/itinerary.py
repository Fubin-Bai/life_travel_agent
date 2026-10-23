"""V0 模型知识行程，不提供实时事实、价格或可执行性保证。"""

from datetime import date
from typing import Literal, Self
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .person import NonEmptyString


class ItineraryActivity(BaseModel):
    """时间段仅为安排顺序，不声称验证交通、开放时间或费用。"""
    model_config = ConfigDict(extra="forbid", strict=True)
    time_period: Literal["morning", "afternoon", "evening"]
    title: NonEmptyString
    description: NonEmptyString
    rationale: NonEmptyString


class ItineraryDay(BaseModel):
    """某天主题和活动；只校验结构，不以 Schema 冒充事实核查。"""
    model_config = ConfigDict(extra="forbid", strict=True)
    date: date
    theme: NonEmptyString
    activities: list[ItineraryActivity] = Field(min_length=1)


class Itinerary(BaseModel):
    """完整旅行建议；实际日期覆盖与 Trip ID 在 application 层交叉核对。"""
    model_config = ConfigDict(extra="forbid", strict=True)
    trip_id: NonEmptyString
    summary: NonEmptyString
    days: list[ItineraryDay] = Field(min_length=1)

    @model_validator(mode="after")
    def ordered_unique_days(self) -> Self:
        """日期必须严格递增，不接受重复天或乱序。"""
        dates = [day.date for day in self.days]
        if dates != sorted(set(dates)):
            raise ValueError("行程日期必须递增且不重复")
        return self
