"""验证稀疏更新的应用语义、确认同步及输入隔离，不测试提取或 Planning。"""

import pytest
from pydantic import ValidationError

from fixtures import load_persons, load_relationships, load_trips
from life_journey.application import (
    apply_interview_update, apply_trip_context_update, build_travel_context, initialize_interview,
)
from life_journey.schemas import AppliedInterviewTurn, InterviewTurnResult, TripContext, TripContextUpdate
from life_journey.schemas.interview import MINIMUM_PLANNING_TOPICS


@pytest.fixture
def current_context():
    """各字段均有旧值，便于观察保留、覆盖与清空，不从自然语言推断更新。"""
    return TripContext(
        purpose="原目的", preferred_pace="fast", activity_preferences=["咖啡馆"],
        required_activities=["博物馆"], excluded_activities=["主题乐园"],
    )


@pytest.fixture
def travel_context():
    """复用固定旅行与长期 Profile；不调用网络或随机创建逻辑。"""
    return build_travel_context(load_trips()["trip_tokyo_alex_bella_slow"],
                                load_persons().values(), load_relationships().values())


def turn_result(**changes):
    """构造带模拟自然回复的明确轮次输出，不提供产品固定问卷。"""
    return InterviewTurnResult(**{
        "context_update": {}, "confirmed_topics": [], "missing_topics": [],
        "ready_to_plan": False, "assistant_message": "模拟自然回复", **changes,
    })


def test_omitted_fields_preserve_all_values(current_context):
    """Input：空更新；Expected Output：所有旧值保留但返回新对象；验证 unset 不误清空且输出重新通过模型校验。"""
    result = apply_trip_context_update(current_context, TripContextUpdate())
    assert result == current_context and result is not current_context
    assert TripContext.model_validate(result.model_dump()) == result


@pytest.mark.parametrize("field,new_value", [("purpose", "看展旅行"), ("preferred_pace", "slow")])
def test_scalar_overwrites_when_present(current_context, field, new_value):
    """Input：一个标量新值；Expected Output：只覆盖该字段、其他字段原样保留；验证显式 overwrite。"""
    expected = current_context.model_dump()
    expected[field] = new_value
    result = apply_trip_context_update(current_context, TripContextUpdate(**{field: new_value}))
    assert result.model_dump() == expected


@pytest.mark.parametrize("field", ["purpose", "preferred_pace"])
def test_explicit_none_clears_scalar(current_context, field):
    """Input：标量显式 None；Expected Output：对应旧值清空，其他字段保留；区分明确无偏好与省略。"""
    result = apply_trip_context_update(current_context, TripContextUpdate(**{field: None}))
    expected = current_context.model_dump()
    expected[field] = None
    assert result.model_dump() == expected


@pytest.mark.parametrize("field", ["activity_preferences", "required_activities", "excluded_activities"])
@pytest.mark.parametrize("new_value", [[], ["看展"], ["看展", "看展"]])
def test_list_replace_not_merge(current_context, field, new_value):
    """Input：空列表、不同新列表或含重复项的完整列表；Expected Output：完整替换，既不合并旧项也不去重；验证 replace。"""
    previous = list(getattr(current_context, field))
    result = apply_trip_context_update(current_context, TripContextUpdate(**{field: new_value}))
    expected = current_context.model_dump()
    expected[field] = new_value
    assert result.model_dump() == expected
    assert getattr(current_context, field) == previous
    assert all(item not in getattr(result, field) for item in previous)


def test_list_omission_preserves_others(current_context):
    """Input：只更新 purpose；Expected Output：三个旧列表全部保留；避免其他字段默认 None 覆盖旧数据。"""
    result = apply_trip_context_update(current_context, TripContextUpdate(purpose="新目的"))
    for field in ("activity_preferences", "required_activities", "excluded_activities"):
        assert getattr(result, field) == getattr(current_context, field)


def test_low_level_application_does_not_share_or_mutate_inputs(current_context):
    """Input：具体列表更新；Expected Output：应用前后两输入不变，结果列表与更新及旧列表均独立；防止后续修改污染。"""
    update = TripContextUpdate(activity_preferences=["看展"])
    before = (current_context.model_dump(), update.model_dump(), set(update.model_fields_set))
    result = apply_trip_context_update(current_context, update)
    assert before == (current_context.model_dump(), update.model_dump(), set(update.model_fields_set))
    result.activity_preferences.append("结果新增")
    result.required_activities.append("结果新增")
    assert update.activity_preferences == ["看展"]
    assert current_context.required_activities == ["博物馆"]
    update.activity_preferences.append("更新新增")
    current_context.excluded_activities.append("旧值新增")
    assert result.activity_preferences == ["看展", "结果新增"]
    assert result.excluded_activities == ["主题乐园"]


def test_mutated_update_is_revalidated(current_context):
    """Input：构造后将更新列表改为 None；Expected Output：ValidationError 且旧情境不变；应用时不信任可变对象的过期校验。"""
    update = TripContextUpdate(required_activities=[])
    update.required_activities = None
    before = current_context.model_dump()
    with pytest.raises(ValidationError, match="不接受 null"):
        apply_trip_context_update(current_context, update)
    assert current_context.model_dump() == before


def test_result_is_revalidated_after_preserving_old_values(current_context):
    """Input：旧情境在构造后被改为非法节奏、更新未覆盖该项；Expected Output：ValidationError；不使用跳过校验的复制。"""
    current_context.preferred_pace = "invalid"
    with pytest.raises(ValidationError):
        apply_trip_context_update(current_context, TripContextUpdate())


def test_combined_update_clears_and_confirms(travel_context):
    """Input：四个最低字段明确 None/[] 并确认；Expected Output：新 Context 与 State、missing 缩减、确定性 ready；空值不等于未确认。"""
    state = initialize_interview(travel_context)
    turn = turn_result(
        context_update={"purpose": None, "preferred_pace": None,
                        "required_activities": [], "excluded_activities": []},
        confirmed_topics=list(MINIMUM_PLANNING_TOPICS), ready_to_plan=True, assistant_message="模拟就绪回复",
    )
    result = apply_interview_update(travel_context, state, turn)
    assert result.updated_context is not travel_context.trip.context
    assert result.updated_state is not state
    assert result.updated_context.purpose is result.updated_context.preferred_pace is None
    assert result.updated_context.required_activities == result.updated_context.excluded_activities == []
    assert result.updated_context.activity_preferences == travel_context.trip.context.activity_preferences
    assert result.updated_state.missing_topics == ["activity_preferences", "special_requirements"]
    assert result.deterministic_ready_to_plan and result.llm_ready_to_plan
    assert result.updated_state.phase == "ready_to_plan"
    assert state.topics.purpose == "unknown"


@pytest.mark.parametrize("llm_ready", [False, True])
@pytest.mark.parametrize("minimum_confirmed", [False, True])
def test_readiness_judgments_remain_separate(travel_context, llm_ready, minimum_confirmed):
    """Input：LLM ready 与四主题确认的四种组合；Expected Output：各自原样保留，系统只按最低门槛；不实现进入 Planning 的决策。"""
    turn = turn_result(
        confirmed_topics=list(MINIMUM_PLANNING_TOPICS) if minimum_confirmed else [],
        ready_to_plan=llm_ready, assistant_message="模拟就绪回复" if llm_ready else "模拟继续访谈回复",
    )
    result = apply_interview_update(travel_context, initialize_interview(travel_context), turn)
    assert result.llm_ready_to_plan is llm_ready
    assert result.deterministic_ready_to_plan is minimum_confirmed
    assert result.updated_state.ready_to_plan is minimum_confirmed


def test_special_requirements_only_updates_state(travel_context):
    """Input：只确认特殊要求主题、不提供具体内容；Expected Output：Context 值不变、状态已确认；不暗中新增存储字段。"""
    result = apply_interview_update(travel_context, initialize_interview(travel_context),
                                    turn_result(confirmed_topics=["special_requirements"]))
    assert result.updated_context == travel_context.trip.context
    assert result.updated_context is not travel_context.trip.context
    assert result.updated_state.topics.special_requirements == "confirmed"
    assert "special_requirements" not in result.updated_context.model_dump()


def test_confirmation_without_patch_reconfirms_stored_value(travel_context):
    """Input：确认 purpose 但不提供该字段更新；Expected Output：确认已存目的且不清空；省略不被误解释为确认没有。"""
    result = apply_interview_update(travel_context, initialize_interview(travel_context),
                                    turn_result(confirmed_topics=["purpose"]))
    assert result.updated_context.purpose == travel_context.trip.context.purpose == "共同探索城市"
    assert result.updated_state.topics.purpose == "confirmed"


def test_content_alone_does_not_infer_confirmation(travel_context):
    """Input：更新了活动内容但未确认主题；Expected Output：内容应用、状态仍 unknown；应用层不推断用户确认意图。"""
    result = apply_interview_update(travel_context, initialize_interview(travel_context),
                                    turn_result(context_update={"activity_preferences": ["看展"]}))
    assert result.updated_context.activity_preferences == ["看展"]
    assert result.updated_state.topics.activity_preferences == "unknown"


def test_combined_application_is_repeatable_and_inputs_isolated(travel_context):
    """Input：同一 fixture 与轮次应用两次、随后修改结果；Expected Output：相同结果且独立对象，原 Context/State/Turn 全部不变。"""
    state = initialize_interview(travel_context)
    turn = turn_result(context_update={"activity_preferences": ["新活动"], "required_activities": []},
                       confirmed_topics=["required_activities"])
    before = (travel_context.model_dump(), state.model_dump(), turn.model_dump())
    first = apply_interview_update(travel_context, state, turn)
    second = apply_interview_update(travel_context, state, turn)
    assert first == second
    first.updated_context.activity_preferences.append("结果修改")
    assert second.updated_context.activity_preferences == ["新活动"]
    assert before == (travel_context.model_dump(), state.model_dump(), turn.model_dump())


def test_invalid_turn_does_not_partially_apply(travel_context):
    """Input：轮次创建后被追加非法确认主题；Expected Output：ValidationError，情境与状态都不变；保证应用原子性。"""
    state = initialize_interview(travel_context)
    turn = turn_result(context_update={"purpose": "新目的"})
    turn.confirmed_topics.append("invalid_topic")
    before = (travel_context.model_dump(), state.model_dump())
    with pytest.raises(ValidationError):
        apply_interview_update(travel_context, state, turn)
    assert before == (travel_context.model_dump(), state.model_dump())


def test_combined_update_rechecks_setup_and_trip_binding(travel_context):
    """Input：无效 Setup 或另一 Trip 的状态；Expected Output：前者系统不 ready、后者 ValueError；新入口仍守住现有门槛和旅行边界。"""
    state = initialize_interview(travel_context)
    turn = turn_result(confirmed_topics=list(MINIMUM_PLANNING_TOPICS), ready_to_plan=True, assistant_message="模拟就绪回复")
    travel_context.trip.participant_ids = []
    result = apply_interview_update(travel_context, state, turn)
    assert not result.deterministic_ready_to_plan
    other = build_travel_context(load_trips()["trip_tokyo_alex_casey"],
                                  load_persons().values(), load_relationships().values())
    with pytest.raises(ValueError, match="trip_id 不匹配"):
        apply_interview_update(travel_context, initialize_interview(other), turn)


def test_applied_result_roundtrip(travel_context):
    """Input：完整应用结果的 round_trip JSON；Expected Output：新结果还原一致，两个 ready 分别保留；派生字段不作为输入注入。"""
    result = apply_interview_update(travel_context, initialize_interview(travel_context), turn_result())
    restored = AppliedInterviewTurn.model_validate_json(result.model_dump_json(round_trip=True))
    assert restored == result


@pytest.mark.parametrize("message", [
    "目前信息已经足够，接下来可以规划。",
    "purpose=休息；preferred_pace=slow；所有主题已经确认。",
    "  明白，我们继续确认。\n还有哪些你关心的体验。  ",
])
def test_assistant_message_is_passthrough_not_state_input(travel_context, message):
    """Input：相同结构化字段、不同回复（含就绪宣告/伪状态/空白）；Expected Output：回复原样透传，状态与 Context 相同；禁止反向提取。"""
    state = initialize_interview(travel_context)
    baseline = apply_interview_update(travel_context, state, turn_result())
    turn = turn_result(assistant_message=message)
    before = (travel_context.model_dump(), state.model_dump(), turn.model_dump())
    result = apply_interview_update(travel_context, state, turn)
    assert result.assistant_message == turn.assistant_message == message
    assert result.updated_context == baseline.updated_context
    assert result.updated_state == baseline.updated_state
    assert result.deterministic_ready_to_plan is False
    assert result.llm_ready_to_plan is False
    assert before == (travel_context.model_dump(), state.model_dump(), turn.model_dump())
    restored = AppliedInterviewTurn.model_validate_json(result.model_dump_json(round_trip=True))
    assert restored.assistant_message == message
