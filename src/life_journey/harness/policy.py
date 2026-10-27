"""一次运行的不可变策略；旧AgentBudget兼容引用同一个定义。"""
import os
from pydantic import BaseModel,ConfigDict,Field

class HarnessConfigurationError(ValueError):
    """运行前策略配置错误，不应误报为模型输出不合法。"""

class HarnessPolicy(BaseModel):
    """运行预算统一来源；领域Schema的硬上限仍独立保留。"""
    model_config=ConfigDict(extra='forbid',strict=True,frozen=True)
    max_tool_calls: int=Field(default=12,ge=1,le=24)
    max_search_calls: int=Field(default=6,ge=1,le=10)
    max_route_calls: int=Field(default=6,ge=1,le=12)
    max_calls_per_route_mode: int=Field(default=3,ge=1,le=6)
    max_candidates: int=Field(default=12,ge=1,le=12)
    max_search_limit: int=Field(default=2,ge=1,le=2)
    max_decisions: int=Field(default=8,ge=1,le=16)
    max_consecutive_duplicates: int=Field(default=2,ge=1,le=4)
    recursion_limit: int=Field(default=22,ge=1,le=60)
    max_replan_rounds: int=Field(default=2,ge=0,le=2)
    memory_top_k: int=Field(default=5,ge=1,le=10)
    max_run_seconds: float | None=Field(default=None,gt=0,le=1800,allow_inf_nan=False)
    memory_failure_mode: str=Field(default='fail',pattern='^(fail|continue_without_memory)$')

    @property
    def max_agent_rounds(self):
        """对外名称与旧max_decisions一致，不维护第二份值。"""
        return self.max_decisions

    def graph_recursion_limit(self,validated=False):
        """为现有草稿/校验/修复节点显式预留步数，不增加决策预算。"""
        return self.recursion_limit+(2*self.max_replan_rounds+5 if validated else 0)

    @classmethod
    def from_env(cls):
        """只开放两项非秘密环境覆盖，避免把全部内部细节环境化。"""
        values={}
        try:
            if 'LIFE_JOURNEY_MAX_TOOL_CALLS' in os.environ:values['max_tool_calls']=int(os.environ['LIFE_JOURNEY_MAX_TOOL_CALLS'])
            if 'LIFE_JOURNEY_MAX_RUN_SECONDS' in os.environ:values['max_run_seconds']=float(os.environ['LIFE_JOURNEY_MAX_RUN_SECONDS'])
            return cls(**values)
        except ValueError:raise HarnessConfigurationError('Harness预算配置无效，请检查工具次数或运行时长') from None

DEFAULT_POLICY=HarnessPolicy()
