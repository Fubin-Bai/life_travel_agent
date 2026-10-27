"""离线固定规则评估；预设补丁与真实模型修复质量明确分开。"""
import json
from copy import deepcopy
from pathlib import Path
from life_journey.schemas import TravelContext
from life_journey.schemas.validation import DraftItinerary,ReplanPatch,MAX_REPLAN_ROUNDS
from life_journey.tools.schemas import PlanningObservation
from life_journey.application.constraint_validator import validate_itinerary
from life_journey.application.replanning import repair_draft,RepairCallResult

class FixtureRepair:
    """固定补丁只验证修复应用与再次校验机制。"""
    def __init__(self,patch):self.patch=patch
    def repair_itinerary(self,prompt):
        """返回预设结构化补丁，不访问模型。"""
        return RepairCallResult(output=self.patch,provider='fixture',model='scripted',latency_ms=0.0)

def load_cases(path=None):
    """共享基线加显式字段差异，避免复制重复POI和搜索正文。"""
    path=path or Path(__file__).resolve().parents[3]/'evaluations/v3_constraints.json'
    payload=json.loads(Path(path).read_text());cases=[]
    for case in payload['cases']:
        data=deepcopy(payload['base'])
        for change in case['changes']:
            target=data
            for key in change['path'][:-1]:target=target[key]
            target[change['path'][-1]]=deepcopy(change['value'])
        cases.append({**data,**case})
    return cases

def evaluate(path=None):
    """报告固定样本的硬冲突比例与解决情况，不泛化为推荐质量提升。"""
    cases=load_cases(path);rows=[]
    for case in cases:
        context=TravelContext.model_validate_json(json.dumps(case['context']))
        observation=PlanningObservation.model_validate_json(json.dumps(case['observation']))
        draft=DraftItinerary.model_validate_json(json.dumps(case['draft']))
        before=validate_itinerary(context,draft,observation);after=before;rounds=0
        for _ in range(MAX_REPLAN_ROUNDS):
            if after.valid:break
            try:draft,_=repair_draft(context,draft,after,observation,FixtureRepair(ReplanPatch.model_validate_json(json.dumps(case['patch']))))
            except (ValueError,RuntimeError):pass
            rounds+=1;after=validate_itinerary(context,draft,observation)
        rows.append({'case':case['name'],'expected_detected':case['expected_type'] in before.constraint_types,
            'before_hard':before.hard_violation_count,'after_hard':after.hard_violation_count,'rounds':rounds,
            'before_unsupported':sum(i.type in {'unsupported_fact','route_fact','candidate_outside'} for i in before.violations),
            'after_unsupported':sum(i.type in {'unsupported_fact','route_fact','candidate_outside'} for i in after.violations)})
    hard=sum(r['before_hard'] for r in rows);remaining=sum(r['after_hard'] for r in rows);invalid=sum(r['before_hard']>0 for r in rows)
    return {'kind':'offline_scripted_rule_evaluation','case_count':len(rows),'violation_rate_before':invalid/len(rows),
        'violation_rate_after':sum(r['after_hard']>0 for r in rows)/len(rows),
        'replan_success_rate':sum(r['before_hard']>0 and r['after_hard']==0 for r in rows)/invalid if invalid else 1,
        'hard_constraint_resolution_rate':(hard-remaining)/hard if hard else 1,
        'unsupported_factual_claim_rate_before':sum(r['before_unsupported']>0 for r in rows)/len(rows),
        'unsupported_factual_claim_rate_after':sum(r['after_unsupported']>0 for r in rows)/len(rows),'cases':rows}

if __name__=='__main__':print(json.dumps(evaluate(),ensure_ascii=False,indent=2))
