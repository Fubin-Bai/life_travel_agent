"""V1 确定性工作流与 API 离线测试，不调用任何外部网络。"""
import json
from datetime import datetime,timezone
import pytest
from fastapi.testclient import TestClient
from life_journey.application.planning_observation import collect_planning_observation
from life_journey.application.planning import run_planning
from life_journey.tools import (MainlandCity, PlaceSearchResult, RouteResult, ToolRequestError, ToolResponseError, NoPlacesError, UnsupportedDestinationError)
from test_amap_tools import place
from test_planning import context_and_ready,FakePlanningClient,ReadyInterviewClient,setup_trip
from life_journey.api import create_app


class FakeTools:
    """固定的候选/路线与请求记录，单元测试永不读取真实 Key。"""
    def __init__(self,empty=False,error=None):
        self.calls=[];self.empty=empty;self.error=error
    def resolve_city(self,request):
        """记录范围请求；异常用于验证零模型调用。"""
        self.calls.append(('city',request))
        if self.error:raise self.error
        return MainlandCity(name='北京市',adcode='110000')
    def search_places(self,request):
        """同名ID跨搜索重复，工作流按ID形成有限候选池。"""
        self.calls.append(('search',request))
        return PlaceSearchResult(request=request,status='empty' if self.empty else 'ok',places=[] if self.empty else [place('p1'),place('p2')],fetched_at=datetime.now(timezone.utc))
    def route(self,request):
        """返回有向驾车距离，不表述为步行。"""
        self.calls.append(('route',request))
        return RouteResult(request=request,status='ok',distance_m=1200,duration_s=300,fetched_at=datetime.now(timezone.utc))


def mainland_context():
    """固定虚构人物，仅把城市设为大陆供离线协议测试。"""
    context,state=context_and_ready()
    context.trip.destination='北京'
    return context,state


def test_workflow_bounded_and_observation_reaches_planning():
    """Input：大陆旅行/明确需求/fake工具；Expected Output：有上限的多搜索两向路线、Observation进入Prompt、输入不变；测试目的为不用LLM选择工具且有来源引用。"""
    context,state=mainland_context();before=context.model_dump()
    context.trip.context.required_activities=['展览']
    before=context.model_dump()
    tools=FakeTools();observation=collect_planning_observation(context,tools)
    kinds=[kind for kind,_ in tools.calls]
    assert kinds[0]=='city' and kinds.count('search')<=10 and kinds[-2:]==['route','route']
    assert tools.calls[1][1].keyword=='艺术展览'
    assert len(observation.places)==2
    fake=FakePlanningClient(mutate=lambda data:data['days'][0]['activities'][0].update(place_id='p1'))
    result=run_planning(context,state,fake,observation)
    payload=json.loads(fake.prompts[0].user_prompt)
    assert payload['tool_observation']['places'][0]['place_id']=='p1'
    assert 'API' not in payload['tool_observation']
    assert '不能当作步行/公交时间' in fake.prompts[0].system_prompt
    assert '没有查询地图、搜索' not in fake.prompts[0].system_prompt
    assert result.observation==observation and '高德地图' in result.notice
    assert context.model_dump()==before


def test_unqueried_place_reference_is_rejected():
    """Input：模型返回候选外地点ID；Expected Output：ToolResponseError；测试目的为不让未查询地点冒充工具事实。"""
    context,state=mainland_context();observation=collect_planning_observation(context,FakeTools())
    fake=FakePlanningClient(mutate=lambda d:d['days'][0]['activities'][0].update(place_id='invented'))
    with pytest.raises(ToolResponseError):run_planning(context,state,fake,observation)


def test_all_empty_stops_workflow_without_routes():
    """Input：所有搜索为空；Expected Output：NoPlacesError且无路线；测试目的为明确停止而不伪造候选。"""
    context,_=mainland_context();tools=FakeTools(empty=True)
    with pytest.raises(NoPlacesError):collect_planning_observation(context,tools)
    assert not any(kind=='route' for kind,_ in tools.calls)


def test_api_v1_ready_to_tools_then_model(tmp_path):
    """Input：V1未就绪和就绪请求；Expected Output：先409零工具调用、后规范Observation/来源返回；测试目的为复用门槛及真实API接线且不改变持久数据。"""
    tools=FakeTools();fake=FakePlanningClient(mutate=lambda d:d['days'][0]['activities'][0].update(place_id='p1'))
    with TestClient(create_app(tmp_path/'v1.sqlite3',llm_client=ReadyInterviewClient(),planning_client=fake,place_tools=tools,planning_mode='amap')) as client:
        trip=setup_trip(client);url=f"/api/trips/{trip['trip_id']}"
        assert client.post(url+'/planning').status_code==409 and tools.calls==[]
        client.post(url+'/interview',json={'user_message':'确认'})
        before=client.get(url).json()
        response=client.post(url+'/planning')
        assert response.status_code==200,response.text
        assert response.json()['observation']['source']=='amap'
        assert response.json()['itinerary']['days'][0]['activities'][0]['place_id']=='p1'
        assert response.json()['metrics'] is None
        assert client.get(url).json()==before


@pytest.mark.parametrize('error,status',[(ToolRequestError('高德超时'),502),(UnsupportedDestinationError('非大陆城市'),422),(NoPlacesError('没有地点'),422)])
def test_api_tool_failure_does_not_fallback_to_llm(tmp_path,error,status):
    """Input：超时/不支持/无结果；Expected Output：明确502或422、模型零调用、Trip不变；测试目的为杜绝静默退回V0编造。"""
    tools=FakeTools(error=error);fake=FakePlanningClient()
    with TestClient(create_app(tmp_path/'failure.sqlite3',llm_client=ReadyInterviewClient(),planning_client=fake,place_tools=tools,planning_mode='amap')) as client:
        trip=setup_trip(client);url=f"/api/trips/{trip['trip_id']}"
        client.post(url+'/interview',json={'user_message':'确认'})
        before=client.get(url).json()
        assert client.post(url+'/planning').status_code==status
        assert fake.prompts==[] and client.get(url).json()==before


def test_v1_missing_key_has_safe_error(tmp_path,monkeypatch):
    """Input：启用V1但无高德Key；Expected Output：503且不调用模型；测试目的为不假装已有真实来源。"""
    monkeypatch.delenv('AMAP_WEB_SERVICE_KEY',raising=False)
    fake=FakePlanningClient()
    with TestClient(create_app(tmp_path/'key.sqlite3',llm_client=ReadyInterviewClient(),planning_client=fake,planning_mode='amap')) as client:
        trip=setup_trip(client);url=f"/api/trips/{trip['trip_id']}"
        client.post(url+'/interview',json={'user_message':'确认'})
        response=client.post(url+'/planning')
        assert response.status_code==503 and 'AMAP_WEB_SERVICE_KEY' in response.json()['detail']
        assert fake.prompts==[]


def test_v1_rejects_all_unreferenced_activities():
    """Input：工具成功但模型完全没有地点引用；Expected Output：ToolResponseError；测试目的为不能拿到工具结果后仍完全忽略真实候选。"""
    context,state=mainland_context()
    with pytest.raises(ToolResponseError):run_planning(context,state,FakePlanningClient(),collect_planning_observation(context,FakeTools()))


def test_candidate_cap_and_route_sampling_are_bounded():
    """Input：多关键词、多POI及空路线；Expected Output：最多10搜索/12候选/12条抽样有向路线，缺路线保留状态；测试目的为请求上界与方向明确而不声称完整可行性。"""
    class ManyTools(FakeTools):
        """各搜索返回不同固定候选，路线均为空但无HTTP错误。"""
        def search_places(self,request):
            """构造可控召回，数量不超出单次限制。"""
            self.calls.append(('search',request))
            n=sum(kind=='search' for kind,_ in self.calls)
            return PlaceSearchResult(request=request,status='ok',places=[place(f'p{n}{i}') for i in range(request.limit)],fetched_at=datetime.now(timezone.utc))
        def route(self,request):
            """明确不可达，不伪造数值。"""
            self.calls.append(('route',request))
            return RouteResult(request=request,status='no_route',fetched_at=datetime.now(timezone.utc))
    context,_=mainland_context()
    context.trip.context.required_activities=[f'明确需求{i}' for i in range(15)]
    tools=ManyTools();observation=collect_planning_observation(context,tools)
    assert len(tools.calls)==23 and len(observation.places)==12 and len(observation.routes)==12
    assert '明确需求10' in observation.unqueried_keywords
    assert all(r.status=='no_route' and r.distance_m is None for r in observation.routes)
    pairs={(r.request.origin.place_id,r.request.destination.place_id) for r in observation.routes}
    assert len(pairs)==6
    assert {r.request.mode for r in observation.routes} == {"walking", "transit"}
    assert {a for a,b in pairs} <= {p.place_id for p in observation.places}
