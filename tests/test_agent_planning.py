"""实际LangGraph离线执行；不调用高德/DeepSeek，不只测试手写循环。"""
import json
from datetime import datetime,timezone
import pytest
from fastapi.testclient import TestClient
from life_journey.application.agent_planning import run_agent_planning, AGENT_SYSTEM_PROMPT
from life_journey.schemas.agent import AgentDecision, AgentToolCall, AgentBudget
from life_journey.tools import NoPlacesError, ToolRequestError, RouteResult
from life_journey.llm.base import LLMResponseError, LLMRequestError
from test_planning_observation import mainland_context, FakeTools
from test_planning import FakePlanningClient,ReadyInterviewClient,setup_trip
from life_journey.api import create_app


def call(name='search_places',args=None,id='c1'):
    """构造跨Provider的固定函数请求，不生成随机测试ID。"""
    return AgentToolCall(call_id=id,name=name,arguments=json.dumps(args if args is not None else {'city':'北京','keyword':'艺术展','limit':2},ensure_ascii=False))


class ScriptedAgent:
    """按固定决定序列驱动真实状态图，并记录模型收到的证据。"""
    def __init__(self,*decisions):
        self.decisions=list(decisions);self.prompts=[]
    def decide(self,prompt):
        """无网络，未提供后续决定时结束以暴露图的路由行为。"""
        self.prompts.append(prompt)
        return self.decisions.pop(0) if self.decisions else AgentDecision(ready_to_plan=True)


def planner(**changes):
    """最终输出仍由已有fake和完整领域校验构造。"""
    return FakePlanningClient(mutate=lambda d:[a.update(**{'place_id':'p1',**changes}) for day in d['days'] for a in day['activities']])


def metrics(response):
    """解码兼容API的debug字符串，不引入新顶层响应字段。"""
    return json.loads(response.metrics['agent_run'])


def test_graph_tools_then_agent_then_finalize_preserves_input():
    """Input：明确必看展览及一次工具决定；Expected Output：真实图tools→agent→finalize且完整行程/输入不变；测试图路由与证据消费，目的为不以固定检索伪装Agent。"""
    ctx,state=mainland_context();ctx.trip.context.required_activities=['艺术展']
    before=(ctx.model_dump(),state.model_dump())
    agent=ScriptedAgent(AgentDecision(tool_calls=[call()]))
    tools=FakeTools();final=planner()
    result=run_agent_planning(ctx,state,agent,final,tools)
    m=metrics(result)
    assert m['tool_call_count']==1 and m['decision_count']==2 and m['stop_reason']=='sufficient_evidence'
    assert m['executed_tool_calls']==1 and m['place_count']==2 and m['route_count']==0
    assert tools.calls[1][1].keyword=='艺术展'
    assert len(final.prompts)==1 and len(agent.prompts)==2
    assert '艺术展' in agent.prompts[0].messages[0]['content']
    assert agent.prompts[1].messages[-1]['type']=='function_call_output'
    assert result.observation.places[0].source_keywords==['艺术展']
    assert (ctx.model_dump(),state.model_dump())==before


def test_direct_finalize_without_evidence_fails_without_model_fallback():
    """Input：首轮直接finalize但无地点；Expected Output：NoPlacesError且最终模型零调用；测试直接结束分支，目的为无证据不能退回V0编造。"""
    ctx,state=mainland_context();final=planner();tools=FakeTools()
    with pytest.raises(NoPlacesError):run_agent_planning(ctx,state,ScriptedAgent(),final,tools)
    assert final.prompts==[] and [kind for kind,_ in tools.calls]==['city']


@pytest.mark.parametrize('name,mode',[('get_walking_route','walking'),('get_transit_route','transit'),('get_driving_route','driving')])
def test_multiple_tools_and_route_modes(name,mode):
    """Input：搜索后指定步行/公交/驾车；Expected Output：模型选择模式原样传入且Observation到finalize；测试多轮工具，目的为不在Python偷偷决定模式。"""
    ctx,state=mainland_context()
    agent=ScriptedAgent(AgentDecision(tool_calls=[call()]),AgentDecision(tool_calls=[call(name,{'origin_place_id':'p1','destination_place_id':'p2'},'c2')]))
    result=run_agent_planning(ctx,state,agent,planner(),FakeTools())
    assert result.observation.routes[0].mode==mode
    assert metrics(result)['tool_call_count']==2
    assert json.loads(agent.prompts[-1].messages[-1]['output'])['status']=='ok'


@pytest.mark.parametrize('status',['no_route','unknown'])
def test_unknown_route_is_not_fabricated(status):
    """Input：路线返回无路/未知；Expected Output：保留状态与空数值后继续finalize；测试规范化交通，目的为不补造可达性。"""
    class EmptyRoutes(FakeTools):
        """只返回缺乏交通证据的规范化结果。"""
        def route(self,request):
            """固定无数值，保持端点和模式。"""
            return RouteResult(request=request,status=status,fetched_at=datetime.now(timezone.utc))
    ctx,state=mainland_context()
    agent=ScriptedAgent(AgentDecision(tool_calls=[call()]),AgentDecision(tool_calls=[call('get_transit_route',{'origin_place_id':'p1','destination_place_id':'p2'},'r')]))
    result=run_agent_planning(ctx,state,agent,planner(),EmptyRoutes())
    assert result.observation.routes[0].status==status and result.observation.routes[0].duration_s is None


@pytest.mark.parametrize('name,args,error',[
    ('search_places',{'city':'北京','keyword':'','limit':2},'invalid_arguments'),
    ('search_places',{'city':'上海','keyword':'艺术展','limit':2},'city_out_of_scope'),
    ('search_places',{'city':'北京','keyword':'艺术展','limit':3},'invalid_arguments'),
    ('get_walking_route',{'origin_place_id':'made-up','destination_place_id':'p2'},'unknown_place_id'),
    ('get_transit_route',{'origin_place_id':'p1','destination_place_id':'p1'},'invalid_arguments'),
    ('unsupported_tool',{},'unsupported_tool'),
])
def test_invalid_arguments_return_structured_errors(name,args,error):
    """Input：空词/跨城/超limit/伪造ID/相同端点/未知工具后修正；Expected Output：结构化error后正常结束；测试参数保护，目的为单个非法调用不崩图。"""
    ctx,state=mainland_context();tools=FakeTools()
    agent=ScriptedAgent(AgentDecision(tool_calls=[call(name,args)]),AgentDecision(tool_calls=[call(id='valid')]))
    result=run_agent_planning(ctx,state,agent,planner(),tools)
    assert metrics(result)['actions'][0]['error_code']==error
    assert json.loads(agent.prompts[1].messages[-1]['output'])['status']=='error'
    assert metrics(result)['executed_tool_calls']==1


def test_invalid_json_arguments_can_be_corrected():
    """Input：非JSON arguments后有效查询；Expected Output：invalid_arguments并继续；测试原生协议边界，目的为错误参数不成为未处理异常。"""
    ctx,state=mainland_context()
    agent=ScriptedAgent(AgentDecision(tool_calls=[AgentToolCall(call_id='bad',name='search_places',arguments='not json')]),AgentDecision(tool_calls=[call()]))
    result=run_agent_planning(ctx,state,agent,planner(),FakeTools())
    assert metrics(result)['actions'][0]['error_code']=='invalid_arguments'


def test_failure_then_different_query_continues():
    """Input：第一次POI超时后换词；Expected Output：安全error随后成功，零隐藏重试；测试恢复决策，目的为错误由Agent观察而非重试编造。"""
    class OnceFail(FakeTools):
        """按词失败，不做Provider重试。"""
        def search_places(self,request):
            """旧词失败，新词交给现有fake。"""
            if request.keyword=='旧词':raise ToolRequestError('safe failure')
            return super().search_places(request)
    ctx,state=mainland_context()
    agent=ScriptedAgent(AgentDecision(tool_calls=[call(args={'city':'北京','keyword':'旧词','limit':2})]),AgentDecision(tool_calls=[call(id='new')]))
    result=run_agent_planning(ctx,state,agent,planner(),OnceFail())
    assert [a['status'] for a in metrics(result)['actions']]==['error','ok']
    assert metrics(result)['executed_tool_calls']==2


def test_route_exception_records_unknown_and_continues():
    """Input：POI正常而路线异常；Expected Output：unknown带固定错误分类且仍有行程；测试单路失败，目的为保留证据缺口。"""
    class BrokenRoutes(FakeTools):
        """路线安全失败，不向状态暴露异常内容。"""
        def route(self,request):
            """固定工具异常。"""
            raise ToolRequestError('secret must not leak')
    ctx,state=mainland_context()
    agent=ScriptedAgent(AgentDecision(tool_calls=[call()]),AgentDecision(tool_calls=[call('get_walking_route',{'origin_place_id':'p1','destination_place_id':'p2'},'r')]))
    result=run_agent_planning(ctx,state,agent,planner(),BrokenRoutes())
    assert result.observation.routes[0].status=='unknown'
    assert 'secret must not leak' not in json.dumps(metrics(result))


def test_repeated_call_returns_cache_and_stops():
    """Input：同工具同参数反复请求；Expected Output：仅1次真实工具、缓存返回并repeated_tool_calls停止；测试防循环，目的为不能靠新call_id绕过参数去重。"""
    ctx,state=mainland_context()
    agent=ScriptedAgent(*[AgentDecision(tool_calls=[call(id=f'c{i}')]) for i in range(8)])
    tools=FakeTools();result=run_agent_planning(ctx,state,agent,planner(),tools)
    m=metrics(result)
    assert m['stop_reason']=='repeated_tool_calls' and m['tool_call_count']==3
    assert m['executed_tool_calls']==1 and len(agent.prompts)==3
    assert [a['cached'] for a in m['actions']]==[False,True,True]
    assert len([c for c in tools.calls if c[0]=='search'])==1


def test_total_and_per_tool_budget():
    """Input：三次不同词及search上限1/total上限2；Expected Output：第二次受限后强制finalize；测试预算，目的为非法/拒绝调用也不能无限循环。"""
    ctx,state=mainland_context()
    agent=ScriptedAgent(*[AgentDecision(tool_calls=[call(args={'city':'北京','keyword':f'词{i}','limit':2},id=f'c{i}')]) for i in range(3)])
    result=run_agent_planning(ctx,state,agent,planner(),FakeTools(),budget=AgentBudget(max_tool_calls=2,max_search_calls=1))
    m=metrics(result)
    assert m['tool_call_count']==2 and m['stop_reason']=='tool_budget_exhausted'
    assert m['actions'][1]['error_code']=='search_or_candidate_budget_exhausted'
    assert m['executed_tool_calls']==1


def test_decision_and_recursion_guards():
    """Input：单决策预算或人为极低recursion；Expected Output：前者finalize，后者安全失败；测试双重终止，目的为图不会无限调用。"""
    ctx,state=mainland_context()
    result=run_agent_planning(ctx,state,ScriptedAgent(AgentDecision(tool_calls=[call()])),planner(),FakeTools(),budget=AgentBudget(max_decisions=1))
    assert metrics(result)['stop_reason']=='decision_budget_exhausted'
    with pytest.raises(LLMResponseError,match='recursion limit'):
        run_agent_planning(ctx,state,ScriptedAgent(AgentDecision(tool_calls=[call()])),planner(),FakeTools(),budget=AgentBudget(recursion_limit=1))


def test_excluded_query_blocked_and_candidate_not_arranged():
    """Input：排除咖啡却请求其别名，再请求展览；Expected Output：咖啡不搜索、最终只用展览候选；测试排除边界，目的为模型不能正向查询明确拒绝内容。"""
    ctx,state=mainland_context();ctx.trip.context.excluded_activities=['咖啡馆']
    agent=ScriptedAgent(AgentDecision(tool_calls=[call(args={'city':'北京','keyword':'咖啡店','limit':2})]),AgentDecision(tool_calls=[call(id='valid')]))
    tools=FakeTools();result=run_agent_planning(ctx,state,agent,planner(),tools)
    assert metrics(result)['actions'][0]['error_code']=='excluded_keyword'
    assert all(req.keyword!='咖啡店' for kind,req in tools.calls if kind=='search')
    assert result.itinerary.days[0].activities[0].place_id=='p1'


@pytest.mark.parametrize('changes,error',[
    ({'place_id':'invented'},'未查询'),
    ({'description':'已确认营业，可以放心前往。'},'已确认营业'),
    ({'description':'步行10分钟到达。'},'交通时间'),
])
def test_finalize_retains_existing_fact_guards(changes,error):
    """Input：模型编造地点/unknown营业保证/无路线分钟；Expected Output：原V1守卫拒绝；测试finalize复用，目的为LangGraph不能削弱事实边界。"""
    from life_journey.tools import ToolResponseError
    ctx,state=mainland_context()
    fake=FakePlanningClient(mutate=lambda d:[a.update(**{'place_id':'p1',**changes}) for day in d['days'] for a in day['activities']])
    with pytest.raises((LLMResponseError,ToolResponseError),match=error):
        run_agent_planning(ctx,state,ScriptedAgent(AgentDecision(tool_calls=[call()])),fake,FakeTools())


def test_driving_evidence_does_not_allow_walking_minutes():
    """Input：仅驾车证据却声称连续活动步行时间；Expected Output：LLMResponseError；测试模式隔离，目的为不因Agent而串用交通事实。"""
    ctx,state=mainland_context()
    def mutate(data):
        """构造同日两点并使用错误模式文案。"""
        for day in data['days']:
            day['activities'][0]['place_id']='p1'
            day['activities'].append({**day['activities'][0],'place_id':'p2','description':'步行5分钟到达。'})
    agent=ScriptedAgent(AgentDecision(tool_calls=[call()]),AgentDecision(tool_calls=[call('get_driving_route',{'origin_place_id':'p1','destination_place_id':'p2'},'r')]))
    with pytest.raises(LLMResponseError,match='对应模式'):
        run_agent_planning(ctx,state,agent,FakePlanningClient(mutate=mutate),FakeTools())


@pytest.mark.parametrize('mode',['amap','agent'])
def test_api_modes_and_response_contract(tmp_path,mode):
    """Input：相同Planning API分别使用amap/agent；Expected Output：V1不调用Agent，V2走图，顶层契约一致；测试兼容性，目的为前端无需改API。"""
    agent=ScriptedAgent(AgentDecision(tool_calls=[call()]))
    with TestClient(create_app(tmp_path/'modes.sqlite3',llm_client=ReadyInterviewClient(),planning_client=planner(),place_tools=FakeTools(),planning_mode=mode,agent_client=agent)) as client:
        trip=setup_trip(client);url=f"/api/trips/{trip['trip_id']}"
        assert client.post(url+'/planning').status_code==409
        client.post(url+'/interview',json={'user_message':'确认'})
        before=client.get(url).json()
        response=client.post(url+'/planning')
        assert response.status_code==200,response.text
        assert set(response.json())=={'itinerary','notice','observation','metrics'}
        assert response.json()['metrics'] is None and client.get(url).json()==before
        assert bool(agent.prompts)==(mode=='agent')


def test_trace_omits_arbitrary_keyword_and_provider_errors(caplog):
    """Input：搜索词含虚构隐私内容；Expected Output：指标/日志仅长度与固定分类；测试脱敏可观察性，目的为不记录用户词句或Key。"""
    ctx,state=mainland_context();private='虚构私人消息不可记录'
    agent=ScriptedAgent(AgentDecision(tool_calls=[call(args={'city':'北京','keyword':private,'limit':2})]))
    with caplog.at_level('INFO',logger='life_journey.application.agent_tools'):
        result=run_agent_planning(ctx,state,agent,planner(),FakeTools())
    assert private not in json.dumps(metrics(result),ensure_ascii=False) and private not in caplog.text
    assert 'keyword_length' in caplog.text and 'chain-of-thought' not in result.metrics['agent_run']


def test_no_result_then_retry_new_keyword():
    """Input：第一次空结果后主动换词；Expected Output：no_result传回Agent后正常规划；测试证据不足反馈，目的为不静默补造候选。"""
    class EmptyFirst(FakeTools):
        """首词空结果，第二词复用正常候选。"""
        def search_places(self,request):
            """按明确输入产生固定空/非空结果。"""
            from life_journey.tools import PlaceSearchResult
            if request.keyword=='空词':return PlaceSearchResult(request=request,status='empty',places=[],fetched_at=datetime.now(timezone.utc))
            return super().search_places(request)
    ctx,state=mainland_context()
    agent=ScriptedAgent(AgentDecision(tool_calls=[call(args={'city':'北京','keyword':'空词','limit':2})]),AgentDecision(tool_calls=[call(id='new')]))
    result=run_agent_planning(ctx,state,agent,planner(),EmptyFirst())
    assert [a['status'] for a in metrics(result)['actions']]==['no_result','ok']


def test_batch_calls_and_candidate_cap():
    """Input：一轮两个搜索和候选上限2；Expected Output：只执行首搜索且全部calls均有输出；测试批次协议及池上限，目的为不丢配对/不膨胀候选。"""
    ctx,state=mainland_context()
    agent=ScriptedAgent(AgentDecision(tool_calls=[call(),call(args={'city':'北京','keyword':'建筑','limit':2},id='c2')]))
    result=run_agent_planning(ctx,state,agent,planner(),FakeTools(),budget=AgentBudget(max_candidates=2))
    m=metrics(result)
    assert m['place_count']==2 and m['executed_tool_calls']==1
    assert m['actions'][1]['error_code']=='search_or_candidate_budget_exhausted'
    history=agent.prompts[-1].messages[1:]
    assert len([m for m in history if m['type']=='function_call'])==2
    assert len([m for m in history if m['type']=='function_call_output'])==2


def test_route_and_mode_budgets():
    """Input：同方向两个交通模式而总路线预算1；Expected Output：只查一次、第二次结构化budget错误；测试route配额，目的为不因换模式绕过预算。"""
    ctx,state=mainland_context()
    agent=ScriptedAgent(AgentDecision(tool_calls=[call()]),AgentDecision(tool_calls=[
        call('get_walking_route',{'origin_place_id':'p1','destination_place_id':'p2'},'w'),
        call('get_transit_route',{'origin_place_id':'p1','destination_place_id':'p2'},'t')]))
    result=run_agent_planning(ctx,state,agent,planner(),FakeTools(),budget=AgentBudget(max_route_calls=1))
    assert len(result.observation.routes)==1
    assert metrics(result)['actions'][-1]['error_code']=='route_budget_exhausted'


def test_duplicate_normalizes_city_alias_and_keyword_whitespace():
    """Input：相同词城市别名/首尾空白变化；Expected Output：第二次缓存不发HTTP；测试canonical参数，目的为格式变化不能绕过去重。"""
    ctx,state=mainland_context()
    agent=ScriptedAgent(AgentDecision(tool_calls=[call()]),AgentDecision(tool_calls=[call(args={'city':'北京市','keyword':' 艺术展 ','limit':2},id='new')]))
    result=run_agent_planning(ctx,state,agent,planner(),FakeTools())
    assert metrics(result)['actions'][1]['cached'] and metrics(result)['executed_tool_calls']==1


def test_excluded_returned_place_filtered_before_finalize():
    """Input：展览搜索结果混入被明确排除的店；Expected Output：该POI不入候选池、不可安排；测试结果侧过滤，目的为合法关键词也不能引入明确排除类别。"""
    class Mixed(FakeTools):
        """固定返回一项不应安排的候选。"""
        def search_places(self,request):
            """模拟供应商结果混入咖啡馆。"""
            result=super().search_places(request)
            result.places[1].name='咖啡馆'
            return result
    ctx,state=mainland_context();ctx.trip.context.excluded_activities=['咖啡店']
    result=run_agent_planning(ctx,state,ScriptedAgent(AgentDecision(tool_calls=[call()])),planner(),Mixed())
    assert [p.place_id for p in result.observation.places]==['p1']


def test_agent_provider_error_and_reused_call_id_fail_clearly():
    """Input：Provider错误或重复call_id；Expected Output：安全明确失败、最终模型不调用；测试协议异常，目的为不把无效决策当工具结果。"""
    class BrokenAgent:
        """只模拟决策传输失败。"""
        def decide(self,prompt):
            """无网络，不回显敏感响应。"""
            raise LLMRequestError('Agent请求失败')
    ctx,state=mainland_context();final=planner()
    with pytest.raises(LLMRequestError):run_agent_planning(ctx,state,BrokenAgent(),final,FakeTools())
    agent=ScriptedAgent(AgentDecision(tool_calls=[call()]),AgentDecision(tool_calls=[call()]))
    with pytest.raises(LLMResponseError,match='call_id'):run_agent_planning(ctx,state,agent,final,FakeTools())
    assert final.prompts==[]


def test_empty_evidence_at_budget_exhaustion_does_not_plan():
    """Input：唯一搜索失败且预算耗尽；Expected Output：NoPlacesError而非空知识行程；测试预算强停缺口，目的为退出也不能虚构证据。"""
    ctx,state=mainland_context();final=planner()
    with pytest.raises(NoPlacesError):
        run_agent_planning(ctx,state,ScriptedAgent(AgentDecision(tool_calls=[call()])),final,FakeTools(empty=True),budget=AgentBudget(max_tool_calls=1))
    assert final.prompts==[]


def test_langsmith_environment_does_not_enable_external_trace(monkeypatch):
    """Input：开发机意外启用LANGSMITH_TRACING；Expected Output：图仍离线通过且无上传；测试追踪隔离，目的为不自动发送用户状态。"""
    monkeypatch.setenv('LANGSMITH_TRACING','true')
    monkeypatch.setenv('LANGSMITH_API_KEY','offline-fake')
    import requests
    def blocked(*args,**kwargs):
        """外部追踪若被调用则立即失败。"""
        raise AssertionError('不允许外部追踪')
    monkeypatch.setattr(requests.Session,'request',blocked)
    ctx,state=mainland_context()
    result=run_agent_planning(ctx,state,ScriptedAgent(AgentDecision(tool_calls=[call()])),planner(),FakeTools())
    assert result.itinerary.trip_id==ctx.trip.trip_id


def test_finalize_error_keeps_safe_action_trace():
    """Input：取证成功但最终模型伪造候选ID；Expected Output：仍拒绝且异常附安全行动指标；测试失败可观察性，目的为smoke失败也能定位取证还是finalize。"""
    from life_journey.tools import ToolResponseError
    ctx,state=mainland_context()
    with pytest.raises(ToolResponseError) as exc:
        run_agent_planning(ctx,state,ScriptedAgent(AgentDecision(tool_calls=[call()])),planner(place_id='outside'),FakeTools())
    m=exc.value.agent_run_metrics
    assert m.stop_reason=='finalize_rejected' and m.tool_call_count==1 and m.actions[0].tool_name=='search_places'


def test_api_agent_debug_metrics_keeps_existing_schema(tmp_path):
    """Input：agent模式debug=true的原Planning端点；Expected Output：既有metrics字段内有安全AgentRunMetrics；测试调试接口，目的为不添加前端不认识的顶层字段。"""
    agent=ScriptedAgent(AgentDecision(tool_calls=[call()]))
    with TestClient(create_app(tmp_path/'debug.sqlite3',llm_client=ReadyInterviewClient(),planning_client=planner(),place_tools=FakeTools(),planning_mode='agent',agent_client=agent)) as client:
        trip=setup_trip(client);url=f"/api/trips/{trip['trip_id']}"
        client.post(url+'/interview',json={'user_message':'确认'})
        response=client.post(url+'/planning?debug=true')
        assert response.status_code==200,response.text
        m=json.loads(response.json()['metrics']['agent_run'])
        assert m['tool_call_count']==1 and m['place_count']==2
        assert 'messages' not in m and 'context' not in m


def test_fixed_smoke_data_does_not_use_database():
    """Input：两个固定真实smoke场景；Expected Output：虚构人物/固定ID/大陆Setup及独立Context；测试手动入口数据边界，目的为不使用正式用户数据或互相污染。"""
    from life_journey.evaluation.agent_smoke import smoke_context
    first,state=smoke_context('北京','architecture_coffee')
    second,_=smoke_context('北京','architecture_art')
    assert first.trip.trip_id=='trip_agent_smoke' and state.ready_to_plan
    assert first.trip.context.activity_preferences!=second.trip.context.activity_preferences
    first.trip.context.activity_preferences.append('只修改本实例')
    assert '只修改本实例' not in second.trip.context.activity_preferences


def test_agent_prompt_selects_only_trip_participants():
    """Input：调用者传入额外未参与Person；Expected Output：Agent消息不含该人物且原对象不变；测试公共入口选择边界，目的为只发送本次相关资料。"""
    from life_journey.schemas import Person
    ctx,state=mainland_context()
    ctx.participants.append(Person(person_id='not_in_trip',name='不得发送的未参与者'))
    before=ctx.model_dump()
    agent=ScriptedAgent(AgentDecision(tool_calls=[call()]))
    run_agent_planning(ctx,state,agent,planner(),FakeTools())
    assert all('不得发送的未参与者' not in json.dumps(p.messages,ensure_ascii=False) for p in agent.prompts)
    assert ctx.model_dump()==before
