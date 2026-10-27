"""固定离线Memory检索与脚本规划对照；不是实际LLM质量评估。"""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from life_journey.application.memory import MemoryStore
from life_journey.schemas.memory import MemoryCandidate

class EvaluationEmbedding:
    """仅用于固定评估的假语义簇，生产必须接真实Embedding。"""
    model='evaluation-fake-v1'
    def embed(self,texts):
        """咖啡/cafe同簇，其他信息异簇。"""
        return [[1.0,0.0] if any(k in t for k in ('咖啡','coffee','cafe')) else [0.0,1.0] for t in texts]

def evaluate():
    """比较明确标注的脚本基线，记录隔离/召回指标，不宣称真实个性化收益。"""
    from life_journey.schemas import TravelContext
    from life_journey.schemas.validation import DraftItinerary
    from life_journey.tools.schemas import PlanningObservation
    from life_journey.application.constraint_validator import validate_itinerary
    from .constraints import load_cases
    fixture=load_cases()[0]
    rows=[]
    with TemporaryDirectory() as directory:
        for index,kind in enumerate(('person','relationship','trip','irrelevant_person')):
            context=TravelContext.model_validate_json(json.dumps(fixture['context']))
            context.trip.context.activity_preferences=['coffee']
            for p in context.participants:p.interests=[];p.food_preferences=[]
            store=MemoryStore(Path(directory)/f'{index}.db',EvaluationEmbedding())
            pid=context.trip.participant_ids[0]
            data={'person_id':pid,'participant_ids':[pid],'content':'我一直喜欢安静的咖啡馆','source_reference':'evaluation:feedback','stable':True}
            if kind=='relationship':data.update(memory_type='relationship',relationship_id=context.relationships[0].relationship_id,participant_ids=context.trip.participant_ids)
            if kind=='trip':data.update(memory_type='trip',trip_id='previous-trip',destination='北京',participant_ids=context.trip.participant_ids)
            if kind=='irrelevant_person':data.update(person_id='unrelated',participant_ids=['unrelated'])
            stored=store.write([MemoryCandidate(**data)])
            observation=PlanningObservation.model_validate_json(json.dumps(fixture['observation']))
            # 本评估只比较记忆选择，不继承closed场景的人为关闭条件。
            from life_journey.tools.schemas import OpeningHours
            observation.places[0].opening_hours=OpeningHours()

            _,memories=store.retrieve(context)
            relevant=kind!='irrelevant_person'
            # 固定规划策略只用于证明信息可用性，不调用真实Planner、不当作推荐收益。
            baseline='通用城市活动'
            personalized='安静咖啡馆' if memories else baseline
            expected='安静咖啡馆' if relevant else baseline
            itinerary=DraftItinerary.model_validate_json(json.dumps(fixture['draft']))
            itinerary.summary=personalized
            validation=validate_itinerary(context,itinerary,observation)
            rows.append({'case':kind,'no_memory_alignment':float(baseline==expected),'with_memory_alignment':float(personalized==expected),
                'retrieval_relevance':float(all(m.memory_id==stored[0].memory_id for m in memories) and bool(memories)==relevant),
                'unsupported_personalization':float(not relevant and bool(memories)),'hard_violation_rate':float(not validation.valid)})
    return {'kind':'offline_fake_embeddings_and_scripted_planner','case_count':len(rows),
        'preference_alignment_no_memory':sum(r['no_memory_alignment'] for r in rows)/len(rows),
        'preference_alignment_with_memory':sum(r['with_memory_alignment'] for r in rows)/len(rows),
        'hard_violation_rate':sum(r['hard_violation_rate'] for r in rows)/len(rows),'hard_violation_note':'固定脚本草稿经deterministic Validator检查，不代表真实LLM质量',
        'memory_relevance':sum(r['retrieval_relevance'] for r in rows)/len(rows),
        'unsupported_personalization_rate':sum(r['unsupported_personalization'] for r in rows)/len(rows),'cases':rows}

if __name__=='__main__':print(json.dumps(evaluate(),ensure_ascii=False,indent=2))
