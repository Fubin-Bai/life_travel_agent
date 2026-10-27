"""草稿与局部修复的Provider-independent契约。"""
from typing import Protocol
from .base import LLMCallMetrics
from life_journey.schemas.validation import DraftItinerary,ReplanPatch
from life_journey.schemas.planning import PlanningPrompt

class DraftCallResult(LLMCallMetrics):
    """草稿与真实调用指标。"""
    output: DraftItinerary

class RepairCallResult(LLMCallMetrics):
    """补丁与真实调用指标。"""
    output: ReplanPatch

class ReplanningLLMClient(Protocol):
    """一次初稿与每轮一次补丁，重试/停止由图控制。"""
    def generate_draft(self,prompt:PlanningPrompt)->DraftCallResult: ...
    def repair_itinerary(self,prompt:PlanningPrompt)->RepairCallResult: ...
