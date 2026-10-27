"""V3固定冲突、图循环和局部修复的离线回归。"""
import json
from copy import deepcopy
import pytest
from life_journey.schemas.validation import DraftItinerary, ReplanPatch, DayRepair
from life_journey.application.constraint_validator import validate_itinerary
from life_journey.application.replanning import DraftCallResult, RepairCallResult, repair_draft
from life_journey.application.agent_planning import run_agent_planning
from life_journey.application.planning_observation import collect_planning_observation
from life_journey.schemas.agent import AgentDecision
from life_journey.llm.base import LLMResponseError, LLMRequestError
from test_agent_planning import ScriptedAgent, call
from test_planning_observation import mainland_context, FakeTools
from test_planning import itinerary_payload
from test_opening_hours import with_hours


def fixture():
    """固定日期、两候选与安全草稿，不访问用户数据库。"""
    ctx,state=mainland_context();ctx.trip.context.required_activities=[]
    obs=collect_planning_observation(ctx,FakeTools())
    data=itinerary_payload(ctx.trip)
    for d in data['days']:
        for a in d['activities']:a['place_id']='p1'
    return ctx,state,obs,DraftItinerary.model_validate_json(json.dumps(data))


@pytest.mark.parametrize('kind', ['trip_id','dates','time_order','required_missing','excluded_activity','candidate_outside','closed','unsupported_fact','route_fact','pace_density','meal_repetition','backtracking'])
def test_fixed_constraint_cases(kind):
    """Input：十二类固定硬软冲突；Expected Output：对应结构化issue及正确severity；测试覆盖规则与证据引用，目的为可解释而非字符串报错。"""
    ctx,_,obs,draft=fixture();a=draft.days[0].activities[0]
    if kind=='trip_id':draft.trip_id='wrong'
    elif kind=='dates':draft.days.append(draft.days[0].model_copy(deep=True))
    elif kind=='time_order':
        a.time_period='evening';b=a.model_copy(deep=True);b.time_period='morning';draft.days[0].activities.append(b)
    elif kind=='required_missing':ctx.trip.context.required_activities=['滑雪']
    elif kind=='excluded_activity':ctx.trip.context.excluded_activities=['展览']
    elif kind=='candidate_outside':a.place_id='invented'
    elif kind=='closed':obs.places[0].opening_hours=with_hours('永久停业').opening_hours
    elif kind=='unsupported_fact':a.description='已确认营业，无需核实'
    elif kind=='route_fact':a.description='步行5分钟即可到达'
    elif kind=='pace_density':ctx.trip.context.preferred_pace='fast';draft.summary='紧凑行程'
    elif kind=='meal_repetition':obs.places[0].category='餐饮服务';a.title='美食午餐'
    elif kind=='backtracking':
        p=obs.places[1];p.location.longitude+=0.1
        b=a.model_copy(deep=True);b.place_id='p2';draft.days[0].activities.extend([b,a.model_copy(deep=True)])
    result=validate_itinerary(ctx,draft,obs)
    assert kind in result.constraint_types
    assert result.hard_violation_count==len(result.violations)
    assert all(i.evidence_reference and i.repair_hint for i in result.violations+result.warnings)


class RepairClient:
    """固定草稿与补丁，真实图执行但无Provider网络。"""
    def __init__(self,draft,patch=None,error=False):self.draft=draft;self.patch=patch or ReplanPatch();self.repairs=0;self.error=error
    def generate_draft(self,prompt):
        """记录结构化输入，返回固定草稿。"""
        self.prompt=prompt
        return DraftCallResult(output=self.draft,provider='fake',model='fake',latency_ms=0.0)
    def repair_itinerary(self,prompt):
        """失败仍计入修复轮数。"""
        self.repairs+=1
        if self.error:raise LLMRequestError('离线模拟失败')
        return RepairCallResult(output=self.patch,provider='fake',model='fake',latency_ms=0.0)


@pytest.mark.parametrize('repair_success,error',[(True,False),(False,False),(False,True)])
def test_graph_local_repair_or_explicit_unresolved(repair_success,error):
    """Input：错误ID及成功/空/失败补丁；Expected Output：成功一轮或未解决两轮，返回草稿；测试真实LangGraph循环，目的为有界终止且不隐藏冲突。"""
    ctx,state,_,draft=fixture();draft.trip_id='wrong'
    client=RepairClient(draft,ReplanPatch(trip_id=ctx.trip.trip_id) if repair_success else None,error)
    agent=ScriptedAgent(AgentDecision(tool_calls=[call()]))
    result=run_agent_planning(ctx,state,agent,client,FakeTools(),validated=True)
    assert result.final_status==('valid' if repair_success else 'unresolved')
    assert result.replan_round==(1 if repair_success else 2)
    assert bool(result.unresolved_constraints)!=repair_success
    trace=json.loads(result.metrics['validation_trace'])
    assert [n['node'] for n in trace].count('validate')==result.replan_round+1


def test_unaffected_day_is_immutable():
    """Input：仅第一天闭店却请求更改第二天；Expected Output：LLMResponseError；测试补丁边界，目的为默认局部修复而非全量重写。"""
    ctx,_,obs,draft=fixture();draft.days[0].activities[0].place_id='invented'
    result=validate_itinerary(ctx,draft,obs)
    client=RepairClient(draft,ReplanPatch(days=[DayRepair(day_index=1,replacement=draft.days[1])]))
    with pytest.raises(LLMResponseError):repair_draft(ctx,draft,result,obs,client)


def test_duplicate_dates_are_diagnosed_without_relaxing_legacy_schema():
    """Input：重复日期草稿；Expected Output：草稿合法但Validator报告dates，旧Itinerary仍拒绝；测试兼容，目的为诊断与正式结构校验分开。"""
    from life_journey.schemas.itinerary import Itinerary
    ctx,_,obs,draft=fixture();draft.days.append(draft.days[0])
    assert 'dates' in validate_itinerary(ctx,draft,obs).constraint_types
    with pytest.raises(ValueError):Itinerary.model_validate_json(draft.model_dump_json())


def test_closed_replaced_with_known_alternative():
    """Input：真实形状的闭店证据及同池替代补丁；Expected Output：局部替换p2后通过且unknown不标营业；测试修复闭店，目的为不靠放宽规则通过。"""
    class ClosedTools(FakeTools):
        """只把第一候选设为明确关闭。"""
        def search_places(self,request):
            """仍返回规范化POI与真实来源字段形状。"""
            result=super().search_places(request)
            result.places[0].opening_hours=with_hours('永久停业').opening_hours
            return result
    ctx,state,_,draft=fixture();days=[]
    for i,day in enumerate(draft.days):
        replacement=day.model_copy(deep=True)
        for a in replacement.activities:a.place_id='p2'
        days.append(DayRepair(day_index=i,replacement=replacement))
    client=RepairClient(draft,ReplanPatch(days=days))
    result=run_agent_planning(ctx,state,ScriptedAgent(AgentDecision(tool_calls=[call()])),client,ClosedTools(),validated=True)
    assert result.final_status=='valid' and result.replan_round==1
    assert all(a.place_id=='p2' and a.opening_status=='unknown' for d in result.itinerary.days for a in d.activities)


def test_required_gap_cannot_be_covered_by_failure_disclaimer():
    """Input：描述说未找到滑雪；Expected Output：required_missing；测试否定识别，目的为缺口不能被统计成已满足。"""
    ctx,_,obs,draft=fixture();ctx.trip.context.required_activities=['滑雪']
    draft.days[0].activities[0].description='未找到可验证滑雪地点，暂不安排'
    assert 'required_missing' in validate_itinerary(ctx,draft,obs).constraint_types


def test_fixed_v3_evaluation():
    """Input：十二个固定冲突及预设局部补丁；Expected Output：全部识别、成功修复例通过、未解决例两轮停止；测试评估可重复性，目的为报告有数据依据。"""
    from life_journey.evaluation.constraints import evaluate
    report=evaluate()
    assert report['case_count']==12 and all(c['expected_detected'] for c in report['cases'])
    assert next(c for c in report['cases'] if c['case']=='successful_local_repair')['after_hard']==0
    unresolved=next(c for c in report['cases'] if c['case']=='unresolved_after_limit')
    assert unresolved['rounds']==2 and unresolved['after_hard']>0


def test_missing_requirement_does_not_authorize_full_rewrite():
    """Input：仅缺一个必需活动却修改所有日期；Expected Output：补丁被拒绝；测试局部修复预算，目的为全局缺口不等于全量重写授权。"""
    ctx,_,obs,draft=fixture();ctx.trip.context.required_activities=['咖啡']
    validation=validate_itinerary(ctx,draft,obs)
    patch=ReplanPatch(days=[DayRepair(day_index=i,replacement=d) for i,d in enumerate(draft.days)])
    with pytest.raises(LLMResponseError):repair_draft(ctx,draft,validation,obs,RepairClient(draft,patch))


def test_summary_route_minutes_are_reported_before_complete():
    """Input：摘要出现无端点步行分钟数；Expected Output：hard unsupported_fact而非complete抛异常；测试诊断完整性，目的为事实问题先进入修复环。"""
    ctx,_,obs,draft=fixture();draft.summary='步行5分钟可达'
    assert 'unsupported_fact' in validate_itinerary(ctx,draft,obs).constraint_types
