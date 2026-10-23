"""安全应用已校验的情境更新并同步确认；不解析回答、推断意图或执行 Planning。"""

from pydantic import ValidationError

from life_journey.schemas.create import TripCreate
from life_journey.schemas.interview import (
    AppliedInterviewTurn, InterviewState, InterviewTopic, InterviewTurnResult, TripContextUpdate,
)
from life_journey.schemas.travel_context import TravelContext
from life_journey.schemas.trip_context import TripContext


def _setup_is_complete(context: TravelContext) -> bool:
    """复用 TripCreate 验证必需 Setup，拒绝被后续修改为无效的对象。"""
    if not isinstance(context, TravelContext):
        raise TypeError("context 必须是 TravelContext")
    data = context.trip.model_dump(mode="python", exclude={"trip_id", "context"})
    try:
        TripCreate.model_validate(data)
    except ValidationError:
        return False
    return True


def initialize_interview(context: TravelContext) -> InterviewState:
    """创建全部主题未知的状态，不从 Profile、关系或已有 Context 推断确认。"""
    return InterviewState(
        trip_id=context.trip.trip_id, trip_setup_complete=_setup_is_complete(context)
    )


def get_missing_topics(state: InterviewState) -> list[InterviewTopic]:
    """返回新列表；建议主题仍可 missing，但不一定阻塞 Planning。"""
    return state.missing_topics


def check_minimum_readiness(context: TravelContext, state: InterviewState) -> bool:
    """重新验证当前 Setup，并使用集中定义的最低主题规则；不读取 LLM 判断。"""
    refreshed = _refresh_state(context, state, state.topics.model_dump())
    return refreshed.ready_to_plan


def _refresh_state(context: TravelContext, state: InterviewState, topics: dict) -> InterviewState:
    """绑定同一 Trip，并用当前 Setup 重新计算只读就绪信息。"""
    if context.trip.trip_id != state.trip_id:
        raise ValueError("InterviewState 与当前 Trip 的 trip_id 不匹配")
    return InterviewState(
        trip_id=state.trip_id, topics=topics, trip_setup_complete=_setup_is_complete(context)
    )


def apply_interview_turn(
    context: TravelContext, state: InterviewState, turn: InterviewTurnResult,
) -> InterviewState:
    """保留原有仅返回状态的入口；需要同步情境时使用 apply_interview_update。

    确认是累计的；本轮不实现撤销确认、内容冲突或特殊要求的具体值存储。
    若 LLM 提前建议 ready，新状态仍可能 interviewing；本轮不生成补问问题。
    """
    topics = state.topics.model_dump()
    for topic in turn.confirmed_topics:
        topics[topic] = "confirmed"
    return _refresh_state(context, state, topics)


def apply_trip_context_update(
    current: TripContext, update: TripContextUpdate,
) -> TripContext:
    """按字段存在性应用更新并重新校验，不修改任何输入。

    标量省略保留、具体值覆盖、显式 None 清空。
    列表省略保留，提供时完整替换（含 []），不追加、合并或去重。
    """
    if not isinstance(current, TripContext) or not isinstance(update, TripContextUpdate):
        raise TypeError("需要已校验的 TripContext 与 TripContextUpdate")
    # 重新校验可变的输入模型，防止构造后追加非法值或将列表改成 None。
    validated = TripContextUpdate.model_validate(update.model_dump(mode="python"))
    values = current.model_dump(mode="python")
    for field in ("purpose", "preferred_pace"):
        if field in validated.model_fields_set:
            values[field] = getattr(validated, field)
    for field in ("activity_preferences", "required_activities", "excluded_activities"):
        if field in validated.model_fields_set:
            values[field] = getattr(validated, field)
    return TripContext.model_validate(values)


def apply_interview_update(
    context: TravelContext, state: InterviewState, turn: InterviewTurnResult,
) -> AppliedInterviewTurn:
    """同时返回新的 TripContext 与状态，原子校验，不写回 Trip 或修改输入。

    TravelContext 提供当前 TripContext、Setup 和 trip_id，避免只信任旧 Setup 快照。
    显式 confirmed_topics 确认更新后的字段；未提供更新则重新确认已存值，
    包括旧值为 None / [] 的情形，不猜测清空、不从值自动确认或撤销确认。
    special_requirements 只累计确认状态，不保存具体内容。
    assistant_message 仅原样透传，不解析、不改写，也不参与确认或 readiness 判断。
    """
    if not isinstance(turn, InterviewTurnResult):
        raise TypeError("turn 必须是已校验的 InterviewTurnResult")
    validated_turn = InterviewTurnResult.model_validate(turn.model_dump(mode="python"))
    updated_context = apply_trip_context_update(context.trip.context, validated_turn.context_update)
    updated_state = apply_interview_turn(context, state, validated_turn)
    return AppliedInterviewTurn(
        updated_context=updated_context, updated_state=updated_state,
        llm_ready_to_plan=validated_turn.ready_to_plan,
        assistant_message=validated_turn.assistant_message,
    )
