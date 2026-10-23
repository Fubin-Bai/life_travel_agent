"""使用固定 V0 场景验证选择边界、引用错误与数据隔离。"""

import pytest

from fixtures import load_persons, load_relationships, load_trips
from life_journey.application import build_travel_context
from life_journey.schemas import Person, Relationship, TravelContext, Trip


@pytest.mark.parametrize("trip_id,person_ids,relationship_ids", [
    ("trip_tokyo_alex_bella", ["person_alex", "person_bella"], ["relationship_alex_bella"]),
    ("trip_tokyo_alex_casey", ["person_alex", "person_casey"], ["relationship_alex_casey"]),
    ("trip_tokyo_alex_bella_slow", ["person_alex", "person_bella"], ["relationship_alex_bella"]),
    ("trip_tokyo_alex_bella_fast", ["person_alex", "person_bella"], ["relationship_alex_bella"]),
    ("trip_tokyo_alex_personal_relevance", ["person_alex"], []),
])
def test_all_cases_select_only_current_data(trip_id, person_ids, relationship_ids):
    """Input：A/B/C 五个固定旅行与完整集合；Expected Output：仅目标人物和关系、完整 Trip 原样保留且稳定可序列化；验证选择范围。"""
    persons, relationships = load_persons(), load_relationships()
    trip = load_trips()[trip_id]
    result = build_travel_context(trip, persons.values(), relationships.values())
    assert isinstance(result, TravelContext)
    assert [person.person_id for person in result.participants] == person_ids
    assert [item.relationship_id for item in result.relationships] == relationship_ids
    assert result.trip.model_dump() == trip.model_dump()
    assert result.trip.context.model_dump() == trip.context.model_dump()
    assert set(person_ids) == set(trip.participant_ids)
    assert TravelContext.model_validate_json(result.model_dump_json()) == result
    assert build_travel_context(trip, persons.values(), relationships.values()) == result


def test_preferences_are_separate_and_not_inferred():
    """Input：Alex/Bella 长期偏好、明确关系偏好和慢节奏情境；Expected Output：三层原样独立，无 MBTI/关系标签推断。"""
    persons, relationships = load_persons(), load_relationships()
    trip = load_trips()["trip_tokyo_alex_bella_slow"]
    result = build_travel_context(trip, persons.values(), relationships.values())
    assert result.participants == [persons["person_alex"], persons["person_bella"]]
    assert result.relationships == [relationships["relationship_alex_bella"]]
    assert result.participants[0].mbti == "INFP"
    assert result.participants[0].preferred_pace == "fast"
    assert result.relationships[0].preferred_pace_together == "moderate"
    assert result.trip.context.preferred_pace == "slow"


def test_selection_preserves_explicit_input_order():
    """Input：三人 Trip、乱序人物集合及反序关系集合；Expected Output：人物按 Trip、关系按输入顺序；不依赖字典顺序或隐式排序。"""
    persons, relationships = load_persons(), load_relationships()
    data = load_trips()["trip_tokyo_alex_bella"].model_dump(mode="python")
    data["participant_ids"] = ["person_casey", "person_alex", "person_bella"]
    trip = Trip(**data)
    result = build_travel_context(trip, reversed(list(persons.values())), reversed(list(relationships.values())))
    assert [item.person_id for item in result.participants] == data["participant_ids"]
    assert [item.relationship_id for item in result.relationships] == list(reversed(relationships))


@pytest.mark.parametrize("missing_id", ["person_alex", "person_bella"])
def test_missing_participant_fails(missing_id):
    """Input：缺少任一 Trip 参与者的人物集合；Expected Output：含缺失 ID 的 ValueError；禁止猜测、自动补齐或遗漏人物。"""
    persons = load_persons()
    del persons[missing_id]
    with pytest.raises(ValueError, match=f"找不到 Trip 参与者: {missing_id}"):
        build_travel_context(load_trips()["trip_tokyo_alex_bella"], persons.values(), [])


@pytest.mark.parametrize("duplicate_id", ["person_alex", "person_casey"])
def test_duplicate_person_id_fails_globally(duplicate_id):
    """Input：重复的参与者或未参与者 ID；Expected Output：明确 ValueError；整个 Person 集合不允许 ID 歧义。"""
    persons = load_persons()
    duplicate = Person(**persons[duplicate_id].model_dump())
    with pytest.raises(ValueError, match=f"重复 person_id: {duplicate_id}"):
        build_travel_context(load_trips()["trip_tokyo_alex_bella"], [*persons.values(), duplicate], [])


@pytest.mark.parametrize("endpoints", [
    ("person_alex", "person_missing"), ("person_missing", "person_bella"),
])
def test_touching_relationship_missing_reference_fails(endpoints):
    """Input：关系一端参与本次旅行、另一端不存在；Expected Output：含关系和缺失人物 ID 的 ValueError；不静默丢弃相关错误。"""
    invalid = Relationship(relationship_id="relationship_broken", person_a_id=endpoints[0],
                           person_b_id=endpoints[1], relationship_type="friend")
    with pytest.raises(ValueError, match="Relationship relationship_broken 引用不存在的 Person: person_missing"):
        build_travel_context(load_trips()["trip_tokyo_alex_bella"], load_persons().values(), [invalid])


def test_unrelated_dangling_and_duplicate_relationships_are_ignored():
    """Input：两端均未参加的悬空关系及其重复副本；Expected Output：无错误、不输出；无关集合问题不阻塞当前旅行。"""
    persons, relationships = load_persons(), load_relationships()
    unrelated = Relationship(relationship_id="relationship_unrelated", person_a_id="person_casey",
                              person_b_id="person_missing", relationship_type="friend")
    both_missing = Relationship(relationship_id="relationship_both_missing", person_a_id="missing_a",
                                 person_b_id="missing_b", relationship_type="family")
    result = build_travel_context(load_trips()["trip_tokyo_alex_bella"], persons.values(),
                                  [*relationships.values(), unrelated, unrelated, both_missing])
    assert [item.relationship_id for item in result.relationships] == ["relationship_alex_bella"]
    assert [item.person_id for item in result.participants] == ["person_alex", "person_bella"]


def test_duplicate_selected_relationship_id_fails():
    """Input：两条入选关系 ID 相同但类型不同；Expected Output：明确重复 ID 错误；不覆盖或静默去重。"""
    first = load_relationships()["relationship_alex_bella"]
    second = Relationship(**{**first.model_dump(), "relationship_type": "colleague"})
    with pytest.raises(ValueError, match="重复 relationship_id: relationship_alex_bella"):
        build_travel_context(load_trips()["trip_tokyo_alex_bella"], load_persons().values(), [first, second])


@pytest.mark.parametrize("reverse", [False, True])
def test_duplicate_pair_and_type_fails(reverse):
    """Input：不同关系 ID、同人物对与类型（含 A/B 反转）；Expected Output：重复关系 ValueError；保持无方向语义。"""
    first = load_relationships()["relationship_alex_bella"]
    data = {**first.model_dump(), "relationship_id": "relationship_duplicate"}
    if reverse:
        data["person_a_id"], data["person_b_id"] = data["person_b_id"], data["person_a_id"]
    with pytest.raises(ValueError, match="重复关系（人物对与类型）"):
        build_travel_context(load_trips()["trip_tokyo_alex_bella"], load_persons().values(), [first, Relationship(**data)])


def test_different_explicit_types_for_same_pair_are_preserved():
    """Input：同人物对、不同 ID 与明确关系类型；Expected Output：保留两条；不推断标签冲突或替用户选择关系。"""
    first = load_relationships()["relationship_alex_bella"]
    second = Relationship(**{**first.model_dump(), "relationship_id": "relationship_colleague",
                             "relationship_type": "colleague"})
    result = build_travel_context(load_trips()["trip_tokyo_alex_bella"], load_persons().values(), [first, second])
    assert [item.relationship_id for item in result.relationships] == [first.relationship_id, second.relationship_id]


def test_known_nonparticipant_relationship_does_not_add_person():
    """Input：Alex/Bella Trip 与 Alex/Casey 关系；Expected Output：关系不入选、Casey 不添加，且无关系也能构建；不扩张参与者。"""
    trip = load_trips()["trip_tokyo_alex_bella"]
    result = build_travel_context(trip, load_persons().values(), [load_relationships()["relationship_alex_casey"]])
    assert result.relationships == []
    assert [item.person_id for item in result.participants] == trip.participant_ids


def test_builder_does_not_mutate_and_output_is_independent():
    """Input：原始 fixture 与构建结果双向修改；Expected Output：构建前后输入不变，后续修改互不影响；检查深层数据隔离。"""
    persons, relationships = load_persons(), load_relationships()
    trip = load_trips()["trip_tokyo_alex_bella_slow"]
    before = (
        trip.model_dump(), {key: item.model_dump() for key, item in persons.items()},
        {key: item.model_dump() for key, item in relationships.items()},
    )
    result = build_travel_context(trip, persons.values(), relationships.values())
    assert before == (
        trip.model_dump(), {key: item.model_dump() for key, item in persons.items()},
        {key: item.model_dump() for key, item in relationships.items()},
    )
    result.participants[0].interests.append("结果临时兴趣")
    result.relationships[0].shared_travel_preferences.append("结果临时共同偏好")
    result.trip.participant_ids.append("person_output_only")
    result.trip.budget.currency = "JPY"
    result.trip.context.activity_preferences.append("结果临时偏好")
    assert before == (
        trip.model_dump(), {key: item.model_dump() for key, item in persons.items()},
        {key: item.model_dump() for key, item in relationships.items()},
    )
    snapshot = result.model_dump()
    persons["person_alex"].dislikes.append("输入临时反感")
    relationships["relationship_alex_bella"].shared_travel_preferences.append("输入临时共同偏好")
    trip.context.required_activities.append("输入临时要求")
    trip.budget.currency = "USD"
    assert result.model_dump() == snapshot
