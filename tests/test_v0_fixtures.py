"""只验证固定案例完整性、控制变量与数据隔离，不重复测试 Schema 细则。"""

import pytest

from fixtures import load_persons, load_relationships, load_trips
from life_journey.schemas import Person, Relationship, Trip


@pytest.mark.parametrize("loader,model", [
    (load_persons, Person), (load_relationships, Relationship), (load_trips, Trip),
])
def test_all_fixtures_validate(loader, model):
    """Input：各类完整固定数据；Expected Output：全部经当前 Schema 重新校验且内容不变；防止模型演进后样例失效。"""
    for item in loader().values():
        assert isinstance(item, model)
        assert model.model_validate(item.model_dump(mode="python")) == item


@pytest.mark.parametrize("loader,id_field,expected", [
    (load_persons, "person_id", {"person_alex", "person_bella", "person_casey"}),
    (load_relationships, "relationship_id", {"relationship_alex_bella", "relationship_alex_casey"}),
    (load_trips, "trip_id", {
        "trip_tokyo_alex_bella", "trip_tokyo_alex_casey",
        "trip_tokyo_alex_bella_slow", "trip_tokyo_alex_bella_fast",
        "trip_tokyo_alex_personal_relevance",
    }),
])
def test_fixed_ids_and_repeatable_data(loader, id_field, expected):
    """Input：两次加载每类数据；Expected Output：固定预期 ID、无重复、字典键匹配且数据一致；禁止随机 ID 或日期漂移。"""
    first, second = loader(), loader()
    ids = [getattr(item, id_field) for item in first.values()]
    assert set(first) == set(ids) == expected
    assert len(ids) == len(set(ids)) == len(expected)
    assert all(key == getattr(item, id_field) for key, item in first.items())
    assert {key: item.model_dump() for key, item in first.items()} == {
        key: item.model_dump() for key, item in second.items()
    }


def test_fixture_references_and_global_ids():
    """Input：所有人物、关系、旅行；Expected Output：引用均存在且所有实体 ID 不重复；检查固定数据的一致性而非新增生产查询层。"""
    persons, relationships, trips = load_persons(), load_relationships(), load_trips()
    all_ids = [*persons, *relationships, *trips]
    assert len(all_ids) == len(set(all_ids))
    for relationship in relationships.values():
        assert {relationship.person_a_id, relationship.person_b_id} <= set(persons)
    for trip in trips.values():
        assert set(trip.participant_ids) <= set(persons)
        assert trip.budget.currency == "AUD"


def test_case_a_changes_only_participant_selection():
    """Input：Alex+Bella 与 Alex+Casey 的东京旅行；Expected Output：除追踪 ID 与参与者外完全一致，且明确关系偏好不同。"""
    trips, relationships = load_trips(), load_relationships()
    first, second = trips["trip_tokyo_alex_bella"], trips["trip_tokyo_alex_casey"]
    assert first.participant_ids == ["person_alex", "person_bella"]
    assert second.participant_ids == ["person_alex", "person_casey"]
    assert first.model_dump(exclude={"trip_id", "participant_ids"}) == second.model_dump(
        exclude={"trip_id", "participant_ids"}
    )
    ab, ac = relationships["relationship_alex_bella"], relationships["relationship_alex_casey"]
    assert ab.relationship_type == ac.relationship_type == "friend"
    assert ab.shared_travel_preferences != ac.shared_travel_preferences
    assert ab.preferred_pace_together != ac.preferred_pace_together


def test_case_b_changes_only_trip_pace():
    """Input：同一参与者的慢/快节奏旅行；Expected Output：仅 ID 与情境节奏不同；保证未来节奏单因素比较有稳定输入。"""
    trips = load_trips()
    slow, fast = trips["trip_tokyo_alex_bella_slow"], trips["trip_tokyo_alex_bella_fast"]
    assert slow.participant_ids == fast.participant_ids == ["person_alex", "person_bella"]
    assert slow.context.preferred_pace == "slow"
    assert fast.context.preferred_pace == "fast"
    exclude = {"trip_id": True, "context": {"preferred_pace": True}}
    assert slow.model_dump(exclude=exclude) == fast.model_dump(exclude=exclude)
    assert slow.context.activity_preferences == fast.context.activity_preferences != []
    assert load_persons()["person_alex"].preferred_pace == "fast"


def test_case_c_has_explicit_relevance_signals():
    """Input：Alex 独行的个人相关性案例；Expected Output：兴趣、拥挤反感和体验排除均明确存在；不验证未来模型输出。"""
    person = load_persons()["person_alex"]
    trip = load_trips()["trip_tokyo_alex_personal_relevance"]
    assert trip.participant_ids == [person.person_id]
    assert {"设计", "独立咖啡馆"} <= set(person.interests)
    assert {"拥挤", "大型主题乐园"} <= set(person.dislikes)
    assert "独立设计店" in trip.context.activity_preferences
    assert "体验独立咖啡馆" in trip.context.required_activities
    assert "大型主题乐园" in trip.context.excluded_activities


def test_reloads_are_isolated_after_mutation():
    """Input：一次加载后修改人物、关系、旅行及嵌套对象；Expected Output：已有第二份与再次加载的数据不变；防止跨测试污染。"""
    for loader in (load_persons, load_relationships, load_trips):
        first, second = loader(), loader()
        snapshot = {key: item.model_dump(mode="python") for key, item in second.items()}
        for item in first.values():
            if isinstance(item, Person):
                item.interests.append("测试临时兴趣")
                item.dislikes.append("测试临时反感")
                item.food_preferences.append("测试临时食物")
            elif isinstance(item, Relationship):
                item.shared_travel_preferences.append("测试临时共同偏好")
            else:
                item.participant_ids.append("person_test_only")
                item.budget.currency = "JPY"
                item.context.activity_preferences.append("测试临时偏好")
                item.context.required_activities.append("测试临时要求")
                item.context.excluded_activities.append("测试临时排除")
        assert {key: item.model_dump() for key, item in second.items()} == snapshot
        assert {key: item.model_dump() for key, item in loader().items()} == snapshot


def test_trips_do_not_share_nested_mutable_data():
    """Input：同次加载的两个基础旅行；Expected Output：修改其中一个的参与者、预算与情境不影响其他旅行；防止案例内部共享污染。"""
    trips = load_trips()
    first = trips.pop("trip_tokyo_alex_bella")
    snapshots = {key: trip.model_dump() for key, trip in trips.items()}
    first.participant_ids.append("person_test_only")
    first.budget.currency = "JPY"
    first.context.activity_preferences.append("测试临时偏好")
    first.context.required_activities.append("测试临时要求")
    first.context.excluded_activities.append("测试临时排除")
    assert {key: trip.model_dump() for key, trip in trips.items()} == snapshots
