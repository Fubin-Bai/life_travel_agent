"""只选择当前旅行相关数据，不合并偏好、不推断、不调用外部服务。"""

from collections.abc import Iterable

from life_journey.schemas import Person, Relationship, TravelContext, Trip


def build_travel_context(
    trip: Trip,
    persons: Iterable[Person],
    relationships: Iterable[Relationship],
) -> TravelContext:
    """按 Trip 顺序选择人物，按输入顺序选择相关关系，并返回独立数据。

    集合应提供模型对象，例如 fixture 字典的 values()，不接受原始数据字典。
    Person ID 在整个输入集合中不得重复，本次参与者必须全部存在。
    关系若接触任一参与者则检查引用；完全无关的关系不检查、不输出。
    只对最终入选关系检查重复 ID 与无方向人物对+类型，不静默去重。
    """
    if not isinstance(trip, Trip):
        raise TypeError("trip 必须是已校验的 Trip")

    person_by_id: dict[str, Person] = {}
    for person in persons:
        if not isinstance(person, Person):
            raise TypeError("persons 必须包含 Person 模型对象")
        if person.person_id in person_by_id:
            raise ValueError(f"重复 person_id: {person.person_id}")
        person_by_id[person.person_id] = person

    participants: list[Person] = []
    for person_id in trip.participant_ids:
        if person_id not in person_by_id:
            raise ValueError(f"找不到 Trip 参与者: {person_id}")
        participants.append(person_by_id[person_id])

    participant_ids = set(trip.participant_ids)
    selected: list[Relationship] = []
    seen_ids: set[str] = set()
    seen_pairs: set[tuple[str, str, str]] = set()
    for relationship in relationships:
        if not isinstance(relationship, Relationship):
            raise TypeError("relationships 必须包含 Relationship 模型对象")
        endpoints = {relationship.person_a_id, relationship.person_b_id}
        if not endpoints & participant_ids:
            continue
        for person_id in sorted(endpoints):
            if person_id not in person_by_id:
                raise ValueError(
                    f"Relationship {relationship.relationship_id} 引用不存在的 Person: {person_id}"
                )
        if not endpoints <= participant_ids:
            continue
        if relationship.relationship_id in seen_ids:
            raise ValueError(f"重复 relationship_id: {relationship.relationship_id}")
        person_a_id, person_b_id = sorted(endpoints)
        pair = (person_a_id, person_b_id, relationship.relationship_type)
        if pair in seen_pairs:
            raise ValueError(f"重复关系（人物对与类型）: {pair}")
        seen_ids.add(relationship.relationship_id)
        seen_pairs.add(pair)
        selected.append(relationship)

    # 通过 Python 数据重新构造嵌套对象，避免输出与输入共享列表、情境或预算。
    return TravelContext(
        trip=trip.model_dump(mode="python"),
        participants=[person.model_dump(mode="python") for person in participants],
        relationships=[relationship.model_dump(mode="python") for relationship in selected],
    )
