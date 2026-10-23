"""API 离线集成测试：临时 SQLite + TestClient，不建立真实网络连接或调用 LLM。"""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from life_journey.api import create_app
from life_journey.schemas import Person, Relationship, Trip


@pytest.fixture
def database(tmp_path):
    """每个测试独立临时文件，不触碰开发数据库。"""
    return tmp_path / "test.sqlite3"


@pytest.fixture
def client(database):
    """显式进入 lifespan 初始化临时库，结束后关闭客户端。"""
    with TestClient(create_app(database)) as client:
        yield client


def person(client, name="测试人物"):
    """通过公开 API 创建测试人物，ID 由系统生成。"""
    response = client.post("/api/persons", json={"name": name, "interests": ["设计"]})
    assert response.status_code == 201
    return response.json()


def relationship_data(a, b):
    """构造不推断偏好的关系输入。"""
    return dict(person_a_id=a["person_id"], person_b_id=b["person_id"], relationship_type="partner",
                shared_travel_preferences=["散步"], preferred_pace_together="slow")


def trip_data(ids):
    """JSON 日期与金额字符串必须经现有 strict JSON Schema 正常解析。"""
    return dict(participant_ids=ids, destination="测试目的地", start_date="2026-01-01", end_date="2026-01-01",
                budget={"min_amount": "2000.10", "max_amount": "3000.25", "currency": "AUD"})


def test_empty_database_has_no_seed(client):
    """Input：全新数据库；Expected Output：三个集合均为空；验证不自动持久化 mock 人物和旅行。"""
    for resource in ("persons", "relationships", "trips"):
        assert client.get(f"/api/{resource}").json() == []


def test_person_create_read_replace_and_reopen(client, database):
    """Input：创建后完整更新再用另一 app 打开同一文件；Expected Output：ID 稳定、字段持久化且省略列表重置；验证 PUT 与跨连接持久化。"""
    original = person(client)
    updated = client.put(f"/api/persons/{original['person_id']}", json={"name": "新名字", "mbti": "INFP", "dislikes": ["拥挤"]})
    assert updated.status_code == 200
    assert updated.json()["person_id"] == original["person_id"]
    assert updated.json()["interests"] == []
    assert Person.model_validate_json(updated.content).mbti == "INFP"
    with TestClient(create_app(database)) as reopened:
        assert reopened.get(f"/api/persons/{original['person_id']}").json() == updated.json()
        assert reopened.get("/api/persons").json() == [updated.json()]


def test_relationship_create_update_read_and_preference_separation(client, database):
    """Input：两个独立 Person 与关系创建/更新；Expected Output：关系回读相同、人物不变；验证关系更新不覆盖长期个人偏好。"""
    a, b = person(client, "A"), person(client, "B")
    response = client.post("/api/relationships", json=relationship_data(a, b))
    assert response.status_code == 201
    link = response.json()
    updated = client.put(f"/api/relationships/{link['relationship_id']}", json={**relationship_data(a,b), "relationship_type": "friend", "shared_travel_preferences": []})
    assert updated.status_code == 200
    assert updated.json()["relationship_id"] == link["relationship_id"]
    assert Relationship.model_validate_json(updated.content).shared_travel_preferences == []
    assert client.get(f"/api/persons/{a['person_id']}").json() == a
    with TestClient(create_app(database)) as reopened:
        assert reopened.get(f"/api/relationships/{link['relationship_id']}").json() == updated.json()
        assert reopened.get("/api/relationships").json() == [updated.json()]


def test_duplicate_unordered_relationship_conflicts(client):
    """Input：同人物对同类型的反向关系；Expected Output：409 且只保留一条；相同人物对不同类型允许，复用 Context Builder 判重边界。"""
    a, b = person(client, "A"), person(client, "B")
    data = relationship_data(a,b)
    assert client.post("/api/relationships", json=data).status_code == 201
    assert client.post("/api/relationships", json=relationship_data(b,a)).status_code == 409
    assert len(client.get("/api/relationships").json()) == 1
    assert client.post("/api/relationships", json={**data,"relationship_type":"family"}).status_code == 201


def test_duplicate_update_rolls_back(client):
    """Input：将已有关系改成另一条已存在类型；Expected Output：409 且原记录不变；验证事务回滚。"""
    a, b = person(client,"A"), person(client,"B")
    data = relationship_data(a,b)
    client.post("/api/relationships", json=data)
    second = client.post("/api/relationships", json={**data,"relationship_type":"friend"}).json()
    assert client.put(f"/api/relationships/{second['relationship_id']}", json=data).status_code == 409
    assert client.get(f"/api/relationships/{second['relationship_id']}").json() == second


@pytest.mark.parametrize("count", [1,2])
def test_trip_persists_setup_participants_and_empty_context(client,database,count):
    """Input：单人/多人旅行与 Decimal JSON 金额；Expected Output：201、空情境、顺序和精度跨重开保留；验证系统 ID 和持久化。"""
    ids = [person(client,str(index))["person_id"] for index in range(count)]
    data = trip_data(ids)
    response = client.post("/api/trips", json=data)
    assert response.status_code == 201, response.text
    trip = Trip.model_validate_json(response.content)
    assert trip.trip_id.startswith("trip_")
    assert trip.context.model_dump() == dict(purpose=None,preferred_pace=None,activity_preferences=[],required_activities=[],excluded_activities=[])
    for key,value in data.items():
        assert response.json()[key] == value
    with TestClient(create_app(database)) as reopened:
        assert reopened.get(f"/api/trips/{trip.trip_id}").json() == response.json()
        assert reopened.get("/api/trips").json() == [response.json()]
    with sqlite3.connect(database) as db:
        assert [row[0] for row in db.execute("SELECT person_id FROM trip_participants ORDER BY position")] == ids


@pytest.mark.parametrize("resource", ["persons","relationships","trips"])
def test_missing_ids_are_404(client,resource):
    """Input：不存在的 ID；Expected Output：404；验证读取不会创建占位数据。"""
    assert client.get(f"/api/{resource}/missing").status_code == 404


def test_unknown_person_references_fail_atomically(client,database):
    """Input：关系或旅行引用不存在的人物；Expected Output：422 且无部分旅行/关联写入；验证 FK 和同一事务原子性。"""
    a = person(client)
    data = relationship_data(a,{"person_id":"missing"})
    assert client.post("/api/relationships",json=data).status_code == 422
    assert client.post("/api/trips",json=trip_data([a["person_id"],"missing"])).status_code == 422
    assert client.get("/api/trips").json() == []
    assert client.get("/api/relationships").json() == []
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT count(*) FROM trip_participants").fetchone()[0] == 0


@pytest.mark.parametrize("payload", [
    {"name":" "},{"name":123},{"name":"A","person_id":"user_id"},
    {"name":"A","mbti":"INVALID"},{"name":"A","interests":[""]},
    {"name":"A","preferred_pace":"very fast"},
])
def test_person_validation_uses_existing_schema(client,payload):
    """Input：空白、类型、系统 ID、MBTI 和偏好非法值；Expected Output：422 且未写入；验证复用既有输入校验。"""
    assert client.post("/api/persons",json=payload).status_code == 422
    assert client.get("/api/persons").json() == []


@pytest.mark.parametrize("patch", [
    {"participant_ids":[]},{"participant_ids":["SAME","SAME"]},
    {"end_date":"2025-01-01"},{"start_date":"bad-date"},
    {"context":{}},{"trip_id":"manual"},
    {"budget":{"currency":"AUD"}},
    {"budget":{"max_amount":"-1","currency":"AUD"}},
    {"budget":{"max_amount":"Infinity","currency":"AUD"}},
])
def test_trip_validation_keeps_strict_domain_rules(client,patch):
    """Input：参与者、日期、预算或系统字段非法；Expected Output：422 且未写入；验证传输层不放松领域语义。"""
    a = person(client)
    assert client.post("/api/trips",json={**trip_data([a["person_id"]]),**patch}).status_code == 422
    assert client.get("/api/trips").json() == []


@pytest.mark.parametrize("patch", ["self","enum","id"])
def test_relationship_validation(client,patch):
    """Input：自身关系、非法类型或手输关系 ID；Expected Output：422；验证固定枚举和系统字段边界。"""
    a,b = person(client,"A"),person(client,"B")
    data = relationship_data(a,b)
    if patch == "self": data["person_b_id"] = a["person_id"]
    elif patch == "enum": data["relationship_type"] = "romance"
    else: data["relationship_id"] = "manual"
    assert client.post("/api/relationships",json=data).status_code == 422


def test_put_missing_does_not_insert(client):
    """Input：更新不存在的人物/关系；Expected Output：404 且不插入；避免 PUT 隐式创建。"""
    assert client.put("/api/persons/missing",json={"name":"A"}).status_code == 404
    a,b = person(client,"A"),person(client,"B")
    assert client.put("/api/relationships/missing",json=relationship_data(a,b)).status_code == 404
    assert client.get("/api/relationships").json() == []


def test_invalid_person_update_keeps_old_record(client):
    """Input：将已保存 Person 更新为空姓名；Expected Output：422 且旧数据保留；验证失败不污染持久化记录。"""
    a = person(client)
    assert client.put(f"/api/persons/{a['person_id']}",json={"name":""}).status_code == 422
    assert client.get(f"/api/persons/{a['person_id']}").json() == a


def test_json_errors_and_cors(client):
    """Input：无效 JSON、本地与外部来源预检；Expected Output：422、本地允许、外部拒绝；验证传输及本地 CORS。"""
    assert client.post("/api/persons",content="{",headers={"Content-Type":"application/json"}).status_code == 422
    for origin in ["http://localhost:5173","http://127.0.0.1:5173"]:
        response = client.options("/api/persons",headers={"Origin":origin,"Access-Control-Request-Method":"PUT"})
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == origin
    assert client.options("/api/persons",headers={"Origin":"https://unrelated.example","Access-Control-Request-Method":"PUT"}).status_code == 400
