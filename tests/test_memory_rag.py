"""V4写入、语义检索、隔离与反馈闭环；所有Embedding为离线fake。"""
import json
from datetime import datetime,timezone
import pytest
import httpx
from fastapi.testclient import TestClient
from life_journey.application.memory import MemoryStore,extract_candidates
from life_journey.schemas.memory import MemoryCandidate,FeedbackInput
from life_journey.llm.embedding import CompatibleEmbeddingProvider,validate_vectors
from life_journey.llm.base import LLMConfigurationError,LLMResponseError,LLMRequestError
from life_journey.api import create_app
from life_journey.schemas.agent import AgentDecision
from life_journey.application.agent_planning import run_agent_planning
from test_planning_observation import mainland_context,FakeTools
from test_planning import ReadyInterviewClient,setup_trip
from test_agent_planning import ScriptedAgent,call
from test_constraint_replanning import fixture,RepairClient

class FakeEmbedding:
    """仅测试语义簇；咖啡/cafe同向，滑雪垂直，绝非生产Embedding。"""
    model='fake-semantic-v1'
    def __init__(self):self.calls=[]
    def embed(self,texts):
        """固定非零向量，无网络或随机性。"""
        self.calls.append(texts)
        return [[1.0,0.0] if any(k in t for k in ('咖啡','cafe','coffee')) else [0.0,1.0] for t in texts]

def candidate(ctx,text='我一直喜欢咖啡馆',**changes):
    """显式人物记忆，不从Trip推断长期偏好。"""
    data=dict(person_id=ctx.trip.participant_ids[0],participant_ids=[ctx.trip.participant_ids[0]],content=text,source_reference='test:feedback',stable=True)
    data.update(changes)
    return MemoryCandidate(**data)

def coffee_context():
    """固定检索意图，去掉其他Profile兴趣避免测试词污染。"""
    ctx,_=mainland_context();ctx.trip.context.activity_preferences=['coffee'];ctx.trip.context.preferred_pace=None
    for p in ctx.participants:p.interests=[];p.food_preferences=[]
    return ctx

@pytest.mark.parametrize('text,count',[('我一直喜欢咖啡馆',1),('今天累想慢一点',0),('这次想吃烤鸭',0),('咖啡很好喝',0),('以后喜欢慢节奏。今天累',1)])
def test_stable_filter(text,count):
    """Input：稳定/临时/模糊反馈；Expected Output：仅明确长期偏好入候选；测试过滤，目的为不把单次Trip变长期。"""
    ctx=coffee_context();assert len(extract_candidates(text,ctx,ctx.trip.participant_ids[0]))==count


def test_store_dedup_supersede_and_current_override(tmp_path):
    """Input：重复慢节奏与新明确紧凑偏好；Expected Output：去重、旧记录inactive、新记忆与当前slow冲突不召回；测试冲突，目的为当前需求优先。"""
    from life_journey.storage import connect
    ctx=coffee_context();store=MemoryStore(tmp_path/'m.db',FakeEmbedding())
    slow=candidate(ctx,'我一直喜欢慢节奏',structured_tags={'preferred_pace':'slow'})
    first=store.write([slow])[0];assert store.write([slow])[0].memory_id==first.memory_id
    fast=candidate(ctx,'最近更喜欢紧凑行程',structured_tags={'preferred_pace':'fast'})
    second=store.write([fast])[0]
    with connect(store.path) as db:
        rows=[json.loads(r[0]) for r in db.execute('SELECT data FROM memories')]
    old=next(m for m in rows if m['memory_id']==first.memory_id)
    assert old['active'] is False and old['superseded_by']==second.memory_id
    ctx.trip.context.preferred_pace='slow';assert store.retrieve(ctx)[1]==[]


def test_semantic_topk_and_source_ranking(tmp_path):
    """Input：cafe查询/咖啡同义记忆及无关滑雪，confirmed与inferred同语义；Expected Output：语义召回、过滤无关、TopK与来源排序；测试RAG，目的为不是直接全历史拼接。"""
    ctx=coffee_context();store=MemoryStore(tmp_path/'m.db',FakeEmbedding())
    items=[candidate(ctx,f'我一直喜欢咖啡馆{i}',source_type='inferred',observation_count=2,confidence=0.5) for i in range(7)]
    items.append(candidate(ctx,'我确认长期喜欢咖啡',source_type='confirmed'))
    store.write(items);store.write([candidate(ctx,'一直喜欢滑雪')])
    query,retrieved=store.retrieve(ctx)
    assert len(retrieved)==5 and retrieved[0].source_type=='confirmed'
    assert all('咖啡' in m.content and m.hard_constraint is False for m in retrieved)
    assert all(m.source_reference and m.score>0 for m in retrieved)

@pytest.mark.parametrize('kind',['person','relationship','trip'])
def test_scope_isolation_before_embedding(tmp_path,kind):
    """Input：非参与者/错误组合/不同目的地记忆；Expected Output：零召回且不调用queryEmbedding；测试隔离顺序，目的为跨人跨关系不泄漏。"""
    ctx=coffee_context();embedding=FakeEmbedding();store=MemoryStore(tmp_path/'m.db',embedding)
    if kind=='person':c=candidate(ctx,person_id='other',participant_ids=['other'])
    elif kind=='relationship':c=candidate(ctx,memory_type='relationship',participant_ids=ctx.trip.participant_ids,relationship_id='wrong')
    else:c=candidate(ctx,memory_type='trip',participant_ids=ctx.trip.participant_ids,trip_id='old',destination='上海')
    store.write([c]);calls=len(embedding.calls)
    assert store.retrieve(ctx)[1]==[] and len(embedding.calls)==calls


def test_inferred_requires_repeated_observation(tmp_path):
    """Input：一次行为推断；Expected Output：不存储且不Embedding；测试写入门槛，目的为弱推断不能成为长期事实。"""
    ctx=coffee_context();embedding=FakeEmbedding();store=MemoryStore(tmp_path/'m.db',embedding)
    assert store.write([candidate(ctx,source_type='inferred')])==[] and embedding.calls==[]


def test_graph_memory_reaches_agent_and_planner(tmp_path):
    """Input：已存咖啡偏好与第二次旅行；Expected Output：TopK进入Agent/Planner，响应有来源，trace无全文；测试图接线，目的为RAG不是仅存储。"""
    ctx,state,_,draft=fixture();ctx.trip.context.activity_preferences=['coffee']
    store=MemoryStore(tmp_path/'m.db',FakeEmbedding());stored=store.write([candidate(ctx)])
    agent=ScriptedAgent(AgentDecision(tool_calls=[call()]));planner=RepairClient(draft)
    result=run_agent_planning(ctx,state,agent,planner,FakeTools(),validated=True,memory_store=store)
    assert result.memory_provenance[0]['memory_id']==stored[0].memory_id
    assert '我一直喜欢咖啡馆' in planner.prompt.user_prompt
    assert '我一直喜欢咖啡馆' in agent.prompts[0].messages[0]['content']
    assert '我一直喜欢咖啡馆' not in result.metrics['validation_trace']
    assert '当前Trip explicit' in planner.prompt.system_prompt


def test_feedback_api_and_temporary_no_provider(tmp_path):
    """Input：临时反馈/稳定反馈/错误主体/不存在旅行；Expected Output：仅合法稳定记忆入库，422/404隔离；测试API，目的为不保存全部反馈。"""
    embedding=FakeEmbedding()
    with TestClient(create_app(tmp_path/'api.db',embedding_provider=embedding)) as client:
        trip=setup_trip(client);url=f"/api/trips/{trip['trip_id']}/feedback"
        result=client.post(url,json={'feedback':'今天累了'})
        assert result.status_code==200 and result.json()['stored_memory_ids']==[] and embedding.calls==[]
        result=client.post(url,json={'feedback':'我一直喜欢咖啡馆','rating':5})
        assert result.status_code==200 and len(result.json()['stored_memory_ids'])==1
        assert client.post(url,json={'feedback':'我一直喜欢咖啡','person_id':'unrelated'}).status_code==422
        assert client.post('/api/trips/missing/feedback',json={'feedback':'我一直喜欢咖啡'}).status_code==404

@pytest.mark.parametrize('bad',[[[]],[[0.0,0.0]],[[float('nan')]],[[1.0],[1.0,2.0]],'invalid'])
def test_embedding_invalid_vectors(bad):
    """Input：空/零/非有限/混合维数/异常类型；Expected Output：安全LLMResponseError；测试Schema边界，目的为坏向量不落库。"""
    with pytest.raises(LLMResponseError):validate_vectors(bad,len(bad))


def test_real_provider_contract_via_mock_transport(monkeypatch):
    """Input：fakeHTTP服务返回逆序向量；Expected Output：恢复index顺序并不泄漏Key，HTTP失败无重试；测试生产adapter，目的为真实协议有离线覆盖。"""
    monkeypatch.setenv('LIFE_JOURNEY_EMBEDDING_URL','https://embedding.example.com/v1/embeddings')
    monkeypatch.setenv('LIFE_JOURNEY_EMBEDDING_MODEL','test-v1');monkeypatch.setenv('LIFE_JOURNEY_EMBEDDING_KEY','fake-key')
    calls=[]
    def handler(request):
        """只模拟结构化向量协议。"""
        calls.append(request)
        return httpx.Response(200,json={'data':[{'index':1,'embedding':[0,1]},{'index':0,'embedding':[1,0]}]})
    provider=CompatibleEmbeddingProvider(transport=httpx.MockTransport(handler))
    try:assert provider.embed(['a','b'])==[[1.0,0.0],[0.0,1.0]]
    finally:provider.close()
    assert len(calls)==1 and 'fake-key' not in str(calls[0].url)


def test_feedback_then_second_trip_memory_mode_api(tmp_path):
    """Input：第一旅反馈后新建第二旅并memory规划；Expected Output：记忆入图/Planner与来源返回、同库持久化；测试完整API闭环，目的为不是只测单函数。"""
    from life_journey.schemas import Trip
    from life_journey.schemas.validation import DraftItinerary
    from life_journey.application.replanning import DraftCallResult
    from test_planning import itinerary_payload
    class DynamicPlanner:
        """从实际API日期生成草稿，不使用固定错误Trip ID。"""
        def generate_draft(self,prompt):
            """只验证结构化Memory输入，输出由Validator再次检查。"""
            self.prompt=prompt
            trip=Trip.model_validate_json(json.dumps(json.loads(prompt.user_prompt)['trip']))
            data=itinerary_payload(trip)
            for d in data['days']:
                for a in d['activities']:a['place_id']='p1'
            return DraftCallResult(output=DraftItinerary.model_validate_json(json.dumps(data)),provider='fake',model='fake',latency_ms=0.0)
    planner=DynamicPlanner();agent=ScriptedAgent(AgentDecision(tool_calls=[call()]))
    with TestClient(create_app(tmp_path/'loop.db',planning_mode='memory',embedding_provider=FakeEmbedding(),
            llm_client=ReadyInterviewClient(),planning_client=planner,agent_client=agent,place_tools=FakeTools())) as client:
        first=setup_trip(client)
        stored=client.post(f"/api/trips/{first['trip_id']}/feedback",json={'feedback':'我一直喜欢安静咖啡馆'}).json()['stored_memory_ids']
        person_id=first['participant_ids'][0]
        person=client.get('/api/persons/'+person_id).json()
        client.put('/api/persons/'+person_id,json={**{k:v for k,v in person.items() if k!='person_id'},'interests':['coffee']})
        second=client.post('/api/trips',json={k:v for k,v in first.items() if k in {'participant_ids','destination','start_date','end_date','budget'}}).json()
        client.post(f"/api/trips/{second['trip_id']}/interview",json={'user_message':'确认'})
        result=client.post(f"/api/trips/{second['trip_id']}/planning")
        assert result.status_code==200,result.text
        assert result.json()['final_status']=='valid'
        assert result.json()['memory_provenance'][0]['memory_id']==stored[0]
        assert '安静咖啡馆' in planner.prompt.user_prompt


def test_embedding_failure_keeps_store_atomic(tmp_path):
    """Input：Embedding失败；Expected Output：无记忆落库；测试写入原子性，目的为失败不能留下伪向量或半条数据。"""
    class Broken(FakeEmbedding):
        """模拟服务不可用。"""
        def embed(self,texts):raise LLMRequestError('safe failure')
    ctx=coffee_context();path=tmp_path/'broken.db'
    with pytest.raises(LLMRequestError):MemoryStore(path,Broken()).write([candidate(ctx)])
    assert not path.exists()


def test_related_relationship_and_trip_are_retrievable(tmp_path):
    """Input：完全匹配组合和同城历史旅行；Expected Output：两类记忆可召回；测试正向scope，目的为隔离不能误杀合法记忆。"""
    ctx=coffee_context();store=MemoryStore(tmp_path/'scope.db',FakeEmbedding())
    store.write([candidate(ctx,'我们每次旅行喜欢咖啡',memory_type='relationship',relationship_id=ctx.relationships[0].relationship_id,participant_ids=ctx.trip.participant_ids),
        candidate(ctx,'以后旅行也喜欢咖啡',memory_type='trip',trip_id='old',destination=ctx.trip.destination,participant_ids=ctx.trip.participant_ids)])
    assert {m.memory_type for m in store.retrieve(ctx)[1]}=={'relationship','trip'}


def test_fixed_memory_evaluation():
    """Input：固定个人/关系/旅行/无关人物对照；Expected Output：作用域正确、无无关个性化；测试离线评估，目的为可重复而非真实LLM收益断言。"""
    from life_journey.evaluation.memory_rag import evaluate
    report=evaluate()
    assert report['case_count']==4 and report['memory_relevance']==1 and report['unsupported_personalization_rate']==0


def test_explicit_confirmation_and_scope(tmp_path):
    """Input：显式确认已存在记忆ID与无关记忆ID；Expected Output：前者confirmed且有确认时间，后者拒绝；测试确认流程，目的为不能把重复使用当确认。"""
    from life_journey.storage import connect
    ctx=coffee_context();store=MemoryStore(tmp_path/'confirm.db',FakeEmbedding());m=store.write([candidate(ctx)])[0]
    assert store.confirm([m.memory_id],ctx)==[m.memory_id]
    with connect(store.path) as db:confirmed=json.loads(db.execute('SELECT data FROM memories WHERE id=?',(m.memory_id,)).fetchone()[0])
    assert confirmed['source_type']=='confirmed' and confirmed['last_confirmed_at']
    other=store.write([candidate(ctx,person_id='other',participant_ids=['other'])])[0]
    with pytest.raises(ValueError):store.confirm([other.memory_id],ctx)


def test_explicit_opposite_interest_supersedes(tmp_path):
    """Input：长期喜欢咖啡后明确长期不喜欢咖啡；Expected Output：旧偏好失效，新偏好带avoid标签；测试有限类别冲突，目的为不保留两条同scope矛盾记录。"""
    ctx=coffee_context();store=MemoryStore(tmp_path/'opposite.db',FakeEmbedding());pid=ctx.trip.participant_ids[0]
    store.write(extract_candidates('我一直喜欢咖啡馆',ctx,pid))
    store.write(extract_candidates('我以后不喜欢咖啡馆',ctx,pid))
    retrieved=store.retrieve(ctx)[1]
    assert len(retrieved)==1 and retrieved[0].structured_tags['activity:coffee']=='avoid'


@pytest.mark.parametrize('text',['我一直在研究咖啡馆','我以后不喜欢慢节奏'])
def test_topic_mention_or_negated_pace_is_not_positive_preference(text):
    """Input：只提主题或否定慢节奏；Expected Output：主题不写记忆，否定不生成slow/fast正向标签；测试保守抽取，目的为不把语句误转成确定偏好。"""
    ctx=coffee_context();items=extract_candidates(text,ctx,ctx.trip.participant_ids[0])
    if '研究' in text:assert items==[]
    else:assert len(items)==1 and 'preferred_pace' not in items[0].structured_tags
