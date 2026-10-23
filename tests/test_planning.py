"""规划与 API 使用 fake Client；不查询真实地点或调用 DeepSeek。"""
import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from life_journey.api import create_app
from life_journey.application import build_travel_context, initialize_interview
from life_journey.application.planning import build_planning_prompt, run_planning
from life_journey.llm import LLMCallResult, LLMRequestError
from life_journey.llm.planning import PlanningCallResult
from life_journey.sample_data import load_persons, load_relationships, load_trips
from life_journey.schemas import InterviewState, InterviewTurnResult
from life_journey.schemas.interview import MINIMUM_PLANNING_TOPICS
from life_journey.schemas.itinerary import Itinerary
from life_journey.schemas.planning import V0_FACT_NOTICE


def itinerary_payload(trip):
    """生成结构正确的虚构行程，只验证工程协议，不证明推荐质量。"""
    count=(trip.end_date-trip.start_date).days+1
    return {"trip_id":trip.trip_id,"summary":"按明确偏好放慢节奏。","days":[
        {"date":str(trip.start_date+timedelta(days=i)),"theme":"慢节奏城市探索","activities":[
            {"time_period":"afternoon","title":"设计展览","description":"安排一段展览时间，实际信息需核实。","rationale":"符合个人设计兴趣及明确共同看展偏好。"}
        ]} for i in range(count)]}


class FakePlanningClient:
    """从请求取得日期，返回虚构数据或注入错误，记录一次调用。"""
    def __init__(self, error=None, mutate=None):
        self.prompts=[];self.error=error;self.mutate=mutate
    def generate_itinerary(self,prompt):
        """不访问任何 Provider；所有输出仍经 Pydantic JSON 校验。"""
        self.prompts.append(prompt)
        if self.error: raise self.error
        from life_journey.schemas import Trip
        trip=Trip.model_validate_json(json.dumps(json.loads(prompt.user_prompt)["trip"]))
        data=itinerary_payload(trip)
        if self.mutate: self.mutate(data)
        return PlanningCallResult(output=Itinerary.model_validate_json(json.dumps(data)),provider="fake",model="planning-fake",latency_ms=1.0,total_tokens=99)


class ReadyInterviewClient:
    """一次明确确认最低主题；模型 ready=false 仍不能改变系统门槛。"""
    def generate_interview_turn(self,prompt):
        """只为 API 测试准备就绪状态。"""
        turn=InterviewTurnResult(context_update={"purpose":"relaxation","preferred_pace":"slow","required_activities":[],"excluded_activities":[]},confirmed_topics=list(MINIMUM_PLANNING_TOPICS),missing_topics=[],ready_to_plan=False,assistant_message="信息足够，可以规划。")
        return LLMCallResult(output=turn,provider="fake",model="fake",latency_ms=1.0)


def context_and_ready():
    """固定场景，集中复用已有最低确认主题，不在测试重新定义业务门槛。"""
    context=build_travel_context(load_trips()["trip_tokyo_alex_bella_slow"],load_persons().values(),load_relationships().values())
    state=InterviewState(trip_id=context.trip.trip_id,trip_setup_complete=True,topics={topic:"confirmed" for topic in MINIMUM_PLANNING_TOPICS})
    return context,state


def test_planning_selects_context_and_preserves_input():
    """Input：固定人物关系与已就绪情境；Expected Output：一次调用、相关人物/关系及 rationale 字段、完整日期与事实提示；验证无输入修改。"""
    context,state=context_and_ready()
    before=(context.model_dump(),state.model_dump())
    fake=FakePlanningClient()
    result=run_planning(context,state,fake)
    data=json.loads(fake.prompts[0].user_prompt)
    assert [p["name"] for p in data["participants"]] == ["Alex","Bella"]
    assert len(data["relationships"]) == 1
    assert data["trip"]["context"]["preferred_pace"] == "slow"
    assert "Popularity ≠ Personal Relevance" in fake.prompts[0].system_prompt
    assert "MBTI" in fake.prompts[0].system_prompt
    assert result.notice == V0_FACT_NOTICE
    assert result.metrics["total_tokens"] == 99
    assert len(fake.prompts) == 1
    assert Itinerary.model_validate_json(result.itinerary.model_dump_json()) == result.itinerary
    assert (context.model_dump(),state.model_dump()) == before


def test_not_ready_does_not_call_planning():
    """Input：未确认状态；Expected Output：ValueError 且零调用；验证 application 自身仍有门槛。"""
    context,_=context_and_ready();fake=FakePlanningClient()
    with pytest.raises(ValueError): run_planning(context,initialize_interview(context),fake)
    assert not fake.prompts


@pytest.mark.parametrize("change", ["id","missing_day","date"])
def test_itinerary_must_match_trip(change):
    """Input：错误 Trip ID、漏一天或范围外日期；Expected Output：ValueError；验证跨对象 ID 与日期覆盖。"""
    context,state=context_and_ready()
    def mutate(data):
        """保持 Schema 类型合法，以专测跨对象约束。"""
        if change=="id":data["trip_id"]="wrong"
        elif change=="missing_day":data["days"].pop()
        else:data["days"][-1]["date"]="2027-01-01"
    with pytest.raises(ValueError):run_planning(context,state,FakePlanningClient(mutate=mutate))


@pytest.mark.parametrize("change", ["duplicate_day","empty_rationale","unknown","empty_days","period"])
def test_itinerary_structure_validation(change):
    """Input：重复日期、空理由、未知字段、空天或非法时段；Expected Output：ValidationError；验证最小输出契约。"""
    context,_=context_and_ready();data=itinerary_payload(context.trip)
    if change=="duplicate_day":data["days"].append(data["days"][0])
    elif change=="empty_rationale":data["days"][0]["activities"][0]["rationale"]=" "
    elif change=="unknown":data["price_verified"]=True
    elif change=="empty_days":data["days"]=[]
    else:data["days"][0]["activities"][0]["time_period"]="anytime"
    with pytest.raises(ValidationError):Itinerary.model_validate_json(json.dumps(data))


def setup_trip(client):
    """API 创建正常单人旅行，不往开发数据库 seed fixture。"""
    person=client.post("/api/persons",json={"name":"规划测试人物"}).json()
    return client.post("/api/trips",json={"participant_ids":[person["person_id"]],"destination":"测试城市","start_date":"2026-11-10","end_date":"2026-11-11","budget":{"max_amount":"3000","currency":"AUD"}}).json()


def test_api_ready_then_planning(tmp_path):
    """Input：先未就绪规划、再明确确认、再点击规划；Expected Output：先409零调用、后200一次规划且不改 Trip/state；验证真实 API 门槛。"""
    fake=FakePlanningClient()
    with TestClient(create_app(tmp_path/"planning.sqlite3",llm_client=ReadyInterviewClient(),planning_client=fake)) as client:
        trip=setup_trip(client);url=f"/api/trips/{trip['trip_id']}"
        assert client.post(url+"/planning",json={"ready_to_plan":True}).status_code == 409
        assert not fake.prompts
        assert client.post(url+"/interview",json={"user_message":"确认"}).json()["ready_to_plan"] is True
        before=client.get(url).json();state=client.get(url+"/interview").json()
        response=client.post(url+"/planning")
        assert response.status_code == 200,response.text
        assert response.json()["itinerary"]["trip_id"] == trip["trip_id"]
        assert response.json()["notice"] == V0_FACT_NOTICE
        assert response.json()["metrics"] is None
        assert len(fake.prompts) == 1
        assert client.get(url).json() == before
        assert client.get(url+"/interview").json() == state
        assert client.post("/api/trips/missing/planning").status_code == 404


@pytest.mark.parametrize("error", [LLMRequestError("模拟网络失败"),ValueError("内部非法内容")])
def test_planning_errors_are_visible_and_do_not_change_state(tmp_path,error):
    """Input：已就绪但规划请求/校验失败；Expected Output：502且状态保留、无内部内容泄露；验证失败可明确报告。"""
    fake=FakePlanningClient(error=error)
    with TestClient(create_app(tmp_path/"failure.sqlite3",llm_client=ReadyInterviewClient(),planning_client=fake)) as client:
        trip=setup_trip(client);url=f"/api/trips/{trip['trip_id']}"
        client.post(url+"/interview",json={"user_message":"确认"})
        before=client.get(url).json()
        response=client.post(url+"/planning")
        assert response.status_code == 502
        assert "内部非法内容" not in response.text
        assert client.get(url).json() == before
