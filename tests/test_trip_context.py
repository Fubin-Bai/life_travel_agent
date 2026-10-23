"""校验本次旅行理解的数据契约，不测试自然语言提取。"""

import pytest
from pydantic import ValidationError

from life_journey.schemas import TripContext


ACTIVITY_FIELDS = ["activity_preferences", "required_activities", "excluded_activities"]


def test_empty_context_and_independent_defaults():
    """Input：两个空情境；Expected Output：空列表和 None，修改互不影响；验证未知状态与默认值隔离。"""
    first, second = TripContext(), TripContext()
    assert first.purpose is None
    assert first.preferred_pace is None
    assert all(getattr(first, field) == [] for field in ACTIVITY_FIELDS)
    for field in ACTIVITY_FIELDS:
        getattr(first, field).append("看展")
        assert getattr(second, field) == []
    first.required_activities.append("吃当地菜")
    assert first.activity_preferences == first.excluded_activities == ["看展"]


@pytest.mark.parametrize("field", ["purpose", *ACTIVITY_FIELDS])
@pytest.mark.parametrize("value", ["", "  ", 1, True, None])
def test_invalid_context_text(field, value):
    """Input：空白或非字符串文本/列表项；Expected Output：ValidationError；purpose=None 合法，验证严格文本边界。"""
    if field == "purpose" and value is None:
        assert TripContext(purpose=None).purpose is None
        return
    data = {field: [value] if field in ACTIVITY_FIELDS else value}
    with pytest.raises(ValidationError):
        TripContext(**data)


@pytest.mark.parametrize("field", ACTIVITY_FIELDS)
@pytest.mark.parametrize("value", ["看展", None, ("看展",), {"看展"}])
def test_activity_fields_require_lists(field, value):
    """Input：字符串、None、元组或集合；Expected Output：ValidationError；禁止静默转换活动容器。"""
    with pytest.raises(ValidationError):
        TripContext(**{field: value})


@pytest.mark.parametrize("pace", ["slow", "moderate", "fast", None])
def test_context_normalization_and_roundtrip(pace):
    """Input：完整情境和各合法节奏；Expected Output：去空白且 JSON 还原一致；验证三个活动字段独立保留。"""
    context = TripContext(
        purpose=" 纪念日 ", preferred_pace=pace,
        activity_preferences=[" 看展 "], required_activities=[" 吃当地菜 "],
        excluded_activities=[" 徒步 "],
    )
    assert context.purpose == "纪念日"
    assert context.activity_preferences == ["看展"]
    assert context.required_activities == ["吃当地菜"]
    assert context.excluded_activities == ["徒步"]
    assert context.preferred_pace == pace
    assert TripContext.model_validate_json(context.model_dump_json()) == context


@pytest.mark.parametrize("data", [
    {"preferred_pace": "medium"}, {"preferred_pace": 1},
    {"destination": "东京"}, {"budget": {}}, {"notes": "徒步"},
])
def test_unknown_fields_and_invalid_pace(data):
    """Input：非法节奏或不属于对话情境的字段；Expected Output：ValidationError；保持 Setup 与 Context 边界。"""
    with pytest.raises(ValidationError):
        TripContext(**data)


def test_no_activity_conflict_resolution():
    """Input：同一活动同时属于三类；Expected Output：原样保留；明确本轮不执行语义冲突检测或自动消解。"""
    context = TripContext(**{field: ["徒步"] for field in ACTIVITY_FIELDS})
    assert all(getattr(context, field) == ["徒步"] for field in ACTIVITY_FIELDS)
