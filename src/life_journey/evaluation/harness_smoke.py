"""离线Harness smoke，展示真实图控制轨迹；不冒充真实Provider验收。"""
import argparse
import json
from .harness_behavior import evaluate,CASE_NAMES

def main(argv=None):
    """默认场景同时展示缓存、记忆、校验与局部修复。"""
    parser=argparse.ArgumentParser();parser.add_argument('--case',choices=CASE_NAMES,default='memory_repair')
    args=parser.parse_args(argv);run=evaluate(args.case)['runs'][0];summary=run['summary'];events=run['trace']
    report={'kind':'offline_fixture_smoke','run_id':summary['run_id'],'planning_mode':run['planning_mode'],
        'graph_transitions':[e['graph_node'] for e in events if e['event_type']=='NODE_ENTERED'],
        'tool_calls':summary['tool_calls'],'cache_hits':summary['cache_hits'],'memory_retrievals':summary['memory_retrievals'],
        'validation_issues':[e.get('validation_issue_count') for e in events if e['event_type']=='VALIDATION_COMPLETED'],
        'replan_rounds':summary['replan_rounds'],'stop_reason':summary['stop_reason'],'total_latency_ms':summary['total_duration_ms'],
        'final_status':summary['final_status'],'behavior_passed':run['passed']}
    print(json.dumps(report,ensure_ascii=False,indent=2));return 0 if run['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
