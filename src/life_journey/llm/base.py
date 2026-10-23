"""单轮访谈的 Provider-independent 接口与结果，不建立通用模型平台。"""

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from life_journey.schemas import InterviewPrompt, InterviewTurnResult


class LLMClientError(RuntimeError):
    """可向调用方报告的安全错误，不包含凭据、完整 Prompt 或响应内容。"""


class LLMConfigurationError(LLMClientError):
    """环境配置或请求输出契约不正确。"""


class LLMRequestError(LLMClientError):
    """网络、超时、HTTP 或 SDK 请求失败，不自动重试。"""


class LLMResponseError(LLMClientError):
    """响应未完成、无文本、JSON 或领域 Schema 不合法。"""


class LLMCallMetrics(BaseModel):
    """已验证输出及本次调用指标；缺失 usage 为 None，不估算或编造。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    latency_ms: float = Field(ge=0, allow_inf_nan=False)
    cached_input_tokens: int | None = Field(default=None, ge=0)
    reasoning_tokens: int | None = Field(default=None, ge=0)


class LLMCallResult(LLMCallMetrics):
    """访谈输出与共用的调用指标；保留现有公共字段。"""
    output: InterviewTurnResult


@runtime_checkable
class InterviewLLMClient(Protocol):
    """调用方只依赖此接口；一次请求同时返回机器数据和完整 Assistant Turn。"""

    def generate_interview_turn(self, prompt: InterviewPrompt) -> LLMCallResult:
        """生成并校验一次访谈结果，不写回状态，不执行 Planning。"""
        ...
