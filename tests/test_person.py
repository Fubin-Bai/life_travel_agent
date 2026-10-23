import pytest
from pydantic import ValidationError

from life_journey.schemas import Person


def test_minimal_person_and_independent_defaults():
    """Input：两个最小人物；Expected Output：未知偏好、MBTI 为 None，列表互不影响；验证默认值隔离。"""
    first = Person(person_id="a", name="Alex")
    second = Person(person_id="b", name="Alex")
    assert first.preferred_pace is None
    assert first.mbti is None
    assert first.interests == first.dislikes == first.food_preferences == []
    for field in ("interests", "dislikes", "food_preferences"):
        getattr(first, field).append("coffee")
        assert getattr(second, field) == []


@pytest.mark.parametrize("field", ["person_id", "name"])
def test_required_fields(field):
    """Input：分别缺少 ID 或姓名；Expected Output：ValidationError；验证必填字段。"""
    data = {"person_id": "a", "name": "Alex"}
    del data[field]
    with pytest.raises(ValidationError):
        Person(**data)


@pytest.mark.parametrize("field", ["person_id", "name", "interests", "dislikes", "food_preferences"])
@pytest.mark.parametrize("value", ["", "  ", 42, None])
def test_nonempty_strings_and_types(field, value):
    """Input：空白或非字符串字段及列表项；Expected Output：ValidationError；验证文本和类型边界。"""
    data = {"person_id": "a", "name": "Alex"}
    data[field] = [value] if field in ("interests", "dislikes", "food_preferences") else value
    with pytest.raises(ValidationError):
        Person(**data)


@pytest.mark.parametrize("field", ["interests", "dislikes", "food_preferences"])
def test_lists_required(field):
    """Input：用字符串替代偏好列表；Expected Output：ValidationError；防止隐式容器转换。"""
    with pytest.raises(ValidationError):
        Person(person_id="a", name="Alex", **{field: "coffee"})


@pytest.mark.parametrize("pace", ["slow", "moderate", "fast", None])
def test_pace_and_json_roundtrip(pace):
    """Input：各合法节奏和带空白字段；Expected Output：文本标准化、JSON 还原一致；验证已有数据契约。"""
    person = Person(person_id=" a ", name=" 小林 ", interests=[" coffee "],
                    dislikes=["crowds"], food_preferences=["local food"], preferred_pace=pace)
    assert person.person_id == "a"
    assert person.name == "小林"
    assert person.interests == ["coffee"]
    assert Person.model_validate_json(person.model_dump_json()) == person


@pytest.mark.parametrize("extra", [{"preferred_pace": "medium"}, {"preferred_pace": 1},
                                   {"dietary_preferences": []}, {"shared_travel_preferences": []}])
def test_invalid_pace_and_unknown_fields(extra):
    """Input：非法节奏或未知字段；Expected Output：ValidationError；防止错误字段被静默接受。"""
    with pytest.raises(ValidationError):
        Person(person_id="a", name="Alex", **extra)


@pytest.mark.parametrize("mbti", [
    "ISTJ", "ISFJ", "INFJ", "INTJ", "ISTP", "ISFP", "INFP", "INTP",
    "ESTP", "ESFP", "ENFP", "ENTP", "ESTJ", "ESFJ", "ENFJ", "ENTJ",
])
def test_all_standard_mbti_types(mbti):
    """Input：用户明确提供的 16 种类型；Expected Output：原值保存且 JSON 还原一致；验证完整枚举。"""
    person = Person(person_id="a", name="小林", mbti=mbti)
    assert person.mbti == mbti
    assert Person.model_validate_json(person.model_dump_json()) == person


@pytest.mark.parametrize("mbti", ["", "  ", "infp", "INFP-A", "XXXX", 1, True, ["INFP"]])
def test_invalid_mbti(mbti):
    """Input：空白、小写、扩展标签或非字符串；Expected Output：ValidationError；不猜测或纠正 MBTI。"""
    with pytest.raises(ValidationError):
        Person(person_id="a", name="小林", mbti=mbti)


def test_mbti_unknown_normalized_and_independent_of_preferences():
    """Input：未提供 MBTI 的明确偏好和带空白的自述类型；Expected Output：不推断类型、不生成或覆盖偏好。"""
    unknown = Person(person_id="a", name="小林", interests=["徒步"], preferred_pace="fast")
    assert unknown.mbti is None
    assert Person.model_validate_json(unknown.model_dump_json()) == unknown
    described = Person(person_id="a", name="小林", mbti=" INFP ", interests=["徒步"], preferred_pace="fast")
    assert described.mbti == "INFP"
    assert described.interests == unknown.interests
    assert described.preferred_pace == unknown.preferred_pace
    empty = Person(person_id="b", name="小周", mbti="ENTJ")
    assert empty.interests == empty.dislikes == empty.food_preferences == []
    assert empty.preferred_pace is None
