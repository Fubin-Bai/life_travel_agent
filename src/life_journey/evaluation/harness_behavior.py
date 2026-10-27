"""轻量behavioral harness：固定桩驱动真实LangGraph，只检查运行行为，不评分模型。"""
import argparse
import json
from datetime import datetime,timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from life_journey.schemas import TravelContext,InterviewState
from life_journey.schemas.interview import MINIMUM_PLANNING_TOPICS
from life_journey.schemas.agent import AgentDecision,AgentToolCall
from life_journey.schemas.validation import DraftItinerary,ReplanPatch
from life_journey.schemas.itinerary import Itinerary
from life_journey.schemas.memory import MemoryCandidate
from life_journey.tools.schemas import PlanningObservation,PlaceSearchResult,RouteResult
from life_journey.llm.replanning import DraftCallResult,RepairCallResult
from life_journey.llm.planning import PlanningCallResult
from life_journey.application.agent_planning import run_agent_planning
from life_journey.application.memory import MemoryStore
from life_journey.harness.runtime import AgentHarness
from life_journey.harness.policy import HarnessPolicy
from .constraints import load_cases
from .memory_rag import EvaluationEmbedding

CASE_NAMES=('tool_budget','duplicate_stop','memory_scope','hard_replan','soft_stop','max_replans',
    'closed_repair','unknown_not_verified','current_trip_over_memory','candidate_rejected','memory_repair')

class FixtureTools:
    """规范化POI/路线桩，仅使用仓库合成fixture，不访问外部服务。"""
    def __init__(self,observation):self.observation=observation
    def resolve_city(self,request):return self.observation.city
    def search_places(self,request):
        """重建本次请求，不能把其他查询的信封冒充响应。"""
        return PlaceSearchResult(request=request,status='ok',places=self.observation.places[:request.limit],fetched_at=datetime.now(timezone.utc))
    def route(self,request):
        """明确无路线，不伪造未知交通。"""
        return RouteResult(request=request,status='no_route',fetched_at=datetime.now(timezone.utc))

class FixtureAgent:
    """脚本决定仅为行为fixture，不代替生产LLM。"""
    def __init__(self,repeats=1):self.count=0;self.repeats=repeats
    def decide(self,prompt):
        """每次call_id不同，相同参数仍应命中Harness缓存。"""
        self.count+=1
        if self.count>self.repeats:return AgentDecision(ready_to_plan=True)
        call=AgentToolCall(call_id=f'fixture_{self.count}',name='search_places',arguments=json.dumps({'city':'北京','keyword':'艺术展','limit':2},ensure_ascii=False))
        return AgentDecision(tool_calls=[call])

class FixturePlanner:
    """固定草稿/补丁与实际领域Validator组成运行夹具。"""
    def __init__(self,draft,patch):self.draft=draft;self.patch=patch
    def generate_draft(self,prompt):return DraftCallResult(output=self.draft,provider='fixture',model='scripted',latency_ms=0.0)
    def repair_itinerary(self,prompt):return RepairCallResult(output=self.patch,provider='fixture',model='scripted',latency_ms=0.0)
    def generate_itinerary(self,prompt):return PlanningCallResult(output=Itinerary.model_validate_json(self.draft.model_dump_json()),provider='fixture',model='scripted',latency_ms=0.0)


def evaluate(selected=None):
    """聚合运行成功与行为符合率，两者不能混为同一指标。"""
    if selected is not None and selected not in CASE_NAMES:raise ValueError('未知behavioral case')
    fixtures={c['name']:c for c in load_cases()};runs=[]
    with TemporaryDirectory() as directory:
        for name in CASE_NAMES:
            if selected is not None and name!=selected:continue
            fixture_name={'hard_replan':'successful_local_repair','max_replans':'unresolved_after_limit',
                'closed_repair':'closed_poi','candidate_rejected':'candidate_hallucination','soft_stop':'fast_too_sparse',
                'current_trip_over_memory':'fast_too_sparse','memory_repair':'successful_local_repair'}.get(name,'successful_local_repair')
            case=fixtures[fixture_name]
            context=TravelContext.model_validate_json(json.dumps(case['context']))
            observation=PlanningObservation.model_validate_json(json.dumps(case['observation']))
            draft=DraftItinerary.model_validate_json(json.dumps(case['draft']))
            patch=ReplanPatch.model_validate_json(json.dumps(case['patch']))
            if name not in {'hard_replan','max_replans','closed_repair','candidate_rejected','memory_repair'}:draft.trip_id=context.trip.trip_id
            if name=='unknown_not_verified':
                replacement=draft.days[0].model_copy(deep=True)
                draft.days[0].activities[0].description='已确认营业'
                from life_journey.schemas.validation import DayRepair
                patch=ReplanPatch(days=[DayRepair(day_index=0,replacement=replacement)])
            policy=HarnessPolicy(max_tool_calls=1) if name=='tool_budget' else HarnessPolicy()
            repeats=8 if name in {'tool_budget','duplicate_stop','memory_repair'} else 1
            memory_store=None;unrelated_id=None;old_id=None
            if name in {'memory_scope','current_trip_over_memory','memory_repair'}:
                context.trip.context.activity_preferences=['coffee']
                memory_store=MemoryStore(Path(directory)/(name+'.db'),EvaluationEmbedding())
                pid=context.trip.participant_ids[0]
                candidate=MemoryCandidate(person_id=pid,participant_ids=[pid],content='我一直喜欢安静咖啡馆',stable=True,source_reference='behavioral:feedback')
                if name=='memory_scope':candidate=candidate.model_copy(update={'person_id':'unrelated','participant_ids':['unrelated']})
                if name=='current_trip_over_memory':candidate=candidate.model_copy(update={'content':'我一直喜欢慢节奏','structured_tags':{'preferred_pace':'slow'}})
                saved=memory_store.write([candidate])[0]
                if name=='memory_scope':unrelated_id=saved.memory_id
                elif name=='current_trip_over_memory':old_id=saved.memory_id
            mode='memory' if memory_store else 'agent'
            runtime=AgentHarness(context.trip.trip_id,mode,policy=policy)
            state=InterviewState(trip_id=context.trip.trip_id,trip_setup_complete=True,topics={t:'confirmed' for t in MINIMUM_PLANNING_TOPICS})
            result=run_agent_planning(context,state,FixtureAgent(repeats),FixturePlanner(draft,patch),FixtureTools(observation),
                validated=True,memory_store=memory_store,harness=runtime)
            summary=runtime.summary();ids={m['memory_id'] for m in result.memory_provenance}
            checks={'tool_budget':summary.tool_calls<=policy.max_tool_calls,'model_round_budget':runtime.context.decision_count<=policy.max_decisions,
                'replan_budget':summary.replan_rounds<=policy.max_replan_rounds}
            if name=='tool_budget':checks['normal_budget_stop']=summary.final_status=='completed' and summary.stop_reason=='tool_budget_exhausted'
            if name in {'duplicate_stop','memory_repair'}:checks['duplicate_cache_and_stop']=summary.cache_hits==2 and summary.executed_tool_calls==1 and summary.stop_reason=='repeated_tool_calls'
            if name=='memory_scope':checks['scope_isolated']=unrelated_id not in ids and not ids
            if name=='current_trip_over_memory':checks['current_trip_overrides']=old_id not in ids and '慢节奏' not in result.itinerary.summary
            if name in {'hard_replan','memory_repair'}:checks['hard_triggers_replan']=summary.replan_rounds==1 and result.final_status=='valid'
            if name=='soft_stop':checks['soft_does_not_force_replan']=summary.replan_rounds==0 and result.validation_result.soft_warning_count>0
            if name=='max_replans':checks['unresolved_after_max']=summary.replan_rounds==2 and result.final_status=='unresolved' and bool(result.unresolved_constraints)
            if name=='closed_repair':checks['closed_removed']=all(a.place_id!='p1' for d in result.itinerary.days for a in d.activities) and result.final_status=='valid'
            if name=='unknown_not_verified':checks['unknown_stays_unknown']=all(a.opening_status=='unknown' for d in result.itinerary.days for a in d.activities) and result.final_status=='valid'
            if name=='candidate_rejected':checks['outside_candidate_removed']=all(a.place_id in {'p1','p2',None} for d in result.itinerary.days for a in d.activities) and summary.replan_rounds>0
            if name=='memory_repair':checks['memory_in_graph']=len(ids)==1
            runs.append({'case':name,'planning_mode':mode,'passed':all(checks.values()),'assertions':checks,
                'summary':summary.model_dump(mode='json'),'trace':[e.model_dump(mode='json',exclude_none=True,exclude_defaults=True) for e in runtime.events]})
    n=len(runs);summaries=[r['summary'] for r in runs]
    tool_calls=sum(s['tool_calls'] for s in summaries);validations=sum(s['validation_passes'] for s in summaries)
    return {'kind':'offline_behavioral_harness_real_langgraph_fake_dependencies','case_count':n,
        'behavior_pass_rate':sum(r['passed'] for r in runs)/n,'run_success_rate':sum(s['final_status']=='completed' for s in summaries)/n,
        'avg_tool_calls':tool_calls/n,'avg_model_calls':sum(s['model_calls'] for s in summaries)/n,
        'avg_replan_rounds':sum(s['replan_rounds'] for s in summaries)/n,
        'cache_hit_rate':sum(s['cache_hits'] for s in summaries)/tool_calls if tool_calls else 0,
        'validation_failure_rate':sum(s['validation_failures'] for s in summaries)/validations if validations else 0,
        'unresolved_constraint_rate':sum(s['final_status']=='unresolved' for s in summaries)/n,
        'memory_retrieval_count':sum(s['memory_retrievals'] for s in summaries),
        'avg_latency_ms':sum(s['total_duration_ms'] for s in summaries)/n,'runs':runs}


def main(argv=None):
    """手动运行产生本地聚合报告，不使用API Key或正式SQLite。"""
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path)
    args=parser.parse_args(argv);report=evaluate()
    if args.output:args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='runs'},ensure_ascii=False,indent=2))
    return 0 if all(r['passed'] for r in report['runs']) else 1

if __name__=='__main__':raise SystemExit(main())
