"""公共 LLM 契约；此处不导入 SDK 或具体 Provider。"""

from .base import (
    InterviewLLMClient, LLMCallResult, LLMClientError,
    LLMConfigurationError, LLMRequestError, LLMResponseError,
)

__all__ = [
    "InterviewLLMClient", "LLMCallResult", "LLMClientError",
    "LLMConfigurationError", "LLMRequestError", "LLMResponseError",
]
