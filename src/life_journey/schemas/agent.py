"""V2决策、工具参数与可观察指标；不保存隐藏推理或Provider原文。"""
from typing import Any, Literal, Self
from pydantic import Field, model_validator
from life_journey.tools.schemas import ToolModel, NonEmptyString


AGENT_DECISION_MAX_OUTPUT_TOKENS = 1536


from life_journey.harness.policy import HarnessPolicy as AgentBudget


class SearchPlacesArguments(ToolModel):
    """城市只允许已确认当前城市；一次一个短查询词，不接受Provider参数。"""
    city: NonEmptyString = Field(max_length=60)
    keyword: NonEmptyString = Field(max_length=100)
    limit: int = Field(default=2, ge=1, le=2)


class RouteArguments(ToolModel):
    """只引用当前已查询候选，不能由模型提供任意坐标或制造ID。"""
    origin_place_id: NonEmptyString = Field(max_length=100)
    destination_place_id: NonEmptyString = Field(max_length=100)

    @model_validator(mode='after')
    def different_places(self) -> Self:
        """同一地点不构成点间路线。"""
        if self.origin_place_id == self.destination_place_id:
            raise ValueError('路线端点相同')
        return self


class AgentToolCall(ToolModel):
    """原生function call的最小跨Provider表示；参数JSON在工具执行前单独校验。"""
    call_id: NonEmptyString = Field(max_length=128)
    name: NonEmptyString = Field(max_length=128)
    arguments: str = Field(max_length=4096)


class AgentReady(ToolModel):
    """不调用工具时只声明进入finalize，不返回行程或解释性推理。"""
    ready_to_plan: Literal[True]


class AgentDecisionMetrics(ToolModel):
    """仅记录Provider实际提供的决策调用指标，缺失不估算费用。"""
    model: str | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    latency_ms: float = Field(ge=0)


class AgentDecision(ToolModel):
    """一次决策只有工具调用或结束标志；不包含chain-of-thought。"""
    tool_calls: list[AgentToolCall] = Field(default_factory=list, max_length=3)
    ready_to_plan: bool = False
    call_metrics: AgentDecisionMetrics | None = None

    @model_validator(mode='after')
    def single_action(self) -> Self:
        """工具调用与结束不能同时出现，call_id本轮不可重复。"""
        if bool(self.tool_calls) == self.ready_to_plan:
            raise ValueError('工具调用或结束必须二选一')
        if len({c.call_id for c in self.tool_calls}) != len(self.tool_calls):
            raise ValueError('call_id重复')
        return self


class AgentPrompt(ToolModel):
    """原生工具契约和规范化消息；不依赖LangGraph或DeepSeek对象。"""
    system_prompt: NonEmptyString
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]]


class AgentToolObservation(ToolModel):
    """data只来自V1规范化模型；error_code仅固定安全分类。"""
    name: str
    status: Literal['ok', 'no_result', 'no_route', 'unknown', 'error']
    data: dict[str, Any] | None = None
    error_code: str | None = None
    cached: bool = False


class AgentActionTrace(ToolModel):
    """指标不存任意搜索词、完整参数、个人偏好或Provider错误内容。"""
    tool_name: str
    call_count: int
    sanitized_arguments: dict[str, str | int] = Field(default_factory=dict)
    status: Literal['ok', 'no_result', 'no_route', 'unknown', 'error']
    error_code: str | None = None
    latency_ms: float = Field(ge=0)
    cached: bool = False
    executed: bool = False


class AgentRunMetrics(ToolModel):
    """显式返回/日志可使用的安全行动轨迹，不含隐藏推理或原始回复。"""
    tool_call_count: int
    executed_tool_calls: int
    decision_count: int
    decision_metrics: list[AgentDecisionMetrics] = Field(default_factory=list)
    stop_reason: str
    place_count: int
    route_count: int
    opening_observation_count: int
    actions: list[AgentActionTrace]
    warnings: list[str]
    latency_ms: float


def tool_definitions() -> list[dict]:
    """只暴露本轮四个函数，不暴露任意Provider路径/Key或坐标。"""
    descriptions = {
        'search_places':'搜索当前已确认大陆城市中的真实地点，结果包含保守营业信息；不要搜索排除活动。',
        'get_walking_route':'查询当前候选两个不同地点间的有向步行路线，游客优先。',
        'get_transit_route':'查询当前候选间同城公交/地铁路线，不保证未来班次。',
        'get_driving_route':'补充驾车参考，不可当作默认游客方式或冒充步行/公交。',
    }
    return [{'type':'function','name':name,'description':descriptions[name],
             'parameters':schema.model_json_schema(mode='validation')} for name,schema in {'search_places':SearchPlacesArguments,'get_walking_route':RouteArguments,'get_transit_route':RouteArguments,'get_driving_route':RouteArguments}.items()]

