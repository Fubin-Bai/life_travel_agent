"""V0 SQLite 存取；JSON 保存领域数据，外键保存人物引用，不引入 ORM。"""

from contextlib import contextmanager
from pathlib import Path
import sqlite3

from life_journey.schemas import Person, Relationship, Trip

MODELS = {"persons": Person, "relationships": Relationship, "trips": Trip}


def initialize_database(path: Path) -> None:
    """只在启动时建库建表，不插入 mock 数据。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS persons (
                id TEXT PRIMARY KEY, data TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS local_profile (
                singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                person_id TEXT NOT NULL UNIQUE REFERENCES persons(id)
            );
            CREATE TABLE IF NOT EXISTS relationships (
                id TEXT PRIMARY KEY,
                person_a_id TEXT NOT NULL REFERENCES persons(id),
                person_b_id TEXT NOT NULL REFERENCES persons(id),
                relationship_type TEXT NOT NULL, data TEXT NOT NULL,
                UNIQUE(person_a_id, person_b_id, relationship_type),
                CHECK(person_a_id < person_b_id)
            );
            CREATE TABLE IF NOT EXISTS trips (
                id TEXT PRIMARY KEY, data TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS interview_states (
                trip_id TEXT PRIMARY KEY REFERENCES trips(id), data TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS trip_participants (
                trip_id TEXT NOT NULL REFERENCES trips(id),
                person_id TEXT NOT NULL REFERENCES persons(id),
                position INTEGER NOT NULL,
                PRIMARY KEY(trip_id, person_id), UNIQUE(trip_id, position)
            );
        """)


@contextmanager
def connect(path: Path):
    """每次操作独立连接和事务；异常回滚，成功提交，总是关闭连接。"""
    db = sqlite3.connect(path, timeout=5)
    db.execute("PRAGMA foreign_keys = ON")
    try:
        with db:
            yield db
    finally:
        db.close()


def read_models(db, table: str, object_id: str | None = None):
    """表名只接受固定映射，参数化查询 ID；JSON 回读再次经领域模型校验。"""
    model = MODELS[table]
    if object_id is None:
        rows = db.execute(f"SELECT data FROM {table} ORDER BY rowid").fetchall()
        return [model.model_validate_json(row[0]) for row in rows]
    row = db.execute(f"SELECT data FROM {table} WHERE id = ?", (object_id,)).fetchone()
    return model.model_validate_json(row[0]) if row else None


def write_model(db, model: Person | Relationship | Trip, *, replace: bool = False) -> None:
    """写入校验后的完整模型；关系规范化人物对用于判重，不改变领域模型 A/B。"""
    if isinstance(model, Person):
        if replace:
            db.execute("UPDATE persons SET data=? WHERE id=?", (model.model_dump_json(), model.person_id))
        else:
            db.execute("INSERT INTO persons(id,data) VALUES (?,?)", (model.person_id, model.model_dump_json()))
    elif isinstance(model, Relationship):
        a, b = sorted((model.person_a_id, model.person_b_id))
        values = (a, b, model.relationship_type, model.model_dump_json(), model.relationship_id)
        if replace:
            db.execute("UPDATE relationships SET person_a_id=?,person_b_id=?,relationship_type=?,data=? WHERE id=?", values)
        else:
            db.execute("INSERT INTO relationships(person_a_id,person_b_id,relationship_type,data,id) VALUES (?,?,?,?,?)", values)
    elif isinstance(model, Trip):
        db.execute("INSERT INTO trips(id,data) VALUES (?,?)", (model.trip_id, model.model_dump_json()))
        db.executemany("INSERT INTO trip_participants(trip_id,person_id,position) VALUES (?,?,?)",
                       [(model.trip_id, person_id, index) for index, person_id in enumerate(model.participant_ids)])
    else:
        raise TypeError("不支持的领域模型")


def interview_snapshot(db, trip_id: str):
    """记录旅行/状态原文；最终提交时防止慢请求覆盖已完成的新一轮。"""
    trip_row = db.execute("SELECT data FROM trips WHERE id=?", (trip_id,)).fetchone()
    state_row = db.execute("SELECT data FROM interview_states WHERE trip_id=?", (trip_id,)).fetchone()
    return (trip_row[0] if trip_row else None, state_row[0] if state_row else None)


def read_interview_state(db, trip_id: str):
    """还原时排除计算字段的 JSON 与现有 frozen 状态模型保持一致。"""
    from life_journey.schemas.interview import InterviewState
    row = db.execute("SELECT data FROM interview_states WHERE trip_id=?", (trip_id,)).fetchone()
    return InterviewState.model_validate_json(row[0]) if row else None


def save_interview(db, trip: Trip, state) -> None:
    """由调用方的同一事务提交 TripContext 和独立状态，不保存对话或重复情境。"""
    if trip.trip_id != state.trip_id:
        raise ValueError("旅行与访谈状态 ID 不一致")
    db.execute("UPDATE trips SET data=? WHERE id=?", (trip.model_dump_json(), trip.trip_id))
    db.execute("INSERT INTO interview_states(trip_id,data) VALUES (?,?) "
               "ON CONFLICT(trip_id) DO UPDATE SET data=excluded.data",
               (trip.trip_id, state.model_dump_json(round_trip=True)))
