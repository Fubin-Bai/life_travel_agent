"""与 provider 无关的访谈请求，不包含 SDK 参数或网络执行。"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class InterviewPrompt(BaseModel):
    """供未来一次 LLM 调用使用：固定指令、输入 JSON 与单一 Assistant Turn 输出契约。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    system_prompt: str = Field(min_length=1)
    user_prompt: str = Field(min_length=1)
    output_schema: dict[str, Any]
