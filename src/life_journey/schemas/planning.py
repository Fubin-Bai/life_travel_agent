"""Provider-independent Planning 请求和 Web 返回值。"""
from typing import Any
from pydantic import BaseModel, ConfigDict, Field
from .itinerary import Itinerary

V0_FACT_NOTICE = "V0 行程基于模型知识生成；未验证营业时间、交通、价格或实时信息，请出行前核实。"


class PlanningPrompt(BaseModel):
    """普通任务字符串和领域 JSON Schema，不绑定具体 SDK。"""
    model_config = ConfigDict(extra="forbid", strict=True)
    system_prompt: str = Field(min_length=1)
    user_prompt: str = Field(min_length=1)
    output_schema: dict[str, Any]


class PlanningResponse(BaseModel):
    """事实边界由程序固定附带，不能依赖模型自愿声明。"""
    model_config = ConfigDict(extra="forbid", strict=True)
    itinerary: Itinerary
    notice: str = V0_FACT_NOTICE
    metrics: dict[str, str | int | float | None] | None = None
