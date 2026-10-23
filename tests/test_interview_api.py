"""Web 访谈使用 fake Client；临时 SQLite，不访问真实 DeepSeek。"""

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from life_journey.api import create_app
from life_journey.llm import LLMCallResult, LLMConfigurationError, LLMRequestError, LLMResponseError
from life_journey.schemas import InterviewState, InterviewTurnResult


class FakeClient:
    """记录一次调用的 Prompt，并顺序返回固定输出或异常。"""
    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.prompts = []

    def generate_interview_turn(self, prompt):
        """不解析自然语言，直接模拟已校验 Client 协议。"""
        self.prompts.append(json.loads(prompt.user_prompt))
        value = next(self.outputs)
        if isinstance(value, Exception):
            raise value
        return LLMCallResult(output=value,provider="fake",model="fake-interview",latency_ms=2.0,total_tokens=42)


def turns():
    """两轮补齐四个最低主题，同时模拟 LLM 与系统 ready 双向不一致。"""
    return [
        InterviewTurnResult(context_update={"purpose":"relaxation","preferred_pace":"slow"},
                            confirmed_topics=["purpose","preferred_pace"],missing_topics=[],ready_to_plan=True,
                            assistant_message="  这次慢一点，还有必须安排的活动吗？  "),
        InterviewTurnResult(context_update={"required_activities":[],"excluded_activities":[]},
                            confirmed_topics=["required_activities","excluded_activities"],missing_topics=[],ready_to_plan=False,
                            assistant_message="信息已经足够，可以开始规划。"),
    ]


def setup_trip(client):
    """真实 CRUD 准备三个人，其中一人不参与本次旅行。"""
    ids = [client.post("/api/persons",json={"name":name}).json()["person_id"] for name in ["甲","乙","无关人"]]
    for other in ids[1:]:
        client.post("/api/relationships",json=dict(person_a_id=ids[0],person_b_id=other,relationship_type="friend"))
    trip = client.post("/api/trips",json=dict(participant_ids=ids[:2],destination="测试城市",start_date="2026-11-10",end_date="2026-11-12",budget={"max_amount":"3000","currency":"AUD"})).json()
    return trip,ids


def test_two_turns_persist_and_restore_context_and_state(tmp_path):
    """Input：首次和第二轮消息；Expected Output：状态创建并累计、情境写回、重开仍可恢复、只发送当前人物关系；验证完整离线链路。"""
    path = tmp_path / "interview.sqlite3"
    fake = FakeClient(turns())
    with TestClient(create_app(path,llm_client=fake)) as client:
        trip, ids = setup_trip(client)
        url = f"/api/trips/{trip['trip_id']}/interview"
        initial = client.get(url).json()
        assert initial["ready_to_plan"] is False
        assert initial["state"]["topics"]["purpose"] == "unknown"
        assert not fake.prompts
        with sqlite3.connect(path) as db:
            assert db.execute("SELECT count(*) FROM interview_states").fetchone()[0] == 0
        first = client.post(url,json={"user_message":"  想休息  "})
        assert first.status_code == 200,first.text
        first = first.json()
        assert first["assistant_message"] == turns()[0].assistant_message
        assert first["ready_to_plan"] is False and first["llm_ready_to_plan"] is True
        assert first["metrics"] is None
        assert first["context"]["purpose"] == "relaxation"
        assert fake.prompts[0]["latest_user_message"] == "  想休息  "
        assert [person["person_id"] for person in fake.prompts[0]["person_profiles"]] == ids[:2]
        assert len(fake.prompts[0]["relevant_relationships"]) == 1
    with TestClient(create_app(path,llm_client=fake)) as reopened:
        restored = reopened.get(url).json()
        assert restored["state"]["topics"]["purpose"] == "confirmed"
        assert restored["context"]["preferred_pace"] == "slow"
        second = reopened.post(url+"?debug=true",json={"user_message":"无必去或排除"})
        assert second.status_code == 200,second.text
        second = second.json()
        assert second["ready_to_plan"] is True and second["llm_ready_to_plan"] is False
        assert second["metrics"]["total_tokens"] == 42
        assert fake.prompts[1]["current_trip_context"]["purpose"] == "relaxation"
        assert fake.prompts[1]["interview_state"]["confirmed_topics"] == ["purpose","preferred_pace"]
        saved_trip = reopened.get(f"/api/trips/{trip['trip_id']}").json()
        assert saved_trip["context"] == second["context"]
        for field in ("participant_ids","budget","destination","start_date","end_date"):
            assert saved_trip[field] == trip[field]
        assert reopened.get(url).json()["ready_to_plan"] is True
    assert len(fake.prompts) == 2
    with sqlite3.connect(path) as db:
        row = db.execute("SELECT data FROM interview_states").fetchone()[0]
        assert InterviewState.model_validate_json(row).ready_to_plan
        assert "missing_topics" not in json.loads(row)
        assert db.execute("SELECT count(*) FROM interview_states").fetchone()[0] == 1


@pytest.mark.parametrize("error,status", [(LLMRequestError("模拟网络失败"),502),(LLMResponseError("模拟结构错误"),502),(LLMConfigurationError("模拟配置缺失"),503)])
def test_failed_calls_do_not_save_partial_turn(tmp_path,error,status):
    """Input：Client 网络、响应、配置失败；Expected Output：明确错误状态，Trip 和 InterviewState 无半轮写入；验证失败原子性且不重试。"""
    path=tmp_path/"failed.sqlite3"
    fake=FakeClient([error])
    with TestClient(create_app(path,llm_client=fake)) as client:
        trip,_=setup_trip(client)
        response=client.post(f"/api/trips/{trip['trip_id']}/interview",json={"user_message":"想放松"})
        assert response.status_code == status
        assert client.get(f"/api/trips/{trip['trip_id']}").json() == trip
    assert len(fake.prompts) == 1
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM interview_states").fetchone()[0] == 0


@pytest.mark.parametrize("data", [{"user_message":""},{"user_message":"  "},{"user_message":123},{"user_message":"好","ready_to_plan":True}])
def test_invalid_request_does_not_call_model(tmp_path,data):
    """Input：空白/非法类型/注入状态字段；Expected Output：422 且零调用；验证 Web 请求只接受用户消息。"""
    fake=FakeClient([])
    with TestClient(create_app(tmp_path/"invalid.sqlite3",llm_client=fake)) as client:
        trip,_=setup_trip(client)
        assert client.post(f"/api/trips/{trip['trip_id']}/interview",json=data).status_code == 422
    assert not fake.prompts


def test_missing_trip_does_not_call_model(tmp_path):
    """Input：不存在的 Trip；Expected Output：GET/POST 404 且零模型调用；防止错误旅行产生费用。"""
    fake=FakeClient([])
    with TestClient(create_app(tmp_path/"missing.sqlite3",llm_client=fake)) as client:
        assert client.get("/api/trips/missing/interview").status_code == 404
        assert client.post("/api/trips/missing/interview",json={"user_message":"测试"}).status_code == 404
    assert not fake.prompts


def test_state_write_failure_rolls_back_trip(tmp_path):
    """Input：数据库触发器拒绝状态写入；Expected Output：失败且已更新 TripContext 同时回滚；验证两表原子提交。"""
    path=tmp_path/"rollback.sqlite3"
    fake=FakeClient([turns()[0]])
    with TestClient(create_app(path,llm_client=fake)) as client:
        trip,_=setup_trip(client)
        with sqlite3.connect(path) as db:
            db.execute("CREATE TRIGGER fail_state BEFORE INSERT ON interview_states BEGIN SELECT RAISE(ABORT,'test rollback'); END")
        assert client.post(f"/api/trips/{trip['trip_id']}/interview",json={"user_message":"放松"}).status_code == 409
        assert client.get(f"/api/trips/{trip['trip_id']}").json() == trip


def test_changed_snapshot_cannot_be_overwritten(tmp_path):
    """Input：模拟模型调用期间另一请求已修改旅行；Expected Output：409、不覆盖新情境；验证并发旧结果不会静默写回。"""
    path=tmp_path/"conflict.sqlite3"
    class ChangingClient(FakeClient):
        """模型返回前模拟独立事务完成新写入。"""
        def generate_interview_turn(self,prompt):
            result=super().generate_interview_turn(prompt)
            with sqlite3.connect(path) as db:
                row=db.execute("SELECT id,data FROM trips").fetchone()
                data=json.loads(row[1]);data["context"]["purpose"]="other committed value"
                db.execute("UPDATE trips SET data=? WHERE id=?",(json.dumps(data),row[0]))
            return result
    fake=ChangingClient([turns()[0]])
    with TestClient(create_app(path,llm_client=fake)) as client:
        trip,_=setup_trip(client)
        assert client.post(f"/api/trips/{trip['trip_id']}/interview",json={"user_message":"休息"}).status_code == 409
        assert client.get(f"/api/trips/{trip['trip_id']}").json()["context"]["purpose"] == "other committed value"


def test_missing_key_reports_without_network(tmp_path,monkeypatch):
    """Input：无环境 Key、未注入 Client；Expected Output：503、明确配置错误且不发生网络请求；验证 lazy Provider 初始化。"""
    monkeypatch.delenv("DEEPSEEK_API_KEY",raising=False)
    with TestClient(create_app(tmp_path/"key.sqlite3")) as client:
        trip,_=setup_trip(client)
        response=client.post(f"/api/trips/{trip['trip_id']}/interview",json={"user_message":"休息"})
        assert response.status_code == 503
        assert "DEEPSEEK_API_KEY" in response.json()["detail"]


def test_different_trips_do_not_share_interview_state(tmp_path):
    """Input：只访谈第一趟旅行，再读取另一趟；Expected Output：另一趟主题仍 unknown、情境为空；验证状态按 Trip 隔离。"""
    fake = FakeClient([turns()[0]])
    with TestClient(create_app(tmp_path / "isolation.sqlite3", llm_client=fake)) as client:
        first, _ = setup_trip(client)
        second, _ = setup_trip(client)
        assert client.post(f"/api/trips/{first['trip_id']}/interview", json={"user_message": "放松"}).status_code == 200
        other = client.get(f"/api/trips/{second['trip_id']}/interview").json()
        assert other["state"]["topics"]["purpose"] == "unknown"
        assert other["context"]["purpose"] is None
        assert other["ready_to_plan"] is False
    assert len(fake.prompts) == 1


def test_invalid_mutated_output_cannot_be_saved(tmp_path):
    """Input：Client 输出构造后被改为非法列表 null；Expected Output：502 且无情境写入；验证 runner 的领域再校验仍生效。"""
    invalid = turns()[0]
    invalid.context_update.required_activities = None
    invalid.context_update.model_fields_set.add("required_activities")
    fake = FakeClient([invalid])
    with TestClient(create_app(tmp_path / "invalid_output.sqlite3", llm_client=fake)) as client:
        trip, _ = setup_trip(client)
        assert client.post(f"/api/trips/{trip['trip_id']}/interview", json={"user_message": "放松"}).status_code == 502
        assert client.get(f"/api/trips/{trip['trip_id']}").json() == trip
