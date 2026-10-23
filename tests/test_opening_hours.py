"""营业时间规范化、未来weekday条件判断与规划防伪；所有测试完全离线。"""
import json
from datetime import date, datetime, timezone
import httpx
import pytest
from pydantic import ValidationError
from life_journey.tools import (OpeningHours, OpeningInterval, WeekdayOpening, PlaceSearchRequest, MainlandCity)
from life_journey.tools.opening_hours import normalize_opening_hours, check_opening_hours, build_opening_checks
from life_journey.application.planning import run_planning, build_planning_prompt
from life_journey.llm.base import LLMResponseError
from test_amap_tools import make_tools, ok, raw_place, place
from test_planning_observation import mainland_context, FakeTools
from life_journey.application.planning_observation import collect_planning_observation
from test_planning import FakePlanningClient

FETCHED = datetime(2026,10,23,2,0,tzinfo=timezone.utc)
MONDAY = date(2030,1,7)
TUESDAY = date(2030,1,8)


def with_hours(text, id='p1'):
    """构造固定来源周规则，明确抓取时间与未来旅行日期不同。"""
    result=place(id)
    result.opening_hours=normalize_opening_hours({'opentime2':text},FETCHED)
    return result


def test_future_weekday_open_and_closed_windows():
    """Input：2026抓取的周二至周日09–17规则，2030周二；Expected Output：上午/下午有窗口、晚上关闭且仍需核实；测试目的为使用旅行weekday而非抓取当天。"""
    candidate=with_hours('周二至周日 09:00-17:00；周一闭馆')
    assert candidate.opening_hours.status=='known'
    morning=check_opening_hours(candidate,TUESDAY,'morning')
    assert morning.status=='open' and morning.available_intervals==[OpeningInterval(start_minute=540,end_minute=720)]
    assert morning.needs_verification is True
    assert check_opening_hours(candidate,TUESDAY,'afternoon').status=='open'
    assert check_opening_hours(candidate,TUESDAY,'evening').status=='closed'
    assert candidate.opening_hours.source_text=='周二至周日 09:00-17:00；周一闭馆'
    assert candidate.opening_hours.fetched_at==FETCHED
    assert candidate.opening_hours.timezone=='Asia/Shanghai'


def test_monday_closure_does_not_infer_other_days():
    """Input：仅周一闭馆；Expected Output：周一全闭，周二未知；测试目的为缺失规则不能被推断成开门或关门。"""
    candidate=with_hours('周一闭馆')
    assert MONDAY.weekday()==0
    for period in ('morning','afternoon','evening'):
        assert check_opening_hours(candidate,MONDAY,period).status=='closed'
        assert check_opening_hours(candidate,TUESDAY,period).status=='unknown'


@pytest.mark.parametrize('biz_ext',[
    None, [], {}, {'opentime2':[]}, {'opentime2':''}, {'opentime2':'   ','open_time':[]},
    {'opentime2':['周一至周日 09:00-17:00']}, {'opentime2':123}, {'opentime2':{'text':'每天09:00-17:00'}},
    {'open_time':'09:00-17:00'}, {'opentime2':'周一至周日 18:00-02:00'},
    {'opentime2':'周一至周日 09:00-17:00 星期一以外随缘'},
    {'opentime2':'周二至周日 09:00-17:00；奇怪格式'},
])
def test_missing_empty_and_mixed_hours_are_unknown(biz_ext):
    """Input：缺失、[]、空文本、异常类型、裸今日时间、跨夜/混合格式；Expected Output：unknown空周表；测试目的为坏营业信息不伪造周规则。"""
    hours=normalize_opening_hours(biz_ext,FETCHED)
    assert hours.status=='unknown' and hours.weekly==[]


@pytest.mark.parametrize('text',[
    '周二至周日 09:00-17:00；周一闭馆，节假日以官方通知为准',
    '每天09:00-17:00，临时调整',
    '旺季每天08:00-18:00；淡季每天09:00-17:00',
    '每天09:00-17:00（法定节假日除外）',
])
def test_exceptions_are_unknown_even_if_fallback_looks_simple(text):
    """Input：节假日/临时/旺淡季文本和简单fallback；Expected Output：unknown不降级为简单开门规则；测试目的为例外不能被短字段掩盖。"""
    hours=normalize_opening_hours({'opentime2':text,'open_time':'每天09:00-17:00'},FETCHED)
    assert hours.status=='unknown' and hours.unknown_reason=='exceptions_need_verification'


@pytest.mark.parametrize('text,status',[
    ('每天24小时营业','open'),('周一至周日 00:00-24:00','open'),
    ('永久停业','closed'),('周一至周日 全天关闭','closed'),
])
def test_unambiguous_daily_rules(text,status):
    """Input：明确24小时/固定闭店；Expected Output：相应周规则状态；测试目的为支持最小明确场景而非自然语言通用解析。"""
    candidate=with_hours(text)
    assert candidate.opening_hours.status=='known'
    assert check_opening_hours(candidate,TUESDAY,'evening').status==status


def test_multiple_intervals_and_conflicting_rules():
    """Input：午休分段和重复星期规则；Expected Output：两个窗口正确、冲突unknown；测试目的为不把午休时间当作营业且不猜覆盖优先级。"""
    candidate=with_hours('每天09:00-12:00 14:00-18:00')
    check=check_opening_hours(candidate,TUESDAY,'afternoon')
    assert check.available_intervals==[OpeningInterval(start_minute=840,end_minute=1080)]
    assert with_hours('每天09:00-17:00；周一闭馆').opening_hours.status=='unknown'


def test_adapter_reuses_search_response_and_keeps_bad_hours_poi(monkeypatch):
    """Input：已有all搜索返回营业文本/坏数组；Expected Output：一次HTTP即可规范化，坏营业不丢POI；测试目的为零新增请求且核心字段保持严格。"""
    calls=[]
    def handler(request):
        """在同一Provider搜索中提供两种营业形状。"""
        calls.append(request)
        first=raw_place('p1');first['biz_ext']={'opentime2':'周一至周日 09:00-17:00','open_time':[]}
        second=raw_place('p2');second['biz_ext']={'opentime2':[],'open_time':['异常']}
        return httpx.Response(200,json=ok(pois=[first,second]))
    tools=make_tools(monkeypatch,handler)
    try:
        result=tools.search_places(PlaceSearchRequest(city=MainlandCity(name='北京',adcode='110000'),keyword='展馆'))
        assert len(calls)==1 and calls[0].url.params['extensions']=='all'
        assert len(result.places)==2
        assert result.places[0].opening_hours.status=='known'
        assert result.places[1].opening_hours.status=='unknown'
        assert result.places[0].opening_hours.fetched_at==result.fetched_at
        assert 'biz_ext' not in result.places[0].model_dump()
    finally:tools.close()


def observation_with_hours(context, texts):
    """构造独立候选池，仅变营业规则，不改变人物或TripContext。"""
    observation=collect_planning_observation(context,FakeTools())
    for candidate in observation.places:
        candidate.opening_hours=normalize_opening_hours({'opentime2':texts.get(candidate.place_id)},FETCHED)
    observation.opening_checks=build_opening_checks(observation.places,context.trip.start_date,context.trip.end_date)
    return observation


def located_client(place_id='p1', description='按明确兴趣安排活动。', title='参观候选地点'):
    """产生结构正确的模型结果，实际营业由应用层重新判断。"""
    def mutate(data):
        """即使模型伪造标签，也不能影响后端判断。"""
        for day in data['days']:
            for activity in day['activities']:
                activity.update(place_id=place_id,description=description,title=title,opening_status='open_by_weekly_rule',opening_note='模型标签不能作为事实')
    return FakePlanningClient(mutate=mutate)


def test_closed_not_returned_and_same_class_alternative_allowed():
    """Input：同类p1闭店、p2每日开门，模型分别选它们；Expected Output：p1拒绝、p2返回周规则窗口；测试目的为closed不能进入最终行程且可用替代。"""
    context,state=mainland_context()
    observation=observation_with_hours(context,{'p1':'每天全天关闭','p2':'每天09:00-17:00'})
    observation.places[0].category=observation.places[1].category='博物馆'
    with pytest.raises(LLMResponseError,match='关闭'):
        run_planning(context,state,located_client('p1'),observation)
    result=run_planning(context,state,located_client('p2'),observation)
    for day in result.itinerary.days:
        assert day.activities[0].opening_status=='open_by_weekly_rule'
        assert '仍需核实' in day.activities[0].opening_note
    payload=json.loads(build_planning_prompt(context,observation).user_prompt)
    assert payload['trip_date_weekdays']['2026-11-10']==1
    assert payload['tool_observation']['opening_checks']
    assert '相同 source_keywords/类别' in build_planning_prompt(context,observation).system_prompt


def test_unknown_label_is_recomputed_not_trusted():
    """Input：未知营业但模型自填open标签；Expected Output：后端覆盖unknown与核实提示，输入不变；测试目的为POI存在不等于verified open。"""
    context,state=mainland_context();observation=observation_with_hours(context,{})
    before=observation.model_dump()
    result=run_planning(context,state,located_client(),observation)
    assert result.itinerary.days[0].activities[0].opening_status=='unknown'
    assert '未知' in result.itinerary.days[0].activities[0].opening_note
    assert observation.model_dump()==before


@pytest.mark.parametrize('text', ['已确认营业，可以放心到访。','verified open','所有地点均正常营业。'])
def test_unknown_cannot_be_presented_as_verified_open(text):
    """Input：unknown POI的肯定营业文案；Expected Output：LLMResponseError；测试目的为不能用自然语言绕过未知状态。"""
    context,state=mainland_context();observation=observation_with_hours(context,{})
    with pytest.raises(LLMResponseError,match='已确认营业'):
        run_planning(context,state,located_client(description=text),observation)


def test_conditional_language_is_not_false_guarantee():
    """Input：需核实是否正常营业；Expected Output：允许且显示unknown；测试目的为不误拒绝否定或待核实文案。"""
    context,state=mainland_context();observation=observation_with_hours(context,{})
    result=run_planning(context,state,located_client(description='出发前需核实是否正常营业。'),observation)
    assert result.itinerary.days[0].activities[0].opening_status=='unknown'


def test_all_closed_can_explain_no_verified_place_without_invention():
    """Input：全部候选关闭且模型只留通用自由活动；Expected Output：无POI引用并明确未找到可验证地点；测试目的为无替代不编造事实。"""
    context,state=mainland_context();observation=observation_with_hours(context,{'p1':'永久停业','p2':'永久停业'})
    result=run_planning(context,state,located_client(None,title='自由活动，待需求核实'),observation)
    assert '未找到可验证地点' in result.itinerary.summary
    assert all(a.place_id is None for d in result.itinerary.days for a in d.activities)


def test_closed_exact_name_cannot_bypass_with_null_id():
    """Input：闭店POI名称写入活动却不给ID；Expected Output：拒绝缺ID结果；测试目的为不通过null绕过营业检查。"""
    context,state=mainland_context();observation=observation_with_hours(context,{'p1':'永久停业','p2':'永久停业'})
    with pytest.raises(LLMResponseError,match='缺少place_id'):
        run_planning(context,state,located_client(None,title='p1'),observation)


def test_bounded_weekday_matrix_and_strict_schema():
    """Input：跨多年日期与坏规范化规则；Expected Output：最多7×3项/地点、无伪造周表；测试目的为多周日期不膨胀且Schema保持严格。"""
    checks=build_opening_checks([with_hours('每天09:00-17:00')],date(2030,1,1),date(2035,1,1))
    assert len(checks)==21
    with pytest.raises(ValidationError):OpeningHours(status='unknown',weekly=[WeekdayOpening(weekday=0,status='closed')])
    with pytest.raises(ValidationError):OpeningInterval(start_minute=1080,end_minute=120)


def test_confirmed_place_exists_does_not_claim_opening_verified():
    """Input：已确认地点存在但营业时间未知；Expected Output：允许unknown；测试目的为分开存在与营业，避免关键词启发式误伤正确声明。"""
    context,state=mainland_context();observation=observation_with_hours(context,{})
    result=run_planning(context,state,located_client(description='已确认地点存在，营业时间未知，需核实。'),observation)
    assert result.itinerary.days[0].activities[0].opening_status=='unknown'


def test_future_monday_closed_is_rejected_in_actual_itinerary():
    """Input：未来周一旅行、周一闭馆POI；Expected Output：拒绝安排；测试目的为最终校验使用真正旅行日期而不是抓取星期。"""
    context,state=mainland_context()
    context.trip.start_date=context.trip.end_date=MONDAY
    observation=observation_with_hours(context,{'p1':'周一闭馆','p2':'每天09:00-17:00'})
    with pytest.raises(LLMResponseError,match='关闭'):
        run_planning(context,state,located_client('p1'),observation)


@pytest.mark.parametrize('chosen,status',[('p1',502),('p2',200)])
def test_api_hours_closed_failure_or_open_alternative(tmp_path,chosen,status):
    """Input：同类永久闭店/简单周规则可用的fake候选；Expected Output：API拒绝closed、允许替代且不改Trip/state；测试目的为完整离线接线和失败原子边界。"""
    from fastapi.testclient import TestClient
    from life_journey.api import create_app
    from test_planning import ReadyInterviewClient,setup_trip
    class HoursTools(FakeTools):
        """复用既有fake，无新增请求，仅附加规范化营业信息。"""
        def search_places(self,request):
            """p1关闭，p2同类开放规则；没有真实HTTP。"""
            result=super().search_places(request)
            for candidate in result.places:
                candidate.category='博物馆'
                candidate.opening_hours=normalize_opening_hours({'opentime2':'永久停业' if candidate.place_id=='p1' else '每天09:00-17:00'},FETCHED)
            return result
    client_model=located_client(chosen)
    with TestClient(create_app(tmp_path/'hours.sqlite3',llm_client=ReadyInterviewClient(),planning_client=client_model,place_tools=HoursTools(),planning_mode='amap')) as client:
        trip=setup_trip(client);url=f"/api/trips/{trip['trip_id']}"
        client.post(url+'/interview',json={'user_message':'确认'})
        before=client.get(url).json();state=client.get(url+'/interview').json()
        response=client.post(url+'/planning')
        assert response.status_code==status,response.text
        if status==200:
            assert response.json()['itinerary']['days'][0]['activities'][0]['opening_status']=='open_by_weekly_rule'
            assert response.json()['observation']['opening_checks']
        assert client.get(url).json()==before and client.get(url+'/interview').json()==state
        assert len(client_model.prompts)==1


def test_unreferenced_activity_cannot_claim_verified_open():
    """Input：保留一项合法引用但另一通用活动声称已确认营业；Expected Output：拒绝；测试目的为不通过空ID逃过营业保证检查。"""
    context,state=mainland_context();observation=observation_with_hours(context,{})
    def mutate(data):
        """第一项故意无ID，第二项保证现有候选引用门槛已满足。"""
        for day in data['days']:
            day['activities'][0].update(place_id=None,title='自由活动',description='已确认营业，可以放心到访。')
            day['activities'].append({**day['activities'][0], 'place_id':'p1', 'description':'营业未知，需核实。'})
    with pytest.raises(LLMResponseError,match='已确认营业'):
        run_planning(context,state,FakePlanningClient(mutate=mutate),observation)


@pytest.mark.parametrize('text',[
    '不能保证当天正常营业，需核实。',
    '营业时间未知，需出行前向商家确认营业时间。',
    '出行前请再次确认营业时间。',
    '不保证未来当天正常营业。',
    '按当前周规则可能正常营业，仍需核实。',
])
def test_qualified_opening_language_does_not_fail_trip(text):
    """Input：否定保证/未来核实动作；Expected Output：允许且仍标unknown；测试文案边界，目的为不把核实提醒误判成已验证事实。"""
    context,state=mainland_context()
    observation=observation_with_hours(context,{})
    result=run_planning(context,state,located_client(description=text),observation)
    assert result.itinerary.days[0].activities[0].opening_status=='unknown'


@pytest.mark.parametrize('text',[
    '需核实价格，但已确认营业。',
    '不能保证交通，所有地点均正常营业。',
    '不是未知，而是已确认营业。',
    '已确认营业，可以放心前往，但建议出行前再看一次。',
])
def test_qualification_cannot_hide_positive_claim(text):
    """Input：前句提示/否定但后句明确保证；Expected Output：仍拒绝；测试分句作用域，目的为修误判同时保留unknown不可冒充verified的规则。"""
    context,state=mainland_context()
    observation=observation_with_hours(context,{})
    with pytest.raises(LLMResponseError):
        run_planning(context,state,located_client(description=text),observation)
