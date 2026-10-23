import pytest
from pydantic import ValidationError

from life_journey.schemas import Person, Relationship


def relationship_data(**changes):
    return dict(relationship_id="r", person_a_id="a", person_b_id="b",
                relationship_type="friend", **changes)


@pytest.mark.parametrize("kind", ["spouse", "partner", "friend", "family", "sibling", "colleague", "other"])
def test_neutral_types_and_json_roundtrip(kind):
    """Input：各合法中性关系及交换后的 A/B；Expected Output：类型不变且 JSON 还原一致；验证无方向语义。"""
    data = relationship_data()
    data["relationship_type"] = kind
    relationship = Relationship(**data)
    assert relationship.relationship_type == kind
    assert relationship.preferred_pace_together is None
    assert relationship.shared_travel_preferences == []
    assert Relationship.model_validate_json(relationship.model_dump_json()) == relationship
    reverse = Relationship(**{**data, "person_a_id": "b", "person_b_id": "a"})
    assert reverse.relationship_type == relationship.relationship_type


@pytest.mark.parametrize("field", ["relationship_id", "person_a_id", "person_b_id", "relationship_type"])
def test_required_fields(field):
    """Input：分别缺少必填关系字段；Expected Output：ValidationError；验证必填边界。"""
    data = relationship_data()
    del data[field]
    with pytest.raises(ValidationError):
        Relationship(**data)


@pytest.mark.parametrize("field", ["relationship_id", "person_a_id", "person_b_id", "shared_travel_preferences"])
@pytest.mark.parametrize("value", ["", "  ", 42, None])
def test_nonempty_strings_and_types(field, value):
    """Input：空白或非字符串 ID/共同偏好项；Expected Output：ValidationError；验证严格文本校验。"""
    data = relationship_data()
    data[field] = [value] if field == "shared_travel_preferences" else value
    with pytest.raises(ValidationError):
        Relationship(**data)


@pytest.mark.parametrize("changes", [
    {"person_b_id": " a "}, {"relationship_type": "parent"},
    {"relationship_type": "child"}, {"relationship_type": 1},
    {"preferred_pace_together": "medium"}, {"preferred_pace_together": 1},
    {"shared_travel_preferences": "coffee"}, {"shared_interests": []},
    {"interests": []},
])
def test_invalid_relationships(changes):
    """Input：自身关系、方向角色、非法节奏、错误容器或未知字段；Expected Output：ValidationError；防止非法数据进入。"""
    with pytest.raises(ValidationError):
        Relationship(**{**relationship_data(), **changes})


@pytest.mark.parametrize("pace", ["slow", "moderate", "fast"])
def test_preferences_normalization_and_roundtrip(pace):
    """Input：带空白 ID/偏好和各合法节奏；Expected Output：去空白且 JSON 还原一致；验证序列化契约。"""
    relationship = Relationship(**{**relationship_data(), "relationship_id": " r ",
        "person_a_id": " a ", "person_b_id": " b ",
        "shared_travel_preferences": [" local food "], "preferred_pace_together": pace})
    assert relationship.relationship_id == "r"
    assert (relationship.person_a_id, relationship.person_b_id) == ("a", "b")
    assert relationship.shared_travel_preferences == ["local food"]
    assert Relationship.model_validate_json(relationship.model_dump_json()) == relationship


def test_person_and_relationship_preferences_stay_separate():
    """Input：两个人的独立偏好与空关系；Expected Output：不自动计算交集，关系修改不影响个人或其他实例；验证偏好分离。"""
    first = Person(person_id="a", name="A", interests=["hiking"], preferred_pace="fast")
    second = Person(person_id="b", name="B", interests=["hiking"], preferred_pace="moderate")
    relationship = Relationship(**relationship_data())
    assert relationship.shared_travel_preferences == []
    relationship.shared_travel_preferences.append("cafes together")
    relationship.preferred_pace_together = "slow"
    assert first.interests == second.interests == ["hiking"]
    assert (first.preferred_pace, second.preferred_pace) == ("fast", "moderate")
    another = Relationship(**relationship_data())
    assert another.shared_travel_preferences == []
