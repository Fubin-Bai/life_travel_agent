"""完全虚构的固定 V0 数据，不包含真实人物信息或真实景点推荐。

不调用 create_* 或随机 ID；直接构造内部 Schema，所有数据经过正常校验。
每次调用均新建模型、列表、预算和情境，避免测试之间共享可变状态。
MBTI 是模拟人物明确自述，所有偏好另行显式填写，不由 MBTI 或关系标签推断。
"""

from datetime import date
from decimal import Decimal

from life_journey.schemas import Person, Relationship, Trip, TripBudget, TripContext


def load_persons() -> dict[str, Person]:
    """返回 Alex、Bella、Casey 三个独立虚构人物，以固定 person_id 为键。"""
    persons = [
        Person(
            person_id="person_alex", name="Alex",
            interests=["独立咖啡馆", "设计", "城市散步"],
            dislikes=["拥挤", "大型主题乐园"], preferred_pace="fast",
            food_preferences=["咖啡"], mbti="INFP",
        ),
        Person(
            person_id="person_bella", name="Bella",
            interests=["博物馆", "历史", "建筑"], dislikes=["夜生活"],
            preferred_pace="moderate", food_preferences=["当地菜"],
        ),
        Person(
            person_id="person_casey", name="Casey",
            interests=["自然", "甜品", "轻松体验"], dislikes=["高强度徒步"],
            preferred_pace="slow", food_preferences=["甜品"], mbti="ENFJ",
        ),
    ]
    return {person.person_id: person for person in persons}


def load_relationships() -> dict[str, Relationship]:
    """两段关系均为 friend，但共同偏好不同且已明确填写，不从标签生成。"""
    relationships = [
        Relationship(
            relationship_id="relationship_alex_bella",
            person_a_id="person_alex", person_b_id="person_bella", relationship_type="friend",
            shared_travel_preferences=["一起看设计展", "探索历史街区"],
            preferred_pace_together="moderate",
        ),
        Relationship(
            relationship_id="relationship_alex_casey",
            person_a_id="person_alex", person_b_id="person_casey", relationship_type="friend",
            shared_travel_preferences=["安静的公园散步", "一起品尝甜品"],
            preferred_pace_together="slow",
        ),
    ]
    return {relationship.relationship_id: relationship for relationship in relationships}


def load_trips() -> dict[str, Trip]:
    """返回 A 类同行人对比、B 类节奏单因素对比及 C 类个人相关性场景。

    日期、东京目的地与 AUD 预算固定；金额仅为模拟规划输入，不证明真实价格可行。
    情境由 fixture 作者直接提供，不代表已经实现对话提取。
    """
    # 此基础字典只在本次调用内存在；每次构造使用独立参与者、预算和情境。
    setup = {
        "destination": "东京", "start_date": date(2026, 11, 10),
        "end_date": date(2026, 11, 12),
    }

    def budget() -> TripBudget:
        """为每次旅行新建相同的正有限 AUD 区间，不查询价格或推断费用口径。"""
        return TripBudget(min_amount=Decimal("2000"), max_amount=Decimal("3000"), currency="AUD")

    trips = [
        # Case A：除了场景 ID，只改变参与者选择；不另改 Trip Context。
        Trip(
            trip_id="trip_tokyo_alex_bella", participant_ids=["person_alex", "person_bella"],
            budget=budget(), **setup,
        ),
        Trip(
            trip_id="trip_tokyo_alex_casey", participant_ids=["person_alex", "person_casey"],
            budget=budget(), **setup,
        ),
        # Case B：活动偏好也保持一致，严格只改变本次节奏，不同时改目的或活动。
        Trip(
            trip_id="trip_tokyo_alex_bella_slow", participant_ids=["person_alex", "person_bella"],
            budget=budget(), context=TripContext(
                purpose="共同探索城市", preferred_pace="slow",
                activity_preferences=["设计展", "历史街区"],
            ), **setup,
        ),
        Trip(
            trip_id="trip_tokyo_alex_bella_fast", participant_ids=["person_alex", "person_bella"],
            budget=budget(), context=TripContext(
                purpose="共同探索城市", preferred_pace="fast",
                activity_preferences=["设计展", "历史街区"],
            ), **setup,
        ),
        # Case C：无真实景点或结果标签，只提供可用于后续相关性检查的明确输入。
        Trip(
            trip_id="trip_tokyo_alex_personal_relevance", participant_ids=["person_alex"],
            budget=budget(), context=TripContext(
                purpose="独自探索设计与咖啡文化",
                activity_preferences=["独立设计店", "安静的独立咖啡馆"],
                required_activities=["体验独立咖啡馆"],
                excluded_activities=["大型主题乐园"],
            ), **setup,
        ),
    ]
    return {trip.trip_id: trip for trip in trips}
