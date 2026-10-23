"""验证用户输入字段边界与现有内部模型一致的校验规则。"""

from datetime import date, datetime
from decimal import Decimal
import json

import pytest
from pydantic import ValidationError

from life_journey.schemas import (
    PersonCreate, RelationshipCreate, TripBudget, TripCreate,
)


def relationship_input(**changes):
    """构造用户明确选择的关系输入，不要求人物集合存在。"""
    return {"person_a_id": "a", "person_b_id": "b", "relationship_type": "friend", **changes}


def trip_input(**changes):
    """构造历史 Trip Setup，避免依赖当前日期或外部查询。"""
    return {
        "participant_ids": ["a"], "destination": "东京",
        "start_date": date(2020, 1, 1), "end_date": date(2020, 1, 3),
        "budget": {"max_amount": Decimal("3000.25"), "currency": "AUD"},
        **changes,
    }


def test_person_create_defaults_and_normalization():
    """Input：带空白姓名及完整偏好；Expected Output：文本标准化、字段保留、默认独立；验证人物输入无需 ID。"""
    first = PersonCreate(name=" 小林 ", interests=[" 看展 "], dislikes=[" 人群 "],
                         food_preferences=[" 当地菜 "], preferred_pace="fast", mbti=" INFP ")
    assert first.model_dump() == {
        "name": "小林", "interests": ["看展"], "dislikes": ["人群"],
        "food_preferences": ["当地菜"], "preferred_pace": "fast", "mbti": "INFP", "gender": None,
    }
    minimal, another = PersonCreate(name="小林"), PersonCreate(name="小周")
    assert minimal.mbti is minimal.preferred_pace is None
    assert minimal.interests == minimal.dislikes == minimal.food_preferences == []
    for field in ("interests", "dislikes", "food_preferences"):
        getattr(minimal, field).append("看展")
        assert getattr(another, field) == []
    assert PersonCreate.model_validate_json(first.model_dump_json()) == first


@pytest.mark.parametrize("data", [
    {}, {"name": ""}, {"name": "  "}, {"name": 1}, {"name": None},
    {"name": "小林", "person_id": "manual"}, {"name": "小林", "unknown": "value"},
])
def test_person_create_required_and_unknown_fields(data):
    """Input：缺姓名、非法姓名、手动 ID 或未知字段；Expected Output：ValidationError；拒绝系统字段和无效用户输入。"""
    with pytest.raises(ValidationError):
        PersonCreate(**data)


@pytest.mark.parametrize("field", ["interests", "dislikes", "food_preferences"])
@pytest.mark.parametrize("value", [[""], ["  "], [1], [True], [None], "看展", ("看展",), None])
def test_person_create_preference_validation(field, value):
    """Input：非法偏好项或非列表容器；Expected Output：ValidationError；保持 Person 的严格非空列表语义。"""
    with pytest.raises(ValidationError):
        PersonCreate(name="小林", **{field: value})


@pytest.mark.parametrize("pace", ["slow", "moderate", "fast", None])
def test_person_create_pace(pace):
    """Input：所有合法节奏及未知值；Expected Output：原值保存；验证用户输入沿用既有节奏枚举。"""
    assert PersonCreate(name="小林", preferred_pace=pace).preferred_pace == pace


@pytest.mark.parametrize("pace", ["medium", "", 1, True])
def test_person_create_invalid_pace(pace):
    """Input：非法节奏字符串或非字符串；Expected Output：ValidationError；拒绝隐式节奏转换。"""
    with pytest.raises(ValidationError):
        PersonCreate(name="小林", preferred_pace=pace)


@pytest.mark.parametrize("mbti", [
    "ISTJ", "ISFJ", "INFJ", "INTJ", "ISTP", "ISFP", "INFP", "INTP",
    "ESTP", "ESFP", "ENFP", "ENTP", "ESTJ", "ESFJ", "ENFJ", "ENTJ", None,
])
def test_person_create_mbti(mbti):
    """Input：16 种明确类型或 None；Expected Output：只保留自述，偏好仍为空；不从 MBTI 生成偏好。"""
    person = PersonCreate(name="小林", mbti=mbti)
    assert person.mbti == mbti
    assert person.interests == person.dislikes == person.food_preferences == []
    assert person.preferred_pace is None


@pytest.mark.parametrize("mbti", ["", " ", "infp", "INFP-A", "XXXX", 1, True])
def test_person_create_invalid_mbti(mbti):
    """Input：空白、小写、扩展标签或错误类型；Expected Output：ValidationError；不猜测 MBTI。"""
    with pytest.raises(ValidationError):
        PersonCreate(name="小林", mbti=mbti)


@pytest.mark.parametrize("kind", ["spouse", "partner", "friend", "family", "sibling", "colleague", "other"])
def test_relationship_create_types_and_normalization(kind):
    """Input：每种合法关系与空白 ID/偏好；Expected Output：标准化并保留中性类型、JSON 可还原；不要求关系 ID。"""
    data = RelationshipCreate(**relationship_input(
        person_a_id=" a ", person_b_id=" b ", relationship_type=kind,
        shared_travel_preferences=[" 一起看展 "], preferred_pace_together="slow",
    ))
    assert (data.person_a_id, data.person_b_id, data.relationship_type) == ("a", "b", kind)
    assert data.shared_travel_preferences == ["一起看展"]
    assert data.preferred_pace_together == "slow"
    assert RelationshipCreate.model_validate_json(data.model_dump_json()) == data


@pytest.mark.parametrize("changes", [
    {"relationship_id": "manual"}, {"unknown": 1},
    {"person_b_id": " a "}, {"person_a_id": ""}, {"person_b_id": " "},
    {"person_a_id": 1}, {"person_b_id": None},
    {"relationship_type": "parent"}, {"relationship_type": "child"},
    {"relationship_type": "unknown"}, {"relationship_type": 1},
    {"shared_travel_preferences": [""]}, {"shared_travel_preferences": [1]},
    {"shared_travel_preferences": "看展"}, {"preferred_pace_together": "medium"},
    {"preferred_pace_together": True},
])
def test_relationship_create_invalid_input(changes):
    """Input：手动关系 ID、未知字段、自身关系或非法用户字段；Expected Output：ValidationError；维持关系校验边界。"""
    with pytest.raises(ValidationError):
        RelationshipCreate(**relationship_input(**changes))


@pytest.mark.parametrize("field", ["person_a_id", "person_b_id", "relationship_type"])
def test_relationship_create_required_fields(field):
    """Input：分别缺少关系必填字段；Expected Output：ValidationError；禁止自动推断人物或关系类型。"""
    data = relationship_input()
    del data[field]
    with pytest.raises(ValidationError):
        RelationshipCreate(**data)


def test_relationship_create_defaults_isolated():
    """Input：两个最小关系输入；Expected Output：共同节奏未知、列表独立；确保没有自动生成共同偏好。"""
    first, second = RelationshipCreate(**relationship_input()), RelationshipCreate(**relationship_input())
    assert first.preferred_pace_together is None
    assert first.shared_travel_preferences == []
    first.shared_travel_preferences.append("看展")
    assert second.shared_travel_preferences == []


@pytest.mark.parametrize("participants", [["a"], [" b ", " a "]])
def test_trip_create_valid_setup_and_roundtrip(participants):
    """Input：单人/多人历史旅行及结构化预算；Expected Output：标准化、顺序保留且 JSON 还原一致；不包含情境和系统 ID。"""
    trip = TripCreate(**trip_input(participant_ids=participants))
    assert trip.participant_ids == [value.strip() for value in participants]
    assert trip.budget == TripBudget(max_amount=Decimal("3000.25"), currency="AUD")
    assert set(trip.model_dump()) == {"participant_ids", "destination", "start_date", "end_date", "budget"}
    assert TripCreate.model_validate_json(trip.model_dump_json()) == trip


@pytest.mark.parametrize("field", ["participant_ids", "destination", "start_date", "end_date", "budget"])
def test_trip_create_required_fields(field):
    """Input：分别缺少每个 Setup 字段；Expected Output：ValidationError；输入不得缺少基础信息。"""
    data = trip_input()
    del data[field]
    with pytest.raises(ValidationError):
        TripCreate(**data)


@pytest.mark.parametrize("changes", [
    {"trip_id": "manual"}, {"context": {}}, {"context": None},
    {"purpose": "纪念日"}, {"unknown": 1}, {"destination": ""},
    {"destination": " "}, {"destination": 1}, {"destination": None},
])
def test_trip_create_forbidden_fields_and_text(changes):
    """Input：系统 ID、情境、未知字段或非法目的地；Expected Output：ValidationError；明确 Setup 的用户输入边界。"""
    with pytest.raises(ValidationError):
        TripCreate(**trip_input(**changes))


@pytest.mark.parametrize("participants", [[], [""], [" "], [1], [True], [None],
    ["a", "a"], ["a", " a "], "a", ("a",), None])
def test_trip_create_invalid_participants(participants):
    """Input：空列表、错误类型、空白或重复 ID；Expected Output：ValidationError；不静默去重或转换。"""
    with pytest.raises(ValidationError):
        TripCreate(**trip_input(participant_ids=participants))


def test_trip_create_date_order():
    """Input：历史同日与反向日期；Expected Output：同日成功、反向报错；只做顺序检查，不依赖当前日期。"""
    trip = TripCreate(**trip_input(end_date=date(2020, 1, 1)))
    assert trip.start_date == trip.end_date
    with pytest.raises(ValidationError):
        TripCreate(**trip_input(end_date=date(2019, 12, 31)))


@pytest.mark.parametrize("field", ["start_date", "end_date"])
@pytest.mark.parametrize("value", ["2020-01-01", 1577836800, datetime(2020, 1, 1), None])
def test_trip_create_strict_python_dates(field, value):
    """Input：Python 文本、时间戳、datetime 或 None；Expected Output：ValidationError；Python 输入沿用严格 date 类型。"""
    with pytest.raises(ValidationError):
        TripCreate(**trip_input(**{field: value}))


@pytest.mark.parametrize("value", ["2020-02-30", "2020-01-01T00:00:00", 1577836800, None])
def test_trip_create_invalid_json_dates(value):
    """Input：JSON 中错误日期、时间文本、时间戳或 null；Expected Output：ValidationError；确保 JSON 日期契约一致。"""
    payload = TripCreate(**trip_input()).model_dump(mode="json")
    payload["start_date"] = value
    with pytest.raises(ValidationError):
        TripCreate.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize("budget", [
    None, {}, {"currency": "AUD"},
    {"max_amount": Decimal("3000")},
    {"currency": "AUD", "max_amount": Decimal("0")},
    {"currency": "AUD", "min_amount": Decimal("-1")},
    {"currency": "AUD", "max_amount": Decimal("NaN")},
    {"currency": "AUD", "max_amount": Decimal("Infinity")},
    {"currency": "AUD", "min_amount": Decimal("4000"), "max_amount": Decimal("3000")},
    {"currency": "AUD", "max_amount": 3000},
    {"currency": "AUD", "max_amount": "3000"},
    {"currency": "aud", "max_amount": Decimal("3000")},
    {"currency": "AU", "max_amount": Decimal("3000")},
    {"currency": "AUD", "max_amount": Decimal("3000"), "hotel": 1},
])
def test_trip_create_budget_validation(budget):
    """Input：缺失金额/币种、非法金额、反向区间、错误类型或未知拆分；Expected Output：ValidationError；复用预算规则。"""
    with pytest.raises(ValidationError):
        TripCreate(**trip_input(budget=budget))


@pytest.mark.parametrize("bounds", [
    {"min_amount": Decimal("2000")}, {"max_amount": Decimal("3000")},
    {"min_amount": Decimal("2000"), "max_amount": Decimal("3000")},
    {"min_amount": Decimal("3000"), "max_amount": Decimal("3000")},
])
def test_trip_create_valid_budget_ranges(bounds):
    """Input：仅下限、仅上限、区间或相等预算；Expected Output：成功并保留边界；输入模型不收紧合法预算组合。"""
    trip = TripCreate(**trip_input(budget={"currency": "AUD", **bounds}))
    for field, value in bounds.items():
        assert getattr(trip.budget, field) == value
