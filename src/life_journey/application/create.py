"""将已校验的用户输入转换为带系统 ID 的内部模型。"""

from uuid import uuid4

from life_journey.schemas import (
    Person, PersonCreate, Relationship, RelationshipCreate, Trip, TripContext, TripCreate,
)


def create_person(data: PersonCreate) -> Person:
    """生成随机 UUID4 字符串 ID，复制用户字段，不修改原输入。"""
    if not isinstance(data, PersonCreate):
        raise TypeError("create_person 需要已校验的 PersonCreate")
    return Person(person_id=f"person_{uuid4()}", **data.model_dump(mode="python"))


def create_relationship(data: RelationshipCreate) -> Relationship:
    """生成关系 ID，不查询人物是否存在，不推断共同偏好。"""
    if not isinstance(data, RelationshipCreate):
        raise TypeError("create_relationship 需要已校验的 RelationshipCreate")
    return Relationship(
        relationship_id=f"relationship_{uuid4()}", **data.model_dump(mode="python")
    )


def create_trip(data: TripCreate) -> Trip:
    """生成旅行 ID 并创建独立空情境，不读取或提取对话。"""
    if not isinstance(data, TripCreate):
        raise TypeError("create_trip 需要已校验的 TripCreate")
    return Trip(
        trip_id=f"trip_{uuid4()}", context=TripContext(), **data.model_dump(mode="python")
    )
