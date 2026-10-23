"""多类需求检索与节奏回归，全部使用固定数据/fake，绝不访问真实API。"""
import json
from datetime import datetime, timezone
import pytest
from life_journey.application.planning_observation import build_retrieval_keywords, collect_planning_observation
from life_journey.application.planning import build_planning_prompt, run_planning
from life_journey.llm.base import LLMResponseError
from life_journey.tools import PlaceSearchResult, ToolRequestError, NoPlacesError
from test_amap_tools import place
from test_planning_observation import mainland_context, FakeTools
from test_planning import FakePlanningClient


def clean_context():
    """隔离测试输入，去掉历史fixture偏好以只比较目标变量。"""
    context,state=mainland_context()
    context.trip.context.activity_preferences=[]
    context.trip.context.required_activities=[]
    context.trip.context.excluded_activities=[]
    for person in context.participants:
        person.interests=[];person.food_preferences=[]
    for relation in context.relationships:
        relation.shared_travel_preferences=[]
    return context,state


def test_multiple_classes_get_base_keywords_before_variants():
    """Input：咖啡/工艺/清吧/建筑与明确地方美食；Expected Output：主词先覆盖五类、变体有限且有来源；测试目的为避免前三词垄断候选召回。"""
    context,_=clean_context()
    context.trip.context.activity_preferences=['咖啡店','工艺品店','清吧','现代建筑']
    context.participants[0].food_preferences=['当地美食']
    queries=build_retrieval_keywords(context,'北京市')
    words=[q.keyword for q in queries]
    assert words[:5]==['咖啡店','工艺品店','清吧','现代建筑','北京特色美食']
    assert all(word in words for word in ['咖啡馆','手作店','酒吧','建筑地标','烤鸭','涮肉'])
    assert queries[4].source_fields==['food_preferences']
    assert queries[4].source_values==['当地美食']
    assert '风景名胜' not in words


def test_semantic_duplicates_combine_provenance():
    """Input：多字段中咖啡馆/cafes/咖啡店；Expected Output：只搜两个别名且来源合并；测试目的为去重关键词而不丢掉解释依据。"""
    context,_=clean_context()
    context.trip.context.required_activities=['咖啡馆']
    context.trip.context.activity_preferences=['cafes']
    context.participants[0].interests=['咖啡店']
    queries=build_retrieval_keywords(context,'北京市')
    assert [q.keyword for q in queries]==['咖啡店','咖啡馆']
    assert queries[0].source_fields==['required_activities','activity_preferences','interests']


def test_exclusions_are_not_positive_queries_or_aliases():
    """Input：旧个人酒吧兴趣但本次排除清吧/迪士尼；Expected Output：不搜索酒吧别名和排除地点，咖啡仍召回；测试目的为排除项优先且不生成正向需求。"""
    context,_=clean_context()
    context.trip.context.activity_preferences=['咖啡店','清吧']
    context.participants[0].interests=['酒吧','迪士尼乐园']
    context.trip.context.excluded_activities=['清吧','迪士尼']
    words=[q.keyword for q in build_retrieval_keywords(context,'北京市')]
    assert words==['咖啡店','咖啡馆']


def test_local_food_is_not_added_without_explicit_request():
    """Input：北京目的地及咖啡兴趣；Expected Output：只有咖啡词，无烤鸭/涮肉；测试目的为城市不是用户饮食偏好证据。"""
    context,_=clean_context();context.participants[0].interests=['咖啡馆']
    assert [q.keyword for q in build_retrieval_keywords(context,'北京市')]==['咖啡店','咖啡馆']


@pytest.mark.parametrize('weak',[[],['随便玩'],['放松','都可以']])
def test_empty_or_weak_requests_have_transparent_fallback(weak):
    """Input：空/模糊偏好且无明确人物兴趣；Expected Output：一个中性种子、标记fallback，不自动补自然/SPA；测试目的为弱需求仍可控召回。"""
    context,_=clean_context();context.trip.context.activity_preferences=weak
    queries=build_retrieval_keywords(context,'北京市')
    assert len(queries)==1 and queries[0].keyword=='风景名胜'
    assert queries[0].source_fields==['fallback']


def test_profile_labels_do_not_change_queries():
    """Input：同需求、不同性别/MBTI/关系标签；Expected Output：关键词完全相同；测试目的为禁用刻板标签推断搜索词。"""
    context,_=clean_context();context.trip.context.activity_preferences=['工艺品店']
    before=[q.model_dump() for q in build_retrieval_keywords(context,'北京市')]
    context.participants[0].gender='female';context.participants[0].mbti='ENTP'
    context.relationships[0].relationship_type='partner'
    assert [q.model_dump() for q in build_retrieval_keywords(context,'北京市')]==before


def test_round_robin_candidates_sources_and_compact_prompt():
    """Input：五类需求和重复命中POI；Expected Output：每类首项先保留、ID去重、所有命中词保留，Prompt无重复端点正文；测试目的为覆盖与体积兼顾。"""
    class DiverseTools(FakeTools):
        """每个查询返回共用POI与特定POI，确保去重不会吞掉类别候选。"""
        def search_places(self,request):
            """使用固定地点，不修改调用者数据。"""
            self.calls.append(('search',request))
            return PlaceSearchResult(request=request,status='ok',places=[place(request.keyword),place('shared')],fetched_at=datetime.now(timezone.utc))
    context,state=clean_context()
    context.trip.context.activity_preferences=['咖啡店','工艺品店','清吧','现代建筑']
    context.participants[0].food_preferences=['当地美食']
    before=context.model_dump()
    tools=DiverseTools();observation=collect_planning_observation(context,tools)
    assert len([c for c in tools.calls if c[0]=='search'])==10
    assert len(observation.places)<=12 and len(observation.routes)<=12
    assert {'咖啡店','工艺品店','清吧','现代建筑','北京特色美食'} <= {p.place_id for p in observation.places}
    shared=[p for p in observation.places if p.place_id=='shared']
    assert len(shared)==1 and len(shared[0].source_keywords)==10
    payload=json.loads(build_planning_prompt(context,observation).user_prompt)['tool_observation']
    assert payload['places'][0]['source_keywords']
    assert payload['retrieval_queries'][0]['source_fields']==['activity_preferences']
    assert 'origin' not in payload['routes'][0] and 'origin_id' in payload['routes'][0]
    assert 'places' not in payload['searches'][0]
    assert context.model_dump()==before


def test_keyword_and_candidate_caps_and_determinism():
    """Input：大量明确需求；Expected Output：最多24生成词、前10搜索、12候选，固定输入固定查询；测试目的为请求与Prompt上限明确。"""
    context,_=clean_context();context.trip.context.required_activities=[f'需求{i}' for i in range(50)]
    queries=build_retrieval_keywords(context,'北京市')
    assert len(queries)==24
    assert queries==build_retrieval_keywords(context,'北京市')
    tools=FakeTools();observation=collect_planning_observation(context,tools)
    assert len(observation.retrieval_queries)==10
    assert len(observation.unqueried_keywords)==14


def test_tool_failure_stops_without_model_fallback():
    """Input：搜索第二次失败；Expected Output：ToolRequestError、后续搜索和路线不调用；测试目的为扩充检索不改变失败边界。"""
    class BrokenTools(FakeTools):
        """固定第二个搜索失败。"""
        def search_places(self,request):
            """首个成功不允许掩盖后续真实请求错误。"""
            if any(kind=='search' for kind,_ in self.calls):raise ToolRequestError('模拟超时')
            return super().search_places(request)
    context,_=clean_context();context.trip.context.activity_preferences=['咖啡店','工艺品店']
    tools=BrokenTools()
    with pytest.raises(ToolRequestError):collect_planning_observation(context,tools)
    assert not any(kind=='route' for kind,_ in tools.calls)


@pytest.mark.parametrize('pace,message,raises',[
    ('fast','本次按慢节奏安排。',True),
    ('fast','采用紧凑行程，咖啡休息穿插其中。',False),
    ('fast','不是慢节奏，而是紧凑探索。',False),
    ('fast','个人平时喜欢慢节奏，但本次采用紧凑探索。',False),
    ('slow','本次按慢节奏安排。',False),
])
def test_explicit_trip_pace_wins_over_profile(pace,message,raises):
    """Input：本次fast/slow与个人慢偏好、不同规划文案；Expected Output：仅拒绝fast被明确写成慢节奏，慢/否定/局部休息可接受；测试目的为修复明确冲突而不改Interview。"""
    context,state=clean_context();context.trip.context.preferred_pace=pace
    context.participants[0].preferred_pace='slow'
    def mutate(data):
        """同时设置理由，避免旧fake慢文案掩盖本用例目标。"""
        data['summary']=message
        for day in data['days']:
            for activity in day['activities']:activity['rationale']='符合明确咖啡兴趣'
    client=FakePlanningClient(mutate=mutate)
    if raises:
        with pytest.raises(LLMResponseError):run_planning(context,state,client)
    else:
        assert run_planning(context,state,client).itinerary.summary==message
    assert '本次节奏优先于个人/共同长期节奏' in client.prompts[0].system_prompt
    assert context.trip.context.preferred_pace==pace


def test_food_requirement_not_crowded_out_by_many_interests():
    """Input：四类本次偏好、大量个人兴趣与明确美食偏好；Expected Output：前10词含本地美食；测试目的为饮食类别不被长兴趣列表挤出。"""
    context,_=clean_context()
    context.trip.context.activity_preferences=['咖啡店','工艺品店','清吧','现代建筑']
    context.participants[0].interests=[f'兴趣{i}' for i in range(20)]
    context.participants[0].food_preferences=['当地美食']
    assert '北京特色美食' in [q.keyword for q in build_retrieval_keywords(context,'北京市')[:10]]
