"""显式联网的V3/V4原型smoke；只用虚构场景和临时库，不读正式用户数据。"""
import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from life_journey.environment import load_project_env
from life_journey.llm.deepseek import DeepSeekInterviewClient,DeepSeekConfig
from life_journey.llm.embedding import CompatibleEmbeddingProvider
from life_journey.llm.base import LLMClientError
from life_journey.tools import AmapPlaceTools,ToolError
from life_journey.application.agent_planning import run_agent_planning,build_agent_graph
from life_journey.application.planning_observation import collect_planning_observation
from life_journey.application.replanning import generate_draft
from life_journey.application.constraint_validator import matches
from life_journey.application.memory import MemoryStore,extract_candidates
from life_journey.schemas.memory import MemoryCandidate
from life_journey.schemas.agent import AgentDecision,AgentBudget
from life_journey.tools.opening_hours import check_opening_hours
from langsmith import tracing_context
from .agent_smoke import smoke_context

class ReadyForValidation:
    """V3组件smoke跳过已覆盖V2的取证决策，使用刚取得的真实Observation。"""
    def decide(self,prompt):return AgentDecision(ready_to_plan=True)

class ControlledDraft:
    """仅初稿注入明确冲突；修复仍调用真实DeepSeek，不能注入假高德事实。"""
    def __init__(self,call,client):self.call=call;self.client=client
    def generate_draft(self,prompt):return self.call
    def repair_itinerary(self,prompt):return self.client.repair_itinerary(prompt)

def v3_smoke(context,state,tools,client,case):
    """固定触发冲突，但不伪造closed或路线Observation。"""
    observation=collect_planning_observation(context,tools)
    call=generate_draft(context,observation,client)
    draft=call.output.model_copy(deep=True)
    if case=='closed':
        choices=[(p,d,period) for p in observation.places for d in draft.days for period in ('morning','afternoon','evening') if check_opening_hours(p,d.date,period).status=='closed']
        if not choices:return {'status':'skipped','reason':'本次真实高德结果没有可判断closed证据，不能伪造闭店用例'}
        p,d,period=choices[0];a=d.activities[0];a.place_id=p.place_id;a.title=p.name;a.time_period=period
    elif case=='required':
        required=context.trip.context.required_activities[0]
        for day in draft.days:
            for a in day.activities:
                p=next((p for p in observation.places if p.place_id==a.place_id),None)
                if matches(required,' '.join((a.title,a.description,p.name if p else '',p.category or '' if p else '',*(p.source_keywords if p else [])))):
                    a.title='自由休息';a.description='通用休息时间';a.place_id=None;a.rationale='暂留空档，尚未覆盖必需活动'
    elif case=='route':
        if len(observation.places)<2:return {'status':'skipped','reason':'真实候选少于两个'}
        a=draft.days[0].activities[0];a.place_id=observation.places[0].place_id
        b=a.model_copy(deep=True);b.place_id=observation.places[1].place_id;b.title=observation.places[1].name;b.time_period='evening';b.description='步行999分钟'
        draft.days[0].activities.append(b)
    call=call.model_copy(update={'output':draft})
    initial={'trip_id':context.trip.trip_id,'context':context,'interview_state':state,'city':observation.city,
        'messages':[],'pending_calls':[],'searches':observation.searches,'places':{p.place_id:p for p in observation.places},
        'routes':observation.routes,'opening_checks':observation.opening_checks,'planning_ready':False,'response':None}
    from life_journey.harness.runtime import AgentHarness
    runtime=AgentHarness(context.trip.trip_id,policy=AgentBudget())
    graph=build_agent_graph(ReadyForValidation(),ControlledDraft(call,client),tools,validated=True,harness=runtime)
    def invoke(harness):
        with tracing_context(enabled=False):return graph.invoke(initial,config={'recursion_limit':harness.policy.graph_recursion_limit(True),'callbacks':[]})['response']
    result=runtime.run(invoke)
    return {'status':result.final_status,'case':case,'replan_round':result.replan_round,
        'validation':result.validation_result.model_dump(mode='json'),'trace':json.loads(result.metrics['validation_trace'])}

def main():
    """仅手动运行才联网，不由pytest自动收集。"""
    load_project_env()
    parser=argparse.ArgumentParser();parser.add_argument('--stage',choices=['v3','v4'],required=True)
    parser.add_argument('--case',choices=['closed','required','route'],default='closed');parser.add_argument('--city',default='北京')
    args=parser.parse_args();client=tools=embedding=None
    try:
        context,state=smoke_context(args.city,'architecture_coffee')
        config=DeepSeekConfig.from_env();client=DeepSeekInterviewClient(DeepSeekConfig(model=config.model,max_output_tokens=8192,timeout_seconds=120))
        tools=AmapPlaceTools()
        if args.stage=='v3':report=v3_smoke(context,state,tools,client,args.case)
        else:
            embedding=CompatibleEmbeddingProvider()
            with TemporaryDirectory() as directory:
                store=MemoryStore(Path(directory)/'smoke.sqlite3',embedding)
                pid=context.trip.participant_ids[0]
                stored=store.write(extract_candidates('我一直喜欢安静的咖啡馆，以后旅行也想保留',context,pid,source_reference='smoke:first_trip_feedback'))
                unrelated=store.write([MemoryCandidate(person_id='unrelated-person',participant_ids=['unrelated-person'],content='我一直喜欢咖啡馆',source_reference='smoke:unrelated',stable=True)])
                context.trip.trip_id='trip_memory_second_smoke';state=state.model_copy(update={'trip_id':context.trip.trip_id})
                result=run_agent_planning(context,state,client,client,tools,validated=True,memory_store=store)
                retrieved={m['memory_id'] for m in result.memory_provenance}
                report={'status':result.final_status,'stored_memory_ids':[m.memory_id for m in stored],
                    'memory_provenance':result.memory_provenance,'unrelated_leaked':bool(retrieved & {m.memory_id for m in unrelated}),
                    'validation':result.validation_result.model_dump(mode='json'),'itinerary':result.itinerary.model_dump(mode='json'),
                    'note':'来源表示检索并提供给Planner；实际采用程度需人工检查rationale，不能仅凭检索成功认定'}
        print(json.dumps(report,ensure_ascii=False,indent=2))
    except (LLMClientError,ToolError,ValueError):
        print('FAILED：真实服务请求、配置或结构校验失败；未伪造成功。');return 1
    finally:
        for resource in (embedding,tools,client):
            if resource is not None:resource.close()
    return 0

if __name__=='__main__':raise SystemExit(main())
