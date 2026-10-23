"""最小 Planning Client contract，fake 或任何 Provider 均可实现。"""
from typing import Protocol
from .base import LLMCallMetrics
from life_journey.schemas.itinerary import Itinerary
from life_journey.schemas.planning import PlanningPrompt


class PlanningCallResult(LLMCallMetrics):
    """结构化行程及真实调用指标，不添加通用模型平台。"""
    output: Itinerary


class PlanningLLMClient(Protocol):
    """独立规划方法；不滥用访谈输出协议承载行程。"""
    def generate_itinerary(self, prompt: PlanningPrompt) -> PlanningCallResult:
        """只调用一次并校验结构，不写回访谈状态。"""
        ...
