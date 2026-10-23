"""V1.3交通工具与规划引用的离线回归，无真实网络。"""
from datetime import datetime, timezone
import httpx
import pytest
from life_journey.tools import RouteRequest, RouteResult, MainlandCity, ToolResponseError, ToolRequestError
from life_journey.application.planning_observation import collect_routes, MAX_ROUTES, MAX_ROUTE_PAIRS
from life_journey.application.planning import apply_route_evidence, compact_observation, route_id, build_planning_prompt
from life_journey.llm.base import LLMResponseError
from life_journey.schemas.itinerary import Itinerary
from test_amap_tools import place, make_tools, ok
from test_planning_observation import FakeTools, mainland_context
from test_planning import itinerary_payload


def request(mode='walking'):
    """构造固定同城端点。"""
    return RouteRequest(city=MainlandCity(name='北京市', adcode='110000'), origin=place('a'), destination=place('b'), mode=mode)


@pytest.mark.parametrize('mode', ['walking','transit'])
@pytest.mark.parametrize('empty', [False, True])
def test_normalized_modes(monkeypatch, mode, empty):
    """Input：步行/公交成功或空方案；Expected Output：米秒、模式、端点正确或no_route；测试规范化，目的为不泄漏raw JSON。"""
    req = request(mode)
    rows = [] if empty else [{'distance':'1200','duration':'600','walking_distance':'120',
                              'segments':[{'bus':{'buslines':[{'name':'虚构地铁'}]}}], 'unused':'不传递'}]
    captured=[]
    def handler(http_request):
        """仅返回固定高德信封并记录参数。"""
        captured.append(http_request)
        return httpx.Response(200, json=ok(route={('transits' if mode=='transit' else 'paths'):rows}))
    tools=make_tools(monkeypatch,handler)
    try:
        result=tools.route(req)
    finally:
        tools.close()
    assert result.status == ('no_route' if empty else 'ok')
    assert result.mode == mode and result.origin_place_id == 'a' and result.destination_place_id == 'b'
    assert result.duration_s == (None if empty else 600)
    assert 'unused' not in result.model_dump_json()
    assert RouteResult.model_validate_json(result.model_dump_json()) == result
    if mode=='transit':
        assert captured[0].url.params['city'] == '北京市'
        assert result.walking_distance_m == (None if empty else 120)
        assert result.transfer_count == (None if empty else 0)


@pytest.mark.parametrize('lines, expected', [([1,1,1],2), ([2,1],None), ([],None)])
def test_transit_transfer_segments(monkeypatch, lines, expected):
    """Input：三段乘车、备选线路或缺分段；Expected Output：2次换乘或未知；测试分段计数，目的为不把备选线路误算换乘。"""
    segments=[{'bus':{'buslines':[{'name':'虚构线路'} for _ in range(n)]}} for n in lines]
    tools=make_tools(monkeypatch,lambda _:httpx.Response(200,json=ok(route={'transits':[{'duration':'1800','distance':[], 'walking_distance':[], 'segments':segments}]})))
    try:
        result=tools.route(request('transit'))
    finally:
        tools.close()
    assert result.transfer_count == expected
    assert result.distance_m is None and result.walking_distance_m is None


@pytest.mark.parametrize('value',[None, [], '', True, '-1', '3.5', {}])
@pytest.mark.parametrize('mode',['walking','transit'])
def test_invalid_duration_fails_clearly(monkeypatch, value, mode):
    """Input：缺失/数组/空值/错误类型时长；Expected Output：安全ToolResponseError；测试原始字段边界，目的为不制造零时长。"""
    key='transits' if mode=='transit' else 'paths'
    tools=make_tools(monkeypatch,lambda _:httpx.Response(200,json=ok(route={key:[{'distance':'200','duration':value}]})))
    try:
        with pytest.raises(ToolResponseError):
            tools.route(request(mode))
    finally:
        tools.close()


def test_budget_and_failure_isolation():
    """Input：12候选、所有请求失败；Expected Output：最多6组合12请求且均unknown；测试预算及隔离，目的为不出现N×N或中断规划。"""
    class FailingTools(FakeTools):
        """只记录并抛出安全工具错误。"""
        def route(self, request):
            """模拟独立请求失败，不访问网络。"""
            self.calls.append(('route',request))
            raise ToolRequestError('固定失败')
    tools=FailingTools()
    result=collect_routes(request().city,[place(str(i)) for i in range(12)],tools)
    assert len(result)==MAX_ROUTES==12
    assert len({(r.origin_place_id,r.destination_place_id) for r in result})==MAX_ROUTE_PAIRS
    assert all(r.status=='unknown' and r.duration_s is None for r in result)
    assert {r.mode for r in result}=={'walking','transit'}


def test_distance_selects_primary_without_removing_preferences():
    """Input：近/远端点和固定候选来源；Expected Output：近步行远公交且输入不变；测试模式选择，目的为距离只控制查询而非删除偏好。"""
    origin=place('a');near=place('b');far=place('c')
    far.location.longitude += 0.1
    tools=FakeTools()
    before=far.model_dump()
    assert collect_routes(request().city,[origin,near],tools)[0].mode=='walking'
    assert collect_routes(request().city,[origin,far],tools)[0].mode=='transit'
    assert far.model_dump()==before


def itinerary_with_pair(reference=None, text='参考活动'):
    """同日两个具体地点，供有向引用检查使用。"""
    context,_=mainland_context()
    payload=itinerary_payload(context.trip)
    activity=payload['days'][0]['activities'][0]
    activity['place_id']='a'
    payload['days'][0]['activities'].append({**activity,'place_id':'b','description':text,'route_from_previous':reference})
    return Itinerary.model_validate_json(__import__('json').dumps(payload))


@pytest.mark.parametrize('mode,text,accepted', [('driving','步行10分钟',False),('walking','步行10分钟',True),('transit','地铁10分钟',True),('walking','步行99分钟',False)])
def test_route_mode_and_minutes(mode,text,accepted):
    """Input：指定模式和交通文案；Expected Output：只接受对应模式/米秒；测试路线引用，目的为不把驾车当步行。"""
    from life_journey.tools.schemas import PlanningObservation
    route=RouteResult(request=request(mode),status='ok',duration_s=600,distance_m=1200,fetched_at=datetime.now(timezone.utc))
    obs=PlanningObservation(city=request().city,searches=[],places=[place('a'),place('b')],routes=[route])
    itinerary=itinerary_with_pair(route_id(route),text)
    if accepted:
        apply_route_evidence(itinerary,obs)
        assert '10分钟' in itinerary.days[0].activities[1].route_note
    else:
        with pytest.raises(LLMResponseError):
            apply_route_evidence(itinerary,obs)



def test_unqueried_route_cannot_claim_verified():
    """Input：无路线证据却写已验证步行10分钟；Expected Output：明确拒绝；测试无证据声明，目的为禁止模型补造交通。"""
    from life_journey.tools.schemas import PlanningObservation
    obs=PlanningObservation(city=request().city,searches=[],places=[place('a'),place('b')],routes=[])
    with pytest.raises(LLMResponseError):
        apply_route_evidence(itinerary_with_pair(text='已验证步行10分钟可达'),obs)


def test_prompt_preserves_relevance_and_mode_rules():
    """Input：明确需求及交通Observation；Expected Output：优先需求、模式隔离及未知边界存在；测试Prompt契约，目的为不以最短距离覆盖用户偏好。"""
    from life_journey.application.planning_observation import collect_planning_observation
    context,_=mainland_context()
    before=context.model_dump()
    observation=collect_planning_observation(context,FakeTools())
    prompt=build_planning_prompt(context,observation)
    assert 'required activity优先于单纯最短距离' in prompt.system_prompt
    assert 'unknown、no_route不得补造' in prompt.system_prompt
    assert context.model_dump()==before
    assert all('route_id' in r for r in compact_observation(observation)['routes'])


def test_api_route_failure_still_plans(tmp_path):
    """Input：真实API链路和失败路线fake；Expected Output：200及unknown交通而Trip不变；测试失败隔离，目的为路线失败不拖垮整次规划。"""
    from fastapi.testclient import TestClient
    from life_journey.api import create_app
    from test_planning import FakePlanningClient, ReadyInterviewClient, setup_trip
    class BrokenRoutes(FakeTools):
        """POI正常，路线安全失败。"""
        def route(self, request):
            """模拟超时，无隐藏重试。"""
            raise ToolRequestError('高德请求超时')
    fake=FakePlanningClient(mutate=lambda d:d['days'][0]['activities'][0].update(place_id='p1'))
    with TestClient(create_app(tmp_path/'route.sqlite3',llm_client=ReadyInterviewClient(),planning_client=fake,place_tools=BrokenRoutes(),planning_mode='amap')) as client:
        trip=setup_trip(client);url=f"/api/trips/{trip['trip_id']}"
        client.post(url+'/interview',json={'user_message':'确认'})
        before=client.get(url).json()
        response=client.post(url+'/planning')
        assert response.status_code==200,response.text
        assert all(r['status']=='unknown' for r in response.json()['observation']['routes'])
        assert len(fake.prompts)==1 and client.get(url).json()==before


@pytest.mark.parametrize('status',['unknown','no_route'])
def test_unknown_and_reverse_refs(status):
    """Input：未知/无路线及反向引用；Expected Output：无数值保证且反向不匹配；测试方向和未知边界，目的为防止证据串用。"""
    from life_journey.tools.schemas import PlanningObservation
    route=RouteResult(request=request(),status=status,fetched_at=datetime.now(timezone.utc))
    obs=PlanningObservation(city=request().city,searches=[],places=[place('a'),place('b')],routes=[route])
    itinerary=itinerary_with_pair(route_id(route))
    apply_route_evidence(itinerary,obs)
    assert '需核实' in itinerary.days[0].activities[1].route_note
    with pytest.raises(LLMResponseError):
        apply_route_evidence(itinerary_with_pair(route_id(route),'步行10分钟'),obs)
    itinerary.days[0].activities[0].place_id='b'
    apply_route_evidence(itinerary,obs)
    assert itinerary.days[0].activities[1].route_from_previous is None
    assert '需核实' in itinerary.days[0].activities[1].route_note


def test_backend_matches_reference_instead_of_model_guess():
    """Input：模型填错或省略路线ID；Expected Output：后端按同日真实端点匹配；测试引用生成，目的为既不信任模型标识符也不伪造路线。"""
    from life_journey.tools.schemas import PlanningObservation
    route=RouteResult(request=request(),status='ok',duration_s=600,distance_m=1200,fetched_at=datetime.now(timezone.utc))
    obs=PlanningObservation(city=request().city,searches=[],places=[place('a'),place('b')],routes=[route])
    before=obs.model_dump()
    for reference in (None, 'made-up-route'):
        itinerary=itinerary_with_pair(reference, '步行10分钟')
        apply_route_evidence(itinerary,obs)
        assert itinerary.days[0].activities[0].route_from_previous is None
        assert itinerary.days[0].activities[1].route_from_previous==route_id(route)
        assert '10分钟' in itinerary.days[0].activities[1].route_note
    assert obs.model_dump()==before
