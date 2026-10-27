"""V2单Agent的Provider-independent原生工具决策接口。"""
from typing import Protocol
from life_journey.schemas.agent import AgentDecision, AgentPrompt


class AgentLLMClient(Protocol):
    """图只依赖这个接口，具体SDK仍封装在既有Provider层。"""
    def decide(self, prompt: AgentPrompt) -> AgentDecision:
        """一次请求返回原生tool calls或结构化finalize决定，不暴露隐藏推理。"""
        ...
