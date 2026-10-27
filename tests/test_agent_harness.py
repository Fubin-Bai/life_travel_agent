"""运行控制层离线测试；真实LangGraph配合fake领域依赖，不调用外部服务。"""
import json
import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient
from life_journey.harness.runtime import AgentHarness,HarnessFailure,call_fingerprint
from life_journey.harness.policy import HarnessPolicy
from life_journey.harness.hooks import HarnessHook
from life_journey.harness.schemas import TraceEvent
from life_journey.application.agent_planning import run_agent_planning,AgentState
from life_journey.application.memory import MemoryStore
from life_journey.schemas.agent import AgentDecision,SearchPlacesArguments,AgentBudget
from life_journey.schemas.validation import ReplanPatch
from life_journey.llm.base import LLMRequestError,LLMResponseError
from life_journey.tools import ToolRequestError
from life_journey.api import create_app
from test_agent_planning import ScriptedAgent,call,planner
from test_planning_observation import mainland_context,FakeTools
from test_constraint_replanning import fixture,RepairClient
from test_memory_rag import FakeEmbedding,candidate
from test_planning import ReadyInterviewClient,setup_trip


def basic(*,runtime=None,agent=None,tools=None,hooks=(),policy=None):
    """固定已就绪旅行，用于比较运行控制变化与业务结果。"""
    ctx,state=mainland_context()
    runtime=runtime or AgentHarness(ctx.trip.trip_id,policy=policy,hooks=hooks)
    result=run_agent_planning(ctx,state,agent or ScriptedAgent(AgentDecision(tool_calls=[call()])),planner(),tools or FakeTools(),harness=runtime)
    return result,runtime


def types(runtime):
    """只取标准事件名，不读取Prompt或原始工具输出。"""
    return [e.event_type for e in runtime.events]


def test_lifecycle_counts_and_state_separation():
    """Input：一次搜索后结束的真实图；Expected Output：完整生命周期、模型3次/工具1次且State无runtime字段；测试职责分离，目的为计数只有一个事实源。"""
    result,runtime=basic();c=runtime.context
    assert c.status=='completed' and c.started_at<=c.finished_at and c.current_graph_node is None
    assert c.tool_call_count==1 and c.executed_tool_calls==1 and c.model_call_count==3 and c.decision_count==2
    assert c.stop_reason=='sufficient_evidence' and c.timing_ms['total']>=0
    assert types(runtime)[0]=='RUN_STARTED' and types(runtime)[-1]=='RUN_COMPLETED'
    assert types(runtime).count('NODE_ENTERED')==types(runtime).count('NODE_EXITED')
    assert 'FINALIZED' in types(runtime)
    assert not {'tool_call_count','tool_counts','used_tool_arguments','replan_round','stop_reason','errors'} & AgentState.__annotations__.keys()
    assert json.loads(result.metrics['harness_summary'])['run_id']==c.run_id
    with pytest.raises(ValueError):runtime.run(lambda h:result)


@pytest.mark.parametrize('values',[{'max_tool_calls':0},{'max_candidates':13},{'max_replan_rounds':3},{'memory_top_k':11},{'max_run_seconds':float('nan')},{'memory_failure_mode':'silent'}])
def test_invalid_policy(values):
    """Input：越界预算、无效超时或静默降级策略；Expected Output：Schema拒绝；测试集中配置，目的为无非法无限预算。"""
    with pytest.raises(ValidationError):HarnessPolicy(**values)


def test_policy_legacy_alias_environment_and_frozen(monkeypatch):
    """Input：旧AgentBudget与少量env覆盖；Expected Output：同一定义、明确覆盖且不可变；测试兼容配置，目的为默认值不再散落。"""
    assert AgentBudget is HarnessPolicy
    monkeypatch.setenv('LIFE_JOURNEY_MAX_TOOL_CALLS','3');monkeypatch.setenv('LIFE_JOURNEY_MAX_RUN_SECONDS','12.5')
    policy=HarnessPolicy.from_env();assert policy.max_tool_calls==3 and policy.max_run_seconds==12.5
    assert policy.graph_recursion_limit(True)==policy.recursion_limit+9
    with pytest.raises(ValidationError):policy.max_tool_calls=4
    monkeypatch.setenv('LIFE_JOURNEY_MAX_TOOL_CALLS','private-invalid')
    with pytest.raises(ValueError,match='Harness预算配置无效'):HarnessPolicy.from_env()


class Recorder(HarnessHook):
    """记录hooks顺序，并尝试修改观察快照以验证隔离。"""
    def __init__(self,label='a',sink=None):self.calls=[];self.label=label;self.sink=sink if sink is not None else []
    def __getattribute__(self,name):
        """测试中统一捕获十二个显式hook名称。"""
        if name in {'before_run','after_run','before_model','after_model','before_tool','after_tool','before_memory_retrieval','after_memory_retrieval','before_validate','after_validate','before_replan','after_replan'}:
            def record(context,event):
                """只接收副本，不接收模型或数据库对象。"""
                self.calls.append(name);self.sink.append((self.label,name));context.warnings.append('mutation-must-not-escape')
                if event:event.sanitized_args['keyword_length']=999
            return record
        return super().__getattribute__(name)


def test_multiple_noop_and_noncritical_hooks_are_isolated():
    """Input：两个记录hook及失败的非critical hook；Expected Output：按顺序执行、主结果不变且安全warning；测试组合与故障隔离，目的为观察不改变业务。"""
    class Broken(HarnessHook):
        """只模拟hook异常原文含秘密。"""
        def before_model(self,context,event):raise RuntimeError('sk-private-hook raw payload')
    sink=[];a=Recorder('a',sink);b=Recorder('b',sink)
    result,runtime=basic(hooks=[a,b,Broken(),HarnessHook()])
    assert runtime.context.status=='completed' and runtime.context.warnings
    assert sink[:2]==[('a','before_run'),('b','before_run')]
    assert a.calls.count('before_model')==3 and a.calls.count('after_model')==3
    assert a.calls.count('before_tool')==a.calls.count('after_tool')==1
    assert 'mutation-must-not-escape' not in runtime.context.warnings
    assert 'sk-private-hook' not in json.dumps(result.metrics)
    assert runtime.context.errors[0].category=='hook' and runtime.context.errors[0].recoverable


@pytest.mark.parametrize('when',['before_run','before_model','after_run'])
def test_explicit_critical_hook_terminates(when):
    """Input：显式critical hook在不同生命周期失败；Expected Output：failed且无假成功终结事件；测试关键策略，目的为critical不能被普通恢复吞掉。"""
    class Critical(HarnessHook):critical=True
    def reject(context,event):raise RuntimeError('private critical details')
    hook=Critical();setattr(hook,when,reject)
    ctx,_=mainland_context();runtime=AgentHarness(ctx.trip.trip_id,hooks=[hook])
    with pytest.raises(HarnessFailure) as exc:basic(runtime=runtime)
    assert runtime.context.status=='failed' and runtime.context.stop_reason=='critical_hook_failed'
    assert types(runtime)[-1]=='RUN_FAILED' and 'RUN_COMPLETED' not in types(runtime)
    assert exc.value.harness_summary.final_status=='failed'
    assert 'private critical details' not in str(exc.value)


def test_trace_sanitizes_arguments_and_rejects_payload():
    """Input：含私密搜索词与不允许的trace字段；Expected Output：只有长度、规范化事件及安全分类；测试输出安全，目的为无key/raw Prompt泄漏。"""
    private='sk-sensitive-user-text'
    agent=ScriptedAgent(AgentDecision(tool_calls=[call(args={'city':'北京','keyword':private,'limit':2})]))
    result,runtime=basic(agent=agent)
    serialized=json.dumps(result.metrics,ensure_ascii=False)
    assert private not in serialized and 'raw_payload' not in serialized
    events=runtime.events
    assert next(e for e in events if e.event_type=='TOOL_COMPLETED').sanitized_args=={'keyword_length':len(private),'limit':2}
    with pytest.raises(ValidationError):runtime.emit('MODEL_CALLED',raw_payload=private)
    event=runtime.emit('MODEL_CALLED',sanitized_args={'api_key':private,'keyword_length':2})
    assert event.sanitized_args=={'keyword_length':2}


def test_stable_fingerprint_cache_and_duplicate_stop():
    """Input：不同call_id、等价城市/空白参数、连续重复；Expected Output：稳定指纹、缓存2次、仅1次HTTP且重复停止；测试统一去重，目的为不能无限查询。"""
    args=SearchPlacesArguments(city='110000',keyword='艺术展',limit=2)
    assert call_fingerprint(' SEARCH_PLACES ',args)==call_fingerprint('search_places',args)
    agent=ScriptedAgent(*[AgentDecision(tool_calls=[call(id=f'c{i}')]) for i in range(8)])
    _,runtime=basic(agent=agent)
    assert runtime.context.tool_call_count==3 and runtime.context.cache_hits==2 and runtime.context.executed_tool_calls==1
    assert types(runtime).count('TOOL_CACHE_HIT')==2 and types(runtime).count('DUPLICATE_CALL_BLOCKED')==1
    assert runtime.context.stop_reason=='repeated_tool_calls'
    assert all(len(key)==64 for key in runtime.cache)


@pytest.mark.parametrize('policy,expected',[(HarnessPolicy(max_tool_calls=1),'tool_budget_exhausted'),(HarnessPolicy(max_decisions=1),'decision_budget_exhausted')])
def test_total_and_round_budget_are_normal_stop(policy,expected):
    """Input：工具/决策一轮预算；Expected Output：正常finalize且BUDGET_REACHED、不是内部失败；测试集中终止规则，目的为预算不是异常崩溃。"""
    _,runtime=basic(policy=policy)
    assert runtime.context.status=='completed' and runtime.context.stop_reason==expected
    assert 'BUDGET_REACHED' in types(runtime) and not any(e.category=='unexpected_internal' for e in runtime.context.errors)


@pytest.mark.parametrize('error_kind',['invalid_args','tool_failure'])
def test_recoverable_tool_errors(error_kind):
    """Input：非法参数或一次工具失败后有效新参数；Expected Output：结构化可恢复错误及后续成功；测试恢复边界，目的为错误不变成模型伪造事实。"""
    class FirstFailure(FakeTools):
        """第一次可选失败，之后正常。"""
        def search_places(self,request):
            if error_kind=='tool_failure' and request.keyword=='first':raise ToolRequestError('safe failure')
            return super().search_places(request)
    first=call(args={'city':'北京','keyword':'first','limit':2} if error_kind=='tool_failure' else {'city':'北京','keyword':'','limit':2})
    agent=ScriptedAgent(AgentDecision(tool_calls=[first]),AgentDecision(tool_calls=[call(id='fixed')]))
    _,runtime=basic(agent=agent,tools=FirstFailure())
    assert runtime.context.status=='completed' and runtime.context.errors[0].recoverable
    assert runtime.context.errors[0].category==('invalid_tool_arguments' if error_kind=='invalid_args' else 'tool')
    assert 'TOOL_FAILED' in types(runtime)


def test_fatal_provider_no_retry_and_failed_hooks():
    """Input：模型Provider失败；Expected Output：只调用一次、failed summary与after_model；测试致命错误，目的为不隐藏重试或吞异常。"""
    class Broken:
        """固定模型失败。"""
        def decide(self,prompt):raise LLMRequestError('safe provider failure')
    ctx,_=mainland_context();hook=Recorder();runtime=AgentHarness(ctx.trip.trip_id,hooks=[hook])
    with pytest.raises(LLMRequestError) as exc:basic(runtime=runtime,agent=Broken())
    assert runtime.context.model_call_count==1 and runtime.context.status=='failed'
    assert runtime.context.errors[0].category=='provider_model'
    assert hook.calls[-1]=='after_run' and hook.calls.count('after_model')==1
    assert exc.value.harness_summary.error_count==1


def test_unexpected_tool_error_is_fatal_and_sanitized():
    """Input：工具实现抛未知内部异常；Expected Output：安全HarnessFailure、TOOL_FAILED和不可恢复内部分类；测试错误边界，目的为不能把bug静默当空结果。"""
    class Broken(FakeTools):
        """模拟非已知ToolError。"""
        def search_places(self,request):raise RuntimeError('sk-private raw provider payload')
    ctx,_=mainland_context();hook=Recorder();runtime=AgentHarness(ctx.trip.trip_id,hooks=[hook])
    with pytest.raises(HarnessFailure) as exc:basic(runtime=runtime,tools=Broken())
    assert runtime.context.errors[0].category=='unexpected_internal' and not runtime.context.errors[0].recoverable
    assert 'TOOL_FAILED' in types(runtime) and hook.calls.count('after_tool')==1
    assert 'sk-private' not in str(exc.value)+runtime.context.model_dump_json()


@pytest.mark.parametrize('failure_mode',['fail','continue_without_memory'])
def test_memory_retrieval_failure_policy(failure_mode):
    """Input：Embedding/检索服务失败及显式恢复策略；Expected Output：默认失败或带warning的无记忆规划；测试保守恢复，目的为不静默假装用了Memory。"""
    class BrokenStore:
        """检索失败不返回伪造记忆。"""
        def retrieve(self,context,top_k):raise LLMRequestError('safe embedding failure')
    ctx,state,_,draft=fixture();hook=Recorder();runtime=AgentHarness(ctx.trip.trip_id,'memory',policy=HarnessPolicy(memory_failure_mode=failure_mode),hooks=[hook])
    def run():return run_agent_planning(ctx,state,ScriptedAgent(AgentDecision(tool_calls=[call()])),RepairClient(draft),FakeTools(),memory_store=BrokenStore(),harness=runtime)
    if failure_mode=='fail':
        with pytest.raises(LLMRequestError):run()
        assert runtime.context.status=='failed'
    else:
        result=run();assert runtime.context.status=='completed' and result.memory_provenance==[]
        assert '本次未使用历史记忆' in result.notice and runtime.context.memory_degraded
    assert runtime.context.errors[0].category=='memory_retrieval'
    assert hook.calls.count('before_memory_retrieval')==hook.calls.count('after_memory_retrieval')==1


def test_memory_topk_and_scope_in_harness(tmp_path):
    """Input：多条相关记忆、无关人物记忆及TopK=1；Expected Output：只返回一条相关ID，trace无正文；测试统一Memory预算，目的为范围与Prompt增长受控。"""
    ctx,state,_,draft=fixture();ctx.trip.context.activity_preferences=['coffee'];store=MemoryStore(tmp_path/'m.db',FakeEmbedding())
    store.write([candidate(ctx,f'我一直喜欢咖啡{i}') for i in range(3)])
    unrelated=store.write([candidate(ctx,'我一直喜欢咖啡',person_id='other',participant_ids=['other'])])[0]
    runtime=AgentHarness(ctx.trip.trip_id,'memory',policy=HarnessPolicy(memory_top_k=1))
    result=run_agent_planning(ctx,state,ScriptedAgent(AgentDecision(tool_calls=[call()])),RepairClient(draft),FakeTools(),memory_store=store,harness=runtime)
    event=next(e for e in runtime.events if e.event_type=='MEMORY_RETRIEVED')
    assert len(result.memory_provenance)==event.result_count==len(event.memory_ids)==1 and unrelated.memory_id not in event.memory_ids
    assert '我一直喜欢' not in result.metrics['harness_trace']


@pytest.mark.parametrize('limit',[0,1,2])
def test_max_replans_is_single_policy(limit):
    """Input：始终错误Trip ID与0/1/2轮修复预算；Expected Output：精确上限后unresolved且模型/验证计数正确；测试统一修复预算，目的为无隐藏第三轮。"""
    ctx,state,_,draft=fixture();draft.trip_id='wrong';client=RepairClient(draft)
    hook=Recorder();runtime=AgentHarness(ctx.trip.trip_id,policy=HarnessPolicy(max_replan_rounds=limit),hooks=[hook])
    result=run_agent_planning(ctx,state,ScriptedAgent(AgentDecision(tool_calls=[call()])),client,FakeTools(),validated=True,harness=runtime)
    assert result.final_status=='unresolved' and result.replan_round==limit and client.repairs==limit
    assert runtime.context.validation_passes==limit+1 and runtime.context.model_call_count==3+limit
    assert runtime.context.status=='unresolved' and runtime.context.stop_reason=='max_replan_rounds'
    assert hook.calls.count('before_replan')==hook.calls.count('after_replan')==limit


def test_validator_failure_never_finalizes_as_valid(monkeypatch):
    """Input：Validator自身抛错；Expected Output：failed、无FINALIZED、after_validate仍执行；测试校验失败边界，目的为未经验证不能冒充valid。"""
    def broken(*args):raise RuntimeError('private validator input')
    monkeypatch.setattr('life_journey.application.constraint_validator.validate_itinerary',broken)
    ctx,state,_,draft=fixture();hook=Recorder();runtime=AgentHarness(ctx.trip.trip_id,hooks=[hook])
    with pytest.raises(HarnessFailure):run_agent_planning(ctx,state,ScriptedAgent(AgentDecision(tool_calls=[call()])),RepairClient(draft),FakeTools(),validated=True,harness=runtime)
    assert runtime.context.status=='failed' and runtime.context.errors[0].category=='validation'
    assert 'FINALIZED' not in types(runtime) and hook.calls.count('after_validate')==1


def test_cooperative_timeout_and_recursion():
    """Input：模型耗尽fake时钟预算或递归上限1；Expected Output：stopped与budget分类；测试时长/递归双边界，目的为安全停止而非内部崩溃。"""
    ctx,state=mainland_context();tick=[0.0]
    class Slow:
        """只推进fake时钟，不实际sleep。"""
        def decide(self,prompt):tick[0]+=2;return AgentDecision(ready_to_plan=True)
    runtime=AgentHarness(ctx.trip.trip_id,policy=HarnessPolicy(max_run_seconds=1.0),clock=lambda:tick[0])
    with pytest.raises(HarnessFailure):run_agent_planning(ctx,state,Slow(),planner(),FakeTools(),harness=runtime)
    assert runtime.context.status=='stopped' and runtime.context.stop_reason=='run_timeout'
    recursion=AgentHarness(ctx.trip.trip_id,policy=HarnessPolicy(recursion_limit=1))
    with pytest.raises(LLMResponseError,match='recursion limit'):basic(runtime=recursion)
    assert recursion.context.status=='stopped' and recursion.context.stop_reason=='recursion_limit'


@pytest.mark.parametrize('mode',['amap','agent','memory'])
def test_api_compatibility_and_harness_debug(tmp_path,mode):
    """Input：旧V1/Agent/Memory同一Planning API；Expected Output：V1不经过Harness，另两者debug含summary且默认隐藏；测试API接线，目的为前端响应不破坏。"""
    from life_journey.schemas import Trip
    from life_journey.schemas.validation import DraftItinerary
    from life_journey.llm.replanning import DraftCallResult
    from test_planning import itinerary_payload
    class Dynamic:
        """从本次Trip构造正确草稿。"""
        def generate_draft(self,prompt):
            trip=Trip.model_validate_json(json.dumps(json.loads(prompt.user_prompt)['trip']));data=itinerary_payload(trip)
            for d in data['days']:
                for a in d['activities']:a['place_id']='p1'
            return DraftCallResult(output=DraftItinerary.model_validate_json(json.dumps(data)),provider='fake',model='fake',latency_ms=0.0)
    client_planner=Dynamic() if mode=='memory' else planner()
    agent=ScriptedAgent(AgentDecision(tool_calls=[call()]))
    with TestClient(create_app(tmp_path/'api.db',planning_mode=mode,planning_client=client_planner,
            agent_client=agent,llm_client=ReadyInterviewClient(),place_tools=FakeTools(),embedding_provider=FakeEmbedding())) as client:
        trip=setup_trip(client);url=f"/api/trips/{trip['trip_id']}";client.post(url+'/interview',json={'user_message':'确认'})
        response=client.post(url+'/planning?debug=true');assert response.status_code==200,response.text
        data=response.json()
        assert ('harness_summary' in data['metrics'])==(mode!='amap')
        if mode!='amap':
            summary=json.loads(data['metrics']['harness_summary']);assert summary['run_id'].startswith('run_') and summary['final_status']=='completed'
            agent.decisions=[AgentDecision(tool_calls=[call(id='next')])]
        plain=client.post(url+'/planning');assert plain.status_code==200 and plain.json()['metrics'] is None


def test_no_candidates_does_not_count_phantom_finalize_call():
    """Input：Agent直接结束且无任何候选；Expected Output：只记录一次Agent模型调用、最终模型零调用；测试准确计数，目的为前置条件失败不算已发模型请求。"""
    from life_journey.tools import NoPlacesError
    ctx,state=mainland_context();runtime=AgentHarness(ctx.trip.trip_id);final=planner()
    with pytest.raises(NoPlacesError):run_agent_planning(ctx,state,ScriptedAgent(),final,FakeTools(),harness=runtime)
    assert runtime.context.model_call_count==1 and final.prompts==[]


@pytest.mark.parametrize('kind',['search','route'])
def test_per_tool_budgets_use_harness_policy(kind):
    """Input：两个搜索或两个模式路线及各自上限1；Expected Output：第二次被预算阻止且无额外HTTP；测试真实执行预算，目的为不靠工具模块自定限制。"""
    decisions=[AgentDecision(tool_calls=[call()])]
    if kind=='search':
        policy=HarnessPolicy(max_search_calls=1)
        decisions.append(AgentDecision(tool_calls=[call(id='next',args={'city':'北京','keyword':'建筑','limit':2})]))
    else:
        policy=HarnessPolicy(max_route_calls=1)
        decisions.append(AgentDecision(tool_calls=[call('get_walking_route',{'origin_place_id':'p1','destination_place_id':'p2'},'walk'),call('get_transit_route',{'origin_place_id':'p1','destination_place_id':'p2'},'transit')]))
    _,runtime=basic(policy=policy,agent=ScriptedAgent(*decisions))
    assert runtime.actions[-1].error_code==('search_or_candidate_budget_exhausted' if kind=='search' else 'route_budget_exhausted')
    assert runtime.context.executed_tool_calls==(1 if kind=='search' else 2) and 'BUDGET_REACHED' in types(runtime)


def test_duplicate_guard_also_blocks_inside_batch():
    """Input：已有一次请求后同批三个重复；Expected Output：前两次缓存、第三次block，HTTP仍一次；测试批次边界，目的为不能等到下一Agent轮才保护。"""
    agent=ScriptedAgent(AgentDecision(tool_calls=[call()]),AgentDecision(tool_calls=[call(id=f'repeated{i}') for i in range(3)]))
    _,runtime=basic(agent=agent)
    assert runtime.context.cache_hits==2 and runtime.actions[-1].error_code=='duplicate_call_blocked'
    assert runtime.context.executed_tool_calls==1 and types(runtime).count('DUPLICATE_CALL_BLOCKED')==1


@pytest.mark.parametrize('when',['before_replan','after_replan'])
def test_critical_replan_hook_is_not_recovered_as_model_failure(when):
    """Input：修复阶段critical hook拒绝；Expected Output：run失败而非吞错后返回unresolved；测试关键策略边界，目的为恢复只适用于明确可恢复错误。"""
    class Critical(HarnessHook):critical=True
    hook=Critical()
    def reject(context,event):raise RuntimeError('private details')
    setattr(hook,when,reject)
    ctx,state,_,draft=fixture();draft.trip_id='wrong';runtime=AgentHarness(ctx.trip.trip_id,hooks=[hook])
    with pytest.raises(HarnessFailure):run_agent_planning(ctx,state,ScriptedAgent(AgentDecision(tool_calls=[call()])),RepairClient(draft,ReplanPatch(trip_id=ctx.trip.trip_id)),FakeTools(),validated=True,harness=runtime)
    assert runtime.context.status=='failed' and runtime.context.stop_reason=='critical_hook_failed'


def test_behavioral_aggregate_and_smoke(capsys):
    """Input：固定11种真实图行为与离线smoke；Expected Output：断言全部满足、保留故意unresolved并输出安全摘要；测试评估可重复性，目的为不把行为合规冒充模型评分。"""
    from life_journey.evaluation.harness_behavior import evaluate
    from life_journey.evaluation.harness_smoke import main
    report=evaluate()
    assert report['case_count']==11 and report['behavior_pass_rate']==1.0
    assert report['unresolved_constraint_rate']==pytest.approx(1/11) and report['run_success_rate']==pytest.approx(10/11)
    assert report['memory_retrieval_count']==3 and report['avg_tool_calls']>0 and report['cache_hit_rate']>0
    assert next(r for r in report['runs'] if r['case']=='soft_stop')['summary']['warning_count']>0
    assert main([])==0
    smoke=json.loads(capsys.readouterr().out)
    assert smoke['cache_hits']==2 and smoke['memory_retrievals']==1 and smoke['replan_rounds']==1 and smoke['final_status']=='completed'


def test_runs_do_not_share_context_cache_or_trace():
    """Input：同一旅行连续两次运行；Expected Output：独立ID/缓存/事件，各执行一次工具；测试请求隔离，目的为不把上次运行当作本次证据。"""
    _,first=basic();_,second=basic()
    assert first.context.run_id!=second.context.run_id and first.cache is not second.cache
    assert first.context.executed_tool_calls==second.context.executed_tool_calls==1
    assert all(e.run_id==first.context.run_id for e in first.events)
    assert all(e.run_id==second.context.run_id for e in second.events)


def test_api_failure_debug_has_safe_structured_diagnostics(tmp_path):
    """Input：Agent Provider失败且debug开关不同；Expected Output：默认detail不变，debug增加安全summary/错误分类；测试失败可观察性，目的为不只看到502字符串。"""
    class Broken:
        """模拟已封装的安全Provider异常。"""
        def decide(self,prompt):raise LLMRequestError('模型服务不可用')
    with TestClient(create_app(tmp_path/'error.db',planning_mode='agent',planning_client=planner(),agent_client=Broken(),llm_client=ReadyInterviewClient(),place_tools=FakeTools())) as client:
        trip=setup_trip(client);url=f"/api/trips/{trip['trip_id']}";client.post(url+'/interview',json={'user_message':'确认'})
        plain=client.post(url+'/planning');assert plain.status_code==502 and set(plain.json())=={'detail'}
        debug=client.post(url+'/planning?debug=true');data=debug.json()
        assert debug.status_code==502 and data['harness_summary']['final_status']=='failed'
        assert data['harness_errors'][0]['category']=='provider_model'
        assert data['harness_summary']['stop_reason']=='provider_model_failed'
        assert data['harness_trace'][-1]['event_type']=='RUN_FAILED'


def test_noncritical_hook_lookup_failure_is_isolated():
    """Input：hook方法属性读取本身失败；Expected Output：仍完成主流程且记录hook分类；测试非critical边界，目的为异常不只限于方法执行阶段。"""
    class BrokenLookup(HarnessHook):
        """模拟集成方错误的hook属性。"""
        @property
        def before_run(self):raise RuntimeError('private lookup detail')
    _,runtime=basic(hooks=[BrokenLookup()])
    assert runtime.context.status=='completed' and runtime.context.errors[0].category=='hook'
    assert 'private lookup detail' not in runtime.context.model_dump_json()


def test_bad_policy_environment_is_configuration_error_not_output_error(tmp_path,monkeypatch):
    """Input：非法Harness环境预算；Expected Output：503安全配置错误、模型工具零调用；测试故障归因，目的为不再把配置错误误报为Planning输出失败。"""
    monkeypatch.setenv('LIFE_JOURNEY_MAX_TOOL_CALLS','invalid-private-value')
    tools=FakeTools();agent=ScriptedAgent(AgentDecision(tool_calls=[call()]))
    with TestClient(create_app(tmp_path/'badpolicy.db',planning_mode='agent',planning_client=planner(),agent_client=agent,llm_client=ReadyInterviewClient(),place_tools=tools)) as client:
        trip=setup_trip(client);url=f"/api/trips/{trip['trip_id']}";client.post(url+'/interview',json={'user_message':'确认'})
        response=client.post(url+'/planning')
        assert response.status_code==503 and 'Harness预算配置无效' in response.json()['detail']
        assert 'invalid-private-value' not in response.text and agent.prompts==[] and tools.calls==[]
