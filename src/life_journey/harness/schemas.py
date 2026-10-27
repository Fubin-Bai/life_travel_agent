"""运行上下文、脱敏事件、结构化错误和汇总，不包含业务正文。"""
from datetime import datetime
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field

EventType=Literal['RUN_STARTED','RUN_COMPLETED','RUN_FAILED','NODE_ENTERED','NODE_EXITED',
    'MODEL_CALLED','TOOL_REQUESTED','TOOL_COMPLETED','TOOL_FAILED','TOOL_CACHE_HIT','MEMORY_RETRIEVED',
    'VALIDATION_COMPLETED','REPLAN_STARTED','REPLAN_COMPLETED','BUDGET_REACHED','DUPLICATE_CALL_BLOCKED','FINALIZED']
ErrorCategory=Literal['provider_model','tool','invalid_tool_arguments','policy_violation','budget_exhausted',
    'memory_retrieval','validation','replanning','unexpected_internal','hook']
RunStatus=Literal['created','running','completed','unresolved','stopped','failed']

class HarnessError(BaseModel):
    """message只由运行层固定分类产生，不能写入异常原文。"""
    model_config=ConfigDict(extra='forbid',strict=True,frozen=True)
    code: str
    category: ErrorCategory
    message: str
    recoverable: bool
    stage: str
    metadata: dict[str,str|int|float|bool]=Field(default_factory=dict)

class ValidationTraceIssue(BaseModel):
    """只记录规则ID和类型，不记录用户约束正文。"""
    model_config=ConfigDict(extra='forbid',strict=True,frozen=True)
    issue_id: str
    type: str
    severity: Literal['hard','soft']

class TraceEvent(BaseModel):
    """只有白名单字段，不接受任意payload、Prompt或原始参数。"""
    model_config=ConfigDict(extra='forbid',strict=True,frozen=True)
    event_id: str
    run_id: str
    timestamp: datetime
    event_type: EventType
    graph_node: str | None=None
    tool_name: str | None=None
    sanitized_args: dict[str,str|int]=Field(default_factory=dict)
    status: str='ok'
    error_code: str | None=None
    duration_ms: float | None=Field(default=None,ge=0,allow_inf_nan=False)
    result_count: int | None=Field(default=None,ge=0)
    cache_hit: bool | None=None
    stop_reason: str | None=None
    validation_issue_count: int | None=Field(default=None,ge=0)
    validation_issues: list[ValidationTraceIssue]=Field(default_factory=list)
    replan_round: int | None=None
    memory_ids: list[str]=Field(default_factory=list)
    retrieval_scores: dict[str,float]=Field(default_factory=dict)

class AgentRunContext(BaseModel):
    """每次运行独立，SDK/数据库/业务正文/缓存均不放入可观察Context。"""
    model_config=ConfigDict(extra='forbid',strict=True)
    run_id: str
    trip_id: str
    planning_mode: Literal['agent','memory']
    started_at: datetime | None=None
    finished_at: datetime | None=None
    current_stage: str='created'
    current_graph_node: str | None=None
    tool_call_count: int=0
    model_call_count: int=0
    decision_count: int=0
    executed_tool_calls: int=0
    tool_counts: dict[str,int]=Field(default_factory=dict)
    cache_hits: int=0
    replan_round: int=0
    memory_retrieval_count: int=0
    validation_passes: int=0
    validation_failures: int=0
    warnings: list[str]=Field(default_factory=list)
    errors: list[HarnessError]=Field(default_factory=list)
    stop_reason: str=''
    status: RunStatus='created'
    timing_ms: dict[str,float]=Field(default_factory=dict)
    policy_snapshot: dict[str,str|int|float|None]=Field(default_factory=dict)
    memory_degraded: bool=False

class AgentRunSummary(BaseModel):
    """用于debug与离线聚合的标量指标；不提供质量保证。"""
    model_config=ConfigDict(extra='forbid',strict=True,frozen=True)
    run_id: str
    final_status: RunStatus
    total_duration_ms: float
    model_calls: int
    tool_calls: int
    executed_tool_calls: int
    cache_hits: int
    memory_retrievals: int
    validation_passes: int
    validation_failures: int
    replan_rounds: int
    warning_count: int
    error_count: int
    stop_reason: str
