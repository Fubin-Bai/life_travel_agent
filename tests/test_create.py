"""验证应用创建入口的 ID、数据保留与输入隔离。"""

from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from life_journey.application import create_person, create_relationship, create_trip
from life_journey.schemas import (
    Person, PersonCreate, Relationship, RelationshipCreate,
    Trip, TripContext, TripCreate,
)


@pytest.fixture
def person_input():
    """提供包含全部用户字段的人物输入，用于校验数据保留。"""
    return PersonCreate(name="小林", interests=["看展"], dislikes=["拥挤"],
                        food_preferences=["当地菜"], preferred_pace="fast", mbti="INFP")


@pytest.fixture
def relationship_input():
    """提供包含共同旅行偏好的关系输入，不依赖外部人物数据。"""
    return RelationshipCreate(person_a_id="a", person_b_id="b", relationship_type="partner",
                              shared_travel_preferences=["看展"], preferred_pace_together="slow")


@pytest.fixture
def trip_input():
    """提供日期与精确预算均已校验的初始 Setup。"""
    return TripCreate(participant_ids=["a", "b"], destination="东京",
                      start_date=date(2020, 1, 1), end_date=date(2020, 1, 3),
                      budget={"min_amount": Decimal("2000.10"),
                              "max_amount": Decimal("3000.25"), "currency": "AUD"})


@pytest.mark.parametrize("fixture_name,factory,domain,id_field,prefix", [
    ("person_input", create_person, Person, "person_id", "person"),
    ("relationship_input", create_relationship, Relationship, "relationship_id", "relationship"),
    ("trip_input", create_trip, Trip, "trip_id", "trip"),
])
def test_create_ids_data_preservation_and_roundtrip(request, fixture_name, factory, domain, id_field, prefix):
    """Input：三种完整 Create 输入各调用两次；Expected Output：不同合法 UUID4、原字段保留、输入不变且 JSON 还原一致。"""
    data = request.getfixturevalue(fixture_name)
    before = data.model_dump(mode="python")
    first, second = factory(data), factory(data)
    assert isinstance(first, domain) and isinstance(second, domain)
    first_id, second_id = getattr(first, id_field), getattr(second, id_field)
    assert first_id != second_id
    for value in (first_id, second_id):
        assert value.startswith(prefix + "_")
        parsed = UUID(value.removeprefix(prefix + "_"))
        assert parsed.version == 4
        assert str(parsed) == value.removeprefix(prefix + "_")
    assert data.model_dump(mode="python") == before
    for result in (first, second):
        for field, value in before.items():
            assert result.model_dump(mode="python")[field] == value
        assert domain.model_validate_json(result.model_dump_json()) == result


def test_trip_gets_fresh_empty_context(trip_input):
    """Input：相同 Setup 创建两次；Expected Output：各有空情境、修改互不影响；情境不由用户输入或自动提取。"""
    first, second = create_trip(trip_input), create_trip(trip_input)
    assert first.context == second.context == TripContext()
    first.context.required_activities.append("看展")
    assert second.context.required_activities == []
    assert "context" not in trip_input.model_dump()


def test_created_person_does_not_share_input_lists(person_input):
    """Input：人物 Create 创建内部对象后双向修改列表；Expected Output：输入和结果互不改变；避免列表共享副作用。"""
    person = create_person(person_input)
    for field in ("interests", "dislikes", "food_preferences"):
        original = list(getattr(person_input, field))
        getattr(person, field).append("结果新增")
        assert getattr(person_input, field) == original
        getattr(person_input, field).append("输入新增")
        assert getattr(person, field) == original + ["结果新增"]


def test_created_relationship_does_not_share_input_lists(relationship_input):
    """Input：关系创建后修改共同偏好；Expected Output：输入与结果隔离；不回写用户数据。"""
    result = create_relationship(relationship_input)
    result.shared_travel_preferences.append("结果新增")
    assert relationship_input.shared_travel_preferences == ["看展"]
    relationship_input.shared_travel_preferences.append("输入新增")
    assert result.shared_travel_preferences == ["看展", "结果新增"]


def test_created_trip_does_not_share_nested_input(trip_input):
    """Input：旅行创建后双向修改参与者与预算；Expected Output：嵌套预算和列表隔离；保护原 Setup。"""
    result = create_trip(trip_input)
    result.participant_ids.append("c")
    result.budget.max_amount = Decimal("4000")
    assert trip_input.participant_ids == ["a", "b"]
    assert trip_input.budget.max_amount == Decimal("3000.25")
    trip_input.participant_ids.append("d")
    trip_input.budget.min_amount = Decimal("1000")
    assert result.participant_ids == ["a", "b", "c"]
    assert result.budget.min_amount == Decimal("2000.10")


@pytest.mark.parametrize("factory", [create_person, create_relationship, create_trip])
def test_factories_require_validated_create_models(factory):
    """Input：未经校验的普通字典；Expected Output：TypeError；创建入口只接收指定 Create 模型而非解析原始输入。"""
    with pytest.raises(TypeError, match="需要已校验"):
        factory({})


def test_creation_from_json_and_deferred_reference_queries():
    """Input：JSON 输入串经 Create 校验；Expected Output：完整内部对象，未知人物 ID 仍保留；验证分层且不越界查询。"""
    person = create_person(PersonCreate.model_validate_json('{"name":"小林","mbti":"INFP"}'))
    relationship = create_relationship(RelationshipCreate.model_validate_json(
        '{"person_a_id":"unknown_a","person_b_id":"unknown_b","relationship_type":"family"}'
    ))
    trip = create_trip(TripCreate.model_validate_json(
        '{"participant_ids":["unknown_a"],"destination":"东京",'
        '"start_date":"2020-01-01","end_date":"2020-01-01",'
        '"budget":{"max_amount":"3000.25","currency":"AUD"}}'
    ))
    assert person.mbti == "INFP" and person.interests == []
    assert relationship.relationship_type == "family"
    assert trip.participant_ids == ["unknown_a"]
    assert trip.budget.max_amount == Decimal("3000.25")
    assert trip.context == TripContext()


def test_domain_validation_is_not_bypassed(relationship_input):
    """Input：已校验对象随后被改为自身关系；Expected Output：创建时内部模型再次报 ValidationError；不绕过领域校验。"""
    relationship_input.person_b_id = relationship_input.person_a_id
    with pytest.raises(ValidationError):
        create_relationship(relationship_input)
