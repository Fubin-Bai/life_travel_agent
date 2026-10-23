"""DeepSeek Responses API 传输实现，不复制访谈业务规则。

官方参数依据：https://api-docs.deepseek.com/api/create-response/
不使用 responses.parse 的严格 Schema 改写，以保留增量字段可省略语义。
"""

from dataclasses import dataclass
import json
import math
import os
from time import perf_counter

from openai import APIConnectionError, APIError, APIStatusError, OpenAI
from pydantic import ValidationError

from life_journey.schemas import InterviewPrompt, InterviewTurnResult
from .planning import PlanningCallResult
from life_journey.schemas.itinerary import Itinerary
from life_journey.schemas.planning import PlanningPrompt
from .base import LLMCallResult, LLMConfigurationError, LLMRequestError, LLMResponseError

BASE_URL = "https://api.deepseek.com"


@dataclass(frozen=True)
class DeepSeekConfig:
    """非秘密配置；模型默认值集中管理，不自动读取 .env 文件。"""

    model: str = "deepseek-flash"
    max_output_tokens: int = 2048
    timeout_seconds: float = 60.0

    def __post_init__(self) -> None:
        """拒绝空模型、无效 token 上限和非有限超时。"""
        if not isinstance(self.model, str) or not self.model.strip():
            raise LLMConfigurationError("DEEPSEEK_MODEL 不能为空")
        if type(self.max_output_tokens) is not int or self.max_output_tokens <= 0:
            raise LLMConfigurationError("max_output_tokens 必须为正整数")
        if (not isinstance(self.timeout_seconds, (int, float))
                or isinstance(self.timeout_seconds, bool)
                or not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0):
            raise LLMConfigurationError("timeout_seconds 必须为正有限数")

    @classmethod
    def from_env(cls) -> "DeepSeekConfig":
        """只从环境选择模型，Key 在 Provider 创建时单独读取且不进入配置 repr。"""
        return cls(model=os.environ.get("DEEPSEEK_MODEL", cls.model).strip())


class DeepSeekInterviewClient:
    """一次 generate 对应一次非流式 API 请求；关闭 SDK 内置重试。"""

    def __init__(self, config: DeepSeekConfig | None = None, *, sdk_client: OpenAI | None = None):
        """从环境读取 Key；可注入使用 fake HTTP transport 的 SDK 进行离线测试。"""
        key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
        if not key:
            raise LLMConfigurationError("DEEPSEEK_API_KEY 未配置")
        if not key.isascii() or any(ord(char) < 33 or ord(char) > 126 for char in key):
            raise LLMConfigurationError("DEEPSEEK_API_KEY 格式错误：含非 ASCII 字符或内部空白，请检查启动终端环境变量；系统环境优先于.env")
        self.config = config or DeepSeekConfig.from_env()
        if sdk_client is None:
            self._client = OpenAI(
                api_key=key, base_url=BASE_URL, max_retries=0,
                timeout=self.config.timeout_seconds,
            )
        else:
            self._client = sdk_client.with_options(
                api_key=key, base_url=BASE_URL, max_retries=0, timeout=self.config.timeout_seconds,
            )

    def close(self) -> None:
        """释放 SDK HTTP 连接；不持久化请求或用户数据。"""
        self._client.close()

    def generate_interview_turn(self, prompt: InterviewPrompt) -> LLMCallResult:
        """映射请求、验证响应并返回指标；不记录 Prompt、Key 或推理文本。"""
        return self._generate_structured(prompt, InterviewTurnResult, LLMCallResult)

    def generate_itinerary(self, prompt: PlanningPrompt) -> PlanningCallResult:
        """复用同一安全传输路径，输出契约使用 Itinerary；不复制访谈语义。"""
        return self._generate_structured(prompt, Itinerary, PlanningCallResult)

    def _generate_structured(self, prompt, output_model, result_model):
        """仅共用 HTTP/JSON/指标逻辑，任务规则仍在各自 Prompt Builder 中。"""
        schema = output_model.model_json_schema(mode="validation")
        if prompt.output_schema != schema:
            raise LLMConfigurationError(f"Prompt output_schema 与 {output_model.__name__} 不一致")
        started = perf_counter()
        try:
            response = self._client.responses.create(
                model=self.config.model,
                instructions=prompt.system_prompt,
                input=prompt.user_prompt,
                text={"format": {"type": "json_schema", "name": output_model.__name__, "schema": schema}},
                reasoning={"effort": "none"},
                max_output_tokens=self.config.max_output_tokens,
                stream=False,
            )
        except APIConnectionError:
            raise LLMRequestError("DeepSeek 网络连接或请求超时失败；未自动重试") from None
        except APIStatusError as exc:
            raise LLMRequestError(f"DeepSeek HTTP 请求失败（状态码 {exc.status_code}）；未自动重试") from None
        except APIError:
            raise LLMRequestError("DeepSeek SDK 请求失败；未自动重试") from None
        latency_ms = (perf_counter() - started) * 1000

        if response.status != "completed" or response.incomplete_details is not None:
            raise LLMResponseError("DeepSeek 响应未完成、被截断或失败")
        if response.error is not None:
            raise LLMResponseError("DeepSeek 响应包含 API 错误")
        messages = [item for item in (response.output or []) if item.type == "message"]
        if len(messages) != 1:
            raise LLMResponseError("DeepSeek 响应必须包含一个可用的 Assistant Message")
        message = messages[0]
        if message.status != "completed" or message.role != "assistant":
            raise LLMResponseError("DeepSeek Assistant Message 未完成")
        parts = [part for part in (message.content or []) if part.type == "output_text"]
        if any(not isinstance(part.text, str) for part in parts):
            raise LLMResponseError("DeepSeek 响应文本格式不合法")
        text = "".join(part.text for part in parts)
        if not text.strip():
            raise LLMResponseError("DeepSeek 响应没有可用文本")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            raise LLMResponseError("DeepSeek 输出不是合法 JSON") from None
        try:
            output = output_model.model_validate_json(text)
        except ValidationError:
            raise LLMResponseError(f"DeepSeek 输出未通过 {output_model.__name__} 校验") from None

        usage = response.usage
        try:
            return result_model(
                output=output, provider="deepseek", model=getattr(response, "model", None),
                input_tokens=usage.input_tokens if usage else None,
                output_tokens=usage.output_tokens if usage else None,
                total_tokens=usage.total_tokens if usage else None,
                latency_ms=latency_ms,
                cached_input_tokens=getattr(getattr(usage, "input_tokens_details", None), "cached_tokens", None),
                reasoning_tokens=getattr(getattr(usage, "output_tokens_details", None), "reasoning_tokens", None),
            )
        except ValidationError:
            raise LLMResponseError("DeepSeek 调用指标格式不合法") from None
