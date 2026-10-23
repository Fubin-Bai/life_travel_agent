"""串联一次访谈调用与安全更新；不依赖具体 Provider，不执行 Planning。"""

from dataclasses import dataclass

from life_journey.llm import InterviewLLMClient
from life_journey.schemas import InterviewState, TravelContext
from .interview import apply_interview_update
from .interview_prompt import build_interview_prompt


@dataclass(frozen=True)
class InterviewRunResult:
    """单轮结果；完整上下文供下一轮使用，指标缺失保持 None。"""

    updated_context: TravelContext
    updated_state: InterviewState
    assistant_message: str
    llm_ready_to_plan: bool
    metrics: dict[str, str | int | float | None]

    @property
    def deterministic_ready_to_plan(self) -> bool:
        """从系统状态派生，不采用模型建议或回复文案。"""
        return self.updated_state.ready_to_plan


def run_interview_turn(
    context: TravelContext, state: InterviewState, user_message: str,
    client: InterviewLLMClient,
) -> InterviewRunResult:
    """一次用户输入只调用一次 Client；返回独立新对象，不解析自然回复。"""
    prompt = build_interview_prompt(context, state, user_message)
    call = client.generate_interview_turn(prompt)
    applied = apply_interview_update(context, state, call.output)
    # 显式写入新情境并重新校验完整上下文，避免 model_copy(update=...) 绕过校验。
    data = context.model_dump(mode="python")
    data["trip"]["context"] = applied.updated_context.model_dump(mode="python")
    updated_context = TravelContext.model_validate(data)
    return InterviewRunResult(
        updated_context=updated_context, updated_state=applied.updated_state,
        assistant_message=applied.assistant_message,
        llm_ready_to_plan=applied.llm_ready_to_plan,
        metrics=call.model_dump(mode="python", exclude={"output"}),
    )
