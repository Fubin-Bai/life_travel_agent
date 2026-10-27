"""手动V2真实smoke：固定虚构输入、行动轨迹和最终行程；不连接SQLite。"""
import argparse
import json
from life_journey import environment
from life_journey.application.context_builder import build_travel_context
from life_journey.application.agent_planning import run_agent_planning
from life_journey.sample_data import load_persons,load_relationships,load_trips
from life_journey.schemas import InterviewState
from life_journey.schemas.interview import MINIMUM_PLANNING_TOPICS
from life_journey.schemas.agent import AgentBudget,AgentRunMetrics
from life_journey.llm.deepseek import DeepSeekInterviewClient,DeepSeekConfig
from life_journey.llm.base import LLMClientError
from life_journey.tools import AmapPlaceTools,ToolError


def smoke_context(city: str, case: str):
    """固定虚构人物与日期，只更换本次明确活动，不读正式用户数据。"""
    trip=load_trips()['trip_tokyo_alex_bella_slow'].model_copy(deep=True)
    trip.trip_id='trip_agent_smoke'
    trip.destination=city
    trip.context.preferred_pace='moderate'
    trip.context.required_activities=['现代建筑']
    trip.context.activity_preferences=['咖啡馆'] if case=='architecture_coffee' else ['艺术展','工艺品店']
    trip.context.excluded_activities=['酒吧']
    context=build_travel_context(trip,load_persons().values(),load_relationships().values())
    state=InterviewState(trip_id=trip.trip_id,trip_setup_complete=True,topics={topic:'confirmed' for topic in MINIMUM_PLANNING_TOPICS})
    return context,state


def main(argv=None) -> int:
    """显式运行才消耗API；只展示action trace，不输出Prompt、Key或隐藏推理。"""
    parser=argparse.ArgumentParser(description='V2 LangGraph真实Agent smoke（会消耗高德与DeepSeek配额）')
    parser.add_argument('--city',default='北京')
    parser.add_argument('--case',choices=['architecture_coffee','architecture_art'],default='architecture_coffee')
    parser.add_argument('--max-tool-calls',type=int,default=6)
    args=parser.parse_args(argv)
    environment.load_project_env()
    tools=None;client=None
    try:
        budget=AgentBudget(max_tool_calls=args.max_tool_calls)
        context,state=smoke_context(args.city,args.case)
        tools=AmapPlaceTools()
        client=DeepSeekInterviewClient(DeepSeekConfig(model=DeepSeekConfig.from_env().model,max_output_tokens=8192,timeout_seconds=120))
        result=run_agent_planning(context,state,client,client,tools,budget=budget)
        metrics=AgentRunMetrics.model_validate_json(result.metrics['agent_run'])
        print(json.dumps({'case':args.case,'agent_run':metrics.model_dump(mode='json'),
                          'search_queries':[search.request.keyword for search in result.observation.searches],
                          'itinerary':result.itinerary.model_dump(mode='json'),'notice':result.notice},ensure_ascii=False,indent=2))
        print('smoke成功仅证明本次链路，非质量评分、未来营业/班次或稳定性保证。')
        return 0
    except (LLMClientError,ToolError) as exc:
        if hasattr(exc,'agent_run_metrics'):
            print(json.dumps({'failed':True,'agent_run':exc.agent_run_metrics.model_dump(mode='json')},ensure_ascii=False,indent=2))
        print(f'FAILED：{exc}')
        return 1
    except (ValueError,TypeError):
        print('FAILED：smoke输入、状态或结果校验失败；未记录原始数据')
        return 1
    finally:
        if tools is not None:tools.close()
        if client is not None:client.close()


if __name__=='__main__':
    raise SystemExit(main())
