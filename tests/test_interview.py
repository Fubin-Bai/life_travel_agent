"""验证访谈协议、显式确认与确定性最低门槛，不调用 LLM。"""

import json

import pytest
from pydantic import ValidationError

from fixtures import load_persons, load_relationships, load_trips
from life_journey.application import (
    apply_interview_turn, build_travel_context, check_minimum_readiness,
    get_missing_topics, initialize_interview,
)
from life_journey.schemas import (
    InterviewState, InterviewTopics, InterviewTurnResult, TripContextUpdate,
)
from life_journey.schemas.interview import ALL_INTERVIEW_TOPICS, MINIMUM_PLANNING_TOPICS


@pytest.fixture
def travel_context():
    """使用已有非空情境与 MBTI、关系偏好的案例，不将内容存在等同于访谈已确认。"""
    return build_travel_context(
        load_trips()["trip_tokyo_alex_bella_slow"],
        load_persons().values(), load_relationships().values(),
    )


def turn_result(**changes):
    """构造模拟协议值；回复仅为测试数据，不是产品固定回复模板。"""
    return InterviewTurnResult(**{
        "context_update": {}, "confirmed_topics": [], "missing_topics": [],
        "ready_to_plan": False, "assistant_message": "模拟的自然回复", **changes,
    })


def minimum_state(context):
    """显式确认四个主题，避免根据 fixture 的非空内容自动推断。"""
    return apply_interview_turn(context, initialize_interview(context), turn_result(
        confirmed_topics=list(MINIMUM_PLANNING_TOPICS), ready_to_plan=True, assistant_message="模拟就绪回复",
    ))


@pytest.mark.parametrize("trip_id", [
    "trip_tokyo_alex_bella", "trip_tokyo_alex_casey", "trip_tokyo_alex_bella_slow",
    "trip_tokyo_alex_bella_fast", "trip_tokyo_alex_personal_relevance",
])
def test_fixtures_initialize_all_topics_unknown(trip_id):
    """Input：A/B/C 已有 TravelContext；Expected Output：Setup 完整但六主题全 unknown、interviewing；不从偏好或 MBTI 推断确认。"""
    context = build_travel_context(load_trips()[trip_id], load_persons().values(), load_relationships().values())
    state = initialize_interview(context)
    assert state.trip_id == trip_id
    assert state.trip_setup_complete
    assert set(state.topics.model_dump().values()) == {"unknown"}
    assert get_missing_topics(state) == list(ALL_INTERVIEW_TOPICS)
    assert not state.ready_to_plan and state.phase == "interviewing"
    assert not check_minimum_readiness(context, state)


def test_unknown_and_confirmed_empty_list_differ(travel_context):
    """Input：同为空列表、先未知后明确确认没有必去项；Expected Output：只有确认后的主题不再 missing；内容与确认分离。"""
    initial = initialize_interview(travel_context)
    turn = turn_result(context_update={"required_activities": []}, confirmed_topics=["required_activities"])
    updated = apply_interview_turn(travel_context, initial, turn)
    assert travel_context.trip.context.required_activities == []
    assert initial.topics.required_activities == "unknown"
    assert updated.topics.required_activities == "confirmed"
    assert "required_activities" in get_missing_topics(initial)
    assert "required_activities" not in get_missing_topics(updated)
    assert not updated.ready_to_plan


@pytest.mark.parametrize("missing", list(MINIMUM_PLANNING_TOPICS))
def test_each_minimum_topic_blocks_readiness(travel_context, missing):
    """Input：四个最低主题分别缺一个，LLM 却建议 ready；Expected Output：系统仍 interviewing；每项最低条件独立阻塞。"""
    confirmed = [topic for topic in MINIMUM_PLANNING_TOPICS if topic != missing]
    turn = turn_result(confirmed_topics=confirmed, missing_topics=[missing], ready_to_plan=True, assistant_message="模拟就绪回复")
    state = apply_interview_turn(travel_context, initialize_interview(travel_context), turn)
    assert missing in get_missing_topics(state)
    assert not state.ready_to_plan and state.phase == "interviewing"
    assert not check_minimum_readiness(travel_context, state)


def test_minimum_confirmations_ready_with_advisory_topics_unknown(travel_context):
    """Input：只确认四个最低主题；Expected Output：ready_to_plan，两个建议主题仍 missing；推荐项不成为绝对阻塞条件。"""
    state = minimum_state(travel_context)
    assert state.ready_to_plan and state.phase == "ready_to_plan"
    assert check_minimum_readiness(travel_context, state)
    assert get_missing_topics(state) == ["activity_preferences", "special_requirements"]


def test_llm_ready_alone_cannot_advance_state(travel_context):
    """Input：无任何确认，仅 LLM ready=True；Expected Output：系统仍 interviewing；禁止 LLM 越过确定性最低门槛。"""
    state = apply_interview_turn(travel_context, initialize_interview(travel_context),
                                 turn_result(ready_to_plan=True, assistant_message="模拟就绪回复"))
    assert not state.ready_to_plan
    assert state.phase == "interviewing"


def test_missing_and_ready_advice_do_not_override_confirmations(travel_context):
    """Input：已满足最低条件后 LLM 建议不就绪并声称 purpose 缺失；Expected Output：已有确认保留且最低检查通过；建议不反写状态。"""
    state = minimum_state(travel_context)
    updated = apply_interview_turn(travel_context, state, turn_result(missing_topics=["purpose"]))
    assert updated.topics.purpose == "confirmed"
    assert updated.ready_to_plan


@pytest.mark.parametrize("changes", [
    {"destination": None}, {"start_date": None}, {"end_date": None},
    {"budget": None}, {"participant_ids": []},
])
def test_current_setup_is_rechecked_not_cached(travel_context, changes):
    """Input：四主题已确认后使某个必需 Setup 无效；Expected Output：当前最低检查失败、刷新状态回 interviewing；旧快照不能绕过门槛。"""
    state = minimum_state(travel_context)
    for field, value in changes.items():
        setattr(travel_context.trip, field, value)
    assert not check_minimum_readiness(travel_context, state)
    refreshed = apply_interview_turn(travel_context, state, turn_result(ready_to_plan=True, assistant_message="模拟就绪回复"))
    assert not refreshed.trip_setup_complete
    assert not refreshed.ready_to_plan and refreshed.phase == "interviewing"
    assert state.ready_to_plan


def test_update_unset_empty_and_value_survive_serialization():
    """Input：省略字段、明确空列表和具体列表；Expected Output：字段集合与 JSON 载荷均不同；避免传输时将 unset 变成清空。"""
    unset = TripContextUpdate()
    empty = TripContextUpdate(required_activities=[])
    value = TripContextUpdate(required_activities=[" 看展 "])
    assert unset.model_fields_set == set()
    assert empty.model_fields_set == value.model_fields_set == {"required_activities"}
    assert unset.model_dump() == {}
    assert empty.model_dump() == {"required_activities": []}
    assert value.model_dump() == {"required_activities": ["看展"]}
    for update in (unset, empty, value):
        restored = TripContextUpdate.model_validate_json(update.model_dump_json())
        assert restored.model_fields_set == update.model_fields_set
        assert restored.model_dump() == update.model_dump()


@pytest.mark.parametrize("field", ["purpose", "preferred_pace"])
def test_explicit_null_scalar_is_not_unset(field):
    """Input：明确 None 的可空标量与省略字段；Expected Output：前者输出 null，后者不输出；确认由独立状态表示。"""
    explicit = TripContextUpdate(**{field: None})
    assert explicit.model_dump() == {field: None}
    assert field not in TripContextUpdate().model_dump()
    restored = TripContextUpdate.model_validate_json(explicit.model_dump_json())
    assert restored.model_fields_set == {field}


@pytest.mark.parametrize("field", ["activity_preferences", "required_activities", "excluded_activities"])
def test_explicit_null_lists_rejected(field):
    """Input：明确 null 的列表字段；Expected Output：ValidationError；列表没有用 [] 表达，无更新则省略。"""
    with pytest.raises(ValidationError, match="不接受 null"):
        TripContextUpdate(**{field: None})


@pytest.mark.parametrize("data", [
    {"purpose": " "}, {"preferred_pace": "medium"}, {"required_activities": [""]},
    {"excluded_activities": "徒步"}, {"activity_preferences": [1]},
    {"special_requirements": "特殊情况"}, {"destination": "东京"},
])
def test_update_rejects_invalid_or_out_of_scope_fields(data):
    """Input：无效增量或非 TripContext 字段；Expected Output：ValidationError；限制增量协议，不扩展特殊要求存储。"""
    with pytest.raises(ValidationError):
        TripContextUpdate(**data)


def test_turn_nested_update_roundtrip_and_assistant_message():
    """Input：模拟 LLM 自然回复与只更新必去项的轮次；Expected Output：回复保留，嵌套增量序列化不补其他字段；支持未来动态输出。"""
    turn = turn_result(context_update={"required_activities": []}, confirmed_topics=["required_activities"],
                       missing_topics=["purpose"])
    assert turn.assistant_message == "模拟的自然回复"
    payload = json.loads(turn.model_dump_json())
    assert payload["context_update"] == {"required_activities": []}
    restored = InterviewTurnResult.model_validate_json(turn.model_dump_json())
    assert restored == turn
    assert restored.context_update.model_fields_set == {"required_activities"}


@pytest.mark.parametrize("changes", [
    {"assistant_message": None}, {"assistant_message": " "},
    {"confirmed_topics": ["purpose", "purpose"]}, {"missing_topics": ["purpose", "purpose"]},
    {"confirmed_topics": ["purpose"], "missing_topics": ["purpose"]},
    {"confirmed_topics": ["not_a_topic"]}, {"missing_topics": "purpose"},
    {"ready_to_plan": "true"}, {"unknown": "value"},
])
def test_turn_protocol_consistency(changes):
    """Input：空回复、重复/交叠/非法主题、错误类型或未知字段；Expected Output：ValidationError；保持新输出协议明确。"""
    with pytest.raises(ValidationError):
        turn_result(**changes)


def test_ready_turn_does_not_require_question():
    """Input：LLM 建议就绪并给出不含问题的自然回复；Expected Output：协议有效；这不代替后续系统最低检查。"""
    turn = turn_result(ready_to_plan=True, assistant_message="模拟就绪回复")
    assert turn.assistant_message == "模拟就绪回复"


def test_state_and_turn_application_do_not_mutate_inputs(travel_context):
    """Input：部分确认和包含具体增量的轮次；Expected Output：新状态累计确认、所有原输入不变，TripContext 不自动合并。"""
    initial = initialize_interview(travel_context)
    turn = turn_result(context_update={"purpose": "本轮新的明确目的", "excluded_activities": []},
                       confirmed_topics=["purpose", "special_requirements"])
    before = (travel_context.model_dump(), initial.model_dump(), turn.model_dump())
    updated = apply_interview_turn(travel_context, initial, turn)
    assert before == (travel_context.model_dump(), initial.model_dump(), turn.model_dump())
    assert updated.topics.purpose == updated.topics.special_requirements == "confirmed"
    assert initial.topics.purpose == "unknown"
    assert travel_context.trip.context.purpose == "共同探索城市"
    assert "special_requirements" not in travel_context.trip.context.model_dump()
    missing = get_missing_topics(updated)
    missing.clear()
    assert get_missing_topics(updated)
    with pytest.raises(ValidationError):
        updated.topics.purpose = "unknown"


def test_patch_content_alone_does_not_confirm_topics(travel_context):
    """Input：增量有内容但无明确 confirmed_topics；Expected Output：主题保持 unknown；不将提取结果当作用户已确认。"""
    result = apply_interview_turn(travel_context, initialize_interview(travel_context),
                                  turn_result(context_update={"purpose": "明确目的"}))
    assert result.topics.purpose == "unknown"


def test_confirmations_accumulate_idempotently(travel_context):
    """Input：分两轮确认四主题并再次确认同一主题；Expected Output：累计后 ready、重复轮次不撤销；不依赖整段聊天历史。"""
    first = apply_interview_turn(travel_context, initialize_interview(travel_context),
                                 turn_result(confirmed_topics=["purpose", "preferred_pace"]))
    assert not first.ready_to_plan
    turn = turn_result(confirmed_topics=["purpose", "required_activities", "excluded_activities"],
                       ready_to_plan=True, assistant_message="模拟就绪回复")
    final = apply_interview_turn(travel_context, first, turn)
    assert final.ready_to_plan
    assert apply_interview_turn(travel_context, final, turn) == final


def test_state_is_bound_to_trip(travel_context):
    """Input：另一旅行的状态传给当前 Trip；Expected Output：明确 ValueError；防止确认状态跨旅行误用。"""
    other = build_travel_context(load_trips()["trip_tokyo_alex_casey"], load_persons().values(), load_relationships().values())
    state = initialize_interview(other)
    with pytest.raises(ValueError, match="trip_id 不匹配"):
        check_minimum_readiness(travel_context, state)
    with pytest.raises(ValueError, match="trip_id 不匹配"):
        apply_interview_turn(travel_context, state, turn_result())


def test_state_readonly_outputs_and_roundtrip(travel_context):
    """Input：达到最低条件的状态；Expected Output：派生阶段可读，不能注入，round_trip 模式还原一致；避免冗余状态互相矛盾。"""
    state = minimum_state(travel_context)
    assert state.model_dump()["phase"] == "ready_to_plan"
    with pytest.raises(ValidationError):
        InterviewState(trip_id=state.trip_id, ready_to_plan=True)
    with pytest.raises(ValidationError):
        InterviewTopics(purpose="inferred")
    restored = InterviewState.model_validate_json(state.model_dump_json(round_trip=True))
    assert restored == state


def test_assistant_message_is_required():
    """Input：轮次缺少 assistant_message；Expected Output：ValidationError；机器状态更新之外必须同时提供用户可读回复。"""
    data = turn_result().model_dump()
    del data["assistant_message"]
    with pytest.raises(ValidationError):
        InterviewTurnResult(**data)


@pytest.mark.parametrize("message", ["", " ", "\n\t", None, 1, True, []])
def test_assistant_message_requires_nonblank_string(message):
    """Input：空串、纯空白或非字符串回复；Expected Output：ValidationError；禁止无可展示内容或隐式类型转换。"""
    with pytest.raises(ValidationError):
        turn_result(assistant_message=message)


@pytest.mark.parametrize("ready,message", [
    (False, "明白，这次更希望放松。还有一定想安排的体验吗？"),
    (False, "明白，我会结合你明确的节奏继续确认。"),
    (True, "当前理解已经足够，可以交给下一阶段处理。"),
])
def test_assistant_response_supports_continuing_and_ready(ready, message):
    """Input：继续访谈的自然回应/追问和就绪陈述；Expected Output：全部合法，不强制问号；回复动态生成而非固定问句字段。"""
    turn = turn_result(ready_to_plan=ready, assistant_message=message)
    assert turn.assistant_message == message
    assert InterviewTurnResult.model_validate_json(turn.model_dump_json()) == turn


def test_legacy_next_question_is_rejected():
    """Input：新协议轮次额外带旧 next_question；Expected Output：ValidationError，Schema 无旧字段；不保留重复输出接口。"""
    with pytest.raises(ValidationError):
        turn_result(next_question="旧问题")
    assert "next_question" not in InterviewTurnResult.model_fields


@pytest.mark.parametrize("extra", [
    {"assistant_message": ["明白。", "接下来有什么偏好？"]},
    {"acknowledgement_message": "明白。"},
])
def test_single_turn_rejects_split_message_fields(extra):
    """Input：两条回复数组或额外 acknowledgement 字段；Expected Output：ValidationError；仅保留一条完整 assistant_message。"""
    with pytest.raises(ValidationError):
        turn_result(**extra)
