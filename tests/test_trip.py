"""验证旅行 Setup、预算与引用的对象内边界。"""

from datetime import date, datetime
from decimal import Decimal
import json

import pytest
from pydantic import ValidationError

from life_journey.schemas import Person, Relationship, Trip, TripBudget, TripContext


def trip_data(**changes):
    """构造明确的历史旅行输入，避免测试依赖当前日期或真实人物集合。"""
    return {
        "trip_id": "trip_001", "participant_ids": ["a"], "destination": "东京",
        "start_date": date(2020, 1, 1), "end_date": date(2020, 1, 3),
        "budget": {"max_amount": Decimal("3000"), "currency": "AUD"},
        **changes,
    }


@pytest.mark.parametrize("participants", [["a"], ["b", "a"]])
def test_setup_and_empty_context(participants):
    """Input：单人或多人历史旅行；Expected Output：成功且保留顺序、空情境；验证最小 Setup 不要求填写对话字段。"""
    trip = Trip(**trip_data(participant_ids=participants))
    assert trip.participant_ids == participants
    assert trip.context == TripContext()
    assert trip.budget.max_amount == Decimal("3000")


@pytest.mark.parametrize("field", ["trip_id", "participant_ids", "destination", "start_date", "end_date", "budget"])
def test_required_setup_fields(field):
    """Input：分别缺少每项必填 Setup；Expected Output：ValidationError；禁止隐式补全用户尚未提供的基础信息。"""
    data = trip_data()
    del data[field]
    with pytest.raises(ValidationError):
        Trip(**data)


@pytest.mark.parametrize("field", ["trip_id", "destination"])
@pytest.mark.parametrize("value", ["", "  ", 1, True, None])
def test_invalid_setup_text(field, value):
    """Input：空白或非字符串 ID/目的地；Expected Output：ValidationError；验证必填字符串契约。"""
    with pytest.raises(ValidationError):
        Trip(**trip_data(**{field: value}))


@pytest.mark.parametrize("participants", [[], [""], ["  "], [1], [None], [True],
    ["a", "a"], ["a", " a "], "a", ("a",), None])
def test_invalid_participants(participants):
    """Input：空列表、非法项、重复/去空白重复 ID 或非列表；Expected Output：ValidationError；不静默去重或转换。"""
    with pytest.raises(ValidationError):
        Trip(**trip_data(participant_ids=participants))


def test_text_normalization_and_full_json_roundtrip():
    """Input：带空白 Setup、精确金额和完整情境；Expected Output：标准化且 JSON 还原一致；验证日期与 Decimal 精度。"""
    trip = Trip(**trip_data(
        trip_id=" trip_001 ", participant_ids=[" a ", " b "], destination=" 东京 ",
        budget={"min_amount": Decimal("2000.10"), "max_amount": Decimal("3000.25"), "currency": " AUD "},
        context={"purpose": " 纪念日 ", "preferred_pace": "slow",
                 "activity_preferences": ["看展"], "required_activities": ["吃当地菜"],
                 "excluded_activities": ["徒步"]},
    ))
    assert (trip.trip_id, trip.destination, trip.participant_ids) == ("trip_001", "东京", ["a", "b"])
    payload = json.loads(trip.model_dump_json())
    assert payload["start_date"] == "2020-01-01"
    assert payload["budget"]["max_amount"] == "3000.25"
    assert trip.budget.currency == "AUD"
    assert Trip.model_validate_json(trip.model_dump_json()) == trip


def test_same_day_and_reversed_dates():
    """Input：同日起止与反向日期；Expected Output：同日成功、反向报错；验证日历日期顺序。"""
    trip = Trip(**trip_data(end_date=date(2020, 1, 1)))
    assert trip.start_date == trip.end_date
    with pytest.raises(ValidationError):
        Trip(**trip_data(end_date=date(2019, 12, 31)))


@pytest.mark.parametrize("field", ["start_date", "end_date"])
@pytest.mark.parametrize("value", ["2020-01-01", 1577836800, datetime(2020, 1, 1), None])
def test_python_dates_are_strict(field, value):
    """Input：Python 字符串、时间戳、datetime 或 None；Expected Output：ValidationError；Python 输入必须为 date。"""
    with pytest.raises(ValidationError):
        Trip(**trip_data(**{field: value}))


@pytest.mark.parametrize("value", ["2020-02-30", "2020-01-01T00:00:00", 1577836800, None])
def test_invalid_json_dates(value):
    """Input：JSON 中的非法日期、时间文本、时间戳或 null；Expected Output：ValidationError；限制 JSON 日期格式。"""
    payload = Trip(**trip_data()).model_dump(mode="json")
    payload["start_date"] = value
    with pytest.raises(ValidationError):
        Trip.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize("extra", [{"purpose": "纪念日"}, {"preferred_pace": "slow"},
    {"participant_count": 1}, {"context": None}, {"budget": None},
    {"budget": {"max_amount": Decimal("3000"), "currency": "AUD", "hotel": 100}},
    {"context": {"unknown": "value"}}])
def test_invalid_or_unknown_nested_fields(extra):
    """Input：未知字段、错误层级字段或空必需模型；Expected Output：ValidationError；嵌套层级同样拒绝未知字段。"""
    with pytest.raises(ValidationError):
        Trip(**trip_data(**extra))


def test_context_and_participant_lists_are_isolated():
    """Input：共享源列表构造两次旅行；Expected Output：修改不互相影响；验证参与者与默认情境实例隔离。"""
    data = trip_data()
    first, second = Trip(**data), Trip(**data)
    first.participant_ids.append("b")
    first.context.required_activities.append("看展")
    assert second.participant_ids == data["participant_ids"] == ["a"]
    assert second.context.required_activities == []


def test_profile_separation_and_deferred_collection_checks():
    """Input：独立人物关系及两次同 ID、含未知人物的 Trip；Expected Output：可构造且 Profile 不变；明确跨集合检查未实现。"""
    person = Person(person_id="a", name="小林", preferred_pace="fast", mbti="INFP")
    relationship = Relationship(relationship_id="r", person_a_id="a", person_b_id="b", relationship_type="partner")
    before = (person.model_dump(), relationship.model_dump())
    first = Trip(**trip_data(participant_ids=[person.person_id, "unknown"], context={"preferred_pace": "slow"}))
    second = Trip(**trip_data())
    assert first.trip_id == second.trip_id
    assert (person.model_dump(), relationship.model_dump()) == before


@pytest.mark.parametrize("bounds", [
    {"max_amount": Decimal("3000")}, {"min_amount": Decimal("2000")},
    {"min_amount": Decimal("2000"), "max_amount": Decimal("3000")},
    {"min_amount": Decimal("2000"), "max_amount": Decimal("2000")},
])
def test_valid_budget_ranges_and_roundtrip(bounds):
    """Input：仅上限、仅下限、区间或相等边界；Expected Output：成功且 JSON 还原一致；覆盖预算允许的边界组合。"""
    budget = TripBudget(currency="AUD", **bounds)
    for field, value in bounds.items():
        assert getattr(budget, field) == value
    assert TripBudget.model_validate_json(budget.model_dump_json()) == budget


@pytest.mark.parametrize("bounds", [{}, {"min_amount": None, "max_amount": None},
    {"min_amount": Decimal("3001"), "max_amount": Decimal("3000")}])
def test_missing_or_reversed_budget_bounds(bounds):
    """Input：缺少所有金额或下限高于上限；Expected Output：ValidationError；拒绝不完整或倒置预算。"""
    with pytest.raises(ValidationError):
        TripBudget(currency="AUD", **bounds)


@pytest.mark.parametrize("field", ["min_amount", "max_amount"])
@pytest.mark.parametrize("value", [Decimal("0"), Decimal("-1"), Decimal("NaN"),
    Decimal("sNaN"), Decimal("Infinity"), Decimal("-Infinity"), 3000, 3000.0, "3000", True])
def test_invalid_budget_amounts(field, value):
    """Input：零、负数、非有限 Decimal 或非 Decimal 类型；Expected Output：ValidationError；验证严格正有限金额。"""
    with pytest.raises(ValidationError):
        TripBudget(currency="AUD", **{field: value})


@pytest.mark.parametrize("currency", ["", "  ", "aud", "AU", "AUDD", "A1D", "澳元", 123, None])
def test_invalid_currency(currency):
    """Input：空白、非三位大写字母或非字符串；Expected Output：ValidationError；只验证币种形式。"""
    with pytest.raises(ValidationError):
        TripBudget(currency=currency, max_amount=Decimal("3000"))


def test_budget_currency_required_and_no_real_currency_lookup():
    """Input：缺币种或使用形式正确的 ZZZ；Expected Output：前者报错、后者成功；明确不验证真实货币有效性。"""
    with pytest.raises(ValidationError):
        TripBudget(max_amount=Decimal("3000"))
    assert TripBudget(currency="ZZZ", max_amount=Decimal("3000")).currency == "ZZZ"
