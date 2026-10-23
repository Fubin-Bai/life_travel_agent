"""旅行基础信息与结构化预算；不查询价格或校验现实可行性。"""

from datetime import date
from decimal import Decimal
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .person import NonEmptyString
from .trip_context import TripContext

PositiveAmount = Annotated[Decimal, Field(gt=0, allow_inf_nan=False)]
CurrencyCode = Annotated[NonEmptyString, Field(pattern=r"^[A-Z]{3}$")]


class TripBudget(BaseModel):
    """规划预算，仅保存原币种金额，不拆分支出或验证真实货币有效性。

    不自动推断人均或全组、每日或全程及费用包含范围；使用预算前需明确口径。
    Python 输入使用 Decimal，JSON 序列化保留十进制字符串。
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    min_amount: PositiveAmount | None = None
    max_amount: PositiveAmount | None = None
    currency: CurrencyCode

    @model_validator(mode="after")
    def validate_amount_range(self) -> Self:
        """要求至少一个金额边界，且下限不得超过上限。"""
        if self.min_amount is None and self.max_amount is None:
            raise ValueError("至少提供 min_amount 或 max_amount 之一")
        if (self.min_amount is not None and self.max_amount is not None
                and self.min_amount > self.max_amount):
            raise ValueError("min_amount 不能大于 max_amount")
        return self


class Trip(BaseModel):
    """确定性的 Trip Setup 与独立的对话情境。

    trip_id 由应用创建函数生成并传入；本模型不生成 ID，仍支持显式 ID 还原。
    participant_ids 引用已有 Person，不复制 Profile，不从关系推断同行者。
    日期采用目的地当地日历，包含首尾两天；不读取外部人物或旅行集合。
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    trip_id: NonEmptyString
    participant_ids: list[NonEmptyString] = Field(min_length=1)
    destination: NonEmptyString
    start_date: date
    end_date: date
    budget: TripBudget
    context: TripContext = Field(default_factory=TripContext)

    @field_validator("participant_ids")
    @classmethod
    def reject_duplicate_participants(cls, value: list[str]) -> list[str]:
        """在字符串标准化后拒绝重复 ID，保留原有顺序。"""
        if len(value) != len(set(value)):
            raise ValueError("participant_ids 不能包含重复人物 ID")
        return value

    @model_validator(mode="after")
    def validate_date_order(self) -> Self:
        """允许同日与历史旅行，但结束日期不得早于开始日期。"""
        if self.end_date < self.start_date:
            raise ValueError("end_date 不能早于 start_date")
        return self
