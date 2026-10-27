"""V3草稿、可解释校验和局部修复契约；不放宽旧Itinerary。"""
from datetime import date as CalendarDate
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from .itinerary import ItineraryDay
from .person import NonEmptyString

from life_journey.harness.policy import DEFAULT_POLICY
MAX_REPLAN_ROUNDS = DEFAULT_POLICY.max_replan_rounds

class DraftItinerary(BaseModel):
    """保留可诊断的日期冲突，交给Validator而非结构层丢弃。"""
    model_config = ConfigDict(extra='forbid', strict=True)
    trip_id: NonEmptyString
    summary: NonEmptyString
    days: list[ItineraryDay] = Field(min_length=1, max_length=366)

class ConstraintIssue(BaseModel):
    """引用仅是草稿中的稳定位置dN:aN，不是跨版本永久ID。"""
    model_config = ConfigDict(extra='forbid', strict=True)
    issue_id: str
    severity: Literal['hard','soft']
    type: str
    message: str
    day: int | None = None
    date: CalendarDate | None = None
    activity_reference: str | None = None
    evidence_reference: str
    repair_hint: str

class ValidationResult(BaseModel):
    """计数和影响范围由后端从issues推导。"""
    model_config = ConfigDict(extra='forbid', strict=True)
    valid: bool
    violations: list[ConstraintIssue]
    warnings: list[ConstraintIssue]
    hard_violation_count: int
    soft_warning_count: int
    affected_days: list[int]
    affected_activity_ids: list[str]
    constraint_types: list[str]
    summary: str

class DayRepair(BaseModel):
    """只替换有问题的某一天；None索引仅可补缺失日期。"""
    model_config = ConfigDict(extra='forbid', strict=True)
    day_index: int | None = Field(default=None, ge=0)
    replacement: ItineraryDay | None = None

class ReplanPatch(BaseModel):
    """禁止默认全份重写，未受影响天不允许修改。"""
    model_config = ConfigDict(extra='forbid', strict=True)
    days: list[DayRepair] = Field(default_factory=list, max_length=20)
    trip_id: str | None = None
    summary: str | None = None
