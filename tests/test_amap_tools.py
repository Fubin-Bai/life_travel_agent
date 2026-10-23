"""高德适配器完全离线；MockTransport 返回固定虚构数据。"""
import logging
import httpx
import pytest
from pydantic import ValidationError
from life_journey.tools import (AmapPlaceTools, CityRequest, MainlandCity, Coordinates, Place, PlaceSearchRequest,
    RouteRequest, ToolConfigurationError, ToolRequestError, ToolResponseError, UnsupportedDestinationError)


def ok(**data):
    """构造成功信封，保留原始 Provider 格式以测规范化边界。"""
    return {'status':'1','infocode':'10000',**data}


def raw_place(id='p1', name='虚构展馆', location='116.400000,39.900000', adcode='110101'):
    """虚构 POI，不声称实际存在。"""
    return {'id':id,'name':name,'location':location,'adcode':adcode,'address':[], 'type':'文化场馆','unused':'不传给规划'}


def place(id='p1'):
    """用于端点测试的已规范化虚构地点。"""
    return Place(place_id=id,name=id,adcode='110101',location=Coordinates(longitude=116.4,latitude=39.9))


def make_tools(monkeypatch, handler):
    """只注入假 Key 和内存 transport，测试不接受真实环境凭据。"""
    monkeypatch.setenv('AMAP_WEB_SERVICE_KEY','test-secret-do-not-log')
    return AmapPlaceTools(transport=httpx.MockTransport(handler))


def test_normalized_search_route_and_safe_logs(monkeypatch,caplog):
    """Input：城市/POI/驾车成功 JSON；Expected Output：规范化字段、城市限制/经纬顺序/米秒正确、日志无 Key；测试目的为覆盖真实 HTTP 边界且不透传原文。"""
    requests=[]
    def handler(request):
        """按路径返回一次固定响应，记录请求参数供断言。"""
        requests.append(request)
        if request.url.path.endswith('district'):
            return httpx.Response(200,json=ok(districts=[{'name':'北京市','adcode':'110000','level':'province'}]))
        if request.url.path.endswith('text'):
            return httpx.Response(200,json=ok(pois=[raw_place()]))
        return httpx.Response(200,json=ok(route={'paths':[{'distance':'1234','duration':'600','steps':['原文不透传']}]}))
    caplog.set_level(logging.DEBUG)
    tools=make_tools(monkeypatch,handler)
    try:
        city=tools.resolve_city(CityRequest(destination='北京'))
        found=tools.search_places(PlaceSearchRequest(city=city,keyword='展馆'))
        route=tools.route(RouteRequest(city=city,origin=place(),destination=place('p2')))
    finally:tools.close()
    assert found.status=='ok' and found.places[0].address is None
    assert 'unused' not in found.model_dump_json()
    assert route.distance_m==1234 and route.duration_s==600 and route.request.mode=='driving'
    assert requests[1].url.params['citylimit']=='true'
    assert requests[1].url.params['city']=='110000'
    assert requests[2].url.params['origin']=='116.400000,39.900000'
    assert 'test-secret' not in caplog.text
    assert 'key=' not in found.model_dump_json()+route.model_dump_json()
    assert tools.__repr__().find('test-secret')==-1


@pytest.mark.parametrize('payload',[
    ok(pois=[raw_place(location='bad')]),ok(pois=[raw_place(location='999,0')]),
    ok(pois=[raw_place(adcode='310101')]),ok(pois=[raw_place(),raw_place()]),
    ok(pois={}),ok(pois=[{'name':'缺少标识'}]),ok(),
])
def test_malformed_or_outside_search_fails(monkeypatch,payload):
    """Input：缺字段/非法坐标/跨城市/重复ID/错误列表；Expected Output：安全 ToolResponseError；测试目的为禁止静默接受坏数据或扩大范围。"""
    tools=make_tools(monkeypatch,lambda request:httpx.Response(200,json=payload))
    try:
        with pytest.raises(ToolResponseError):tools.search_places(PlaceSearchRequest(city=MainlandCity(name='北京市',adcode='110000'),keyword='测试'))
    finally:tools.close()


@pytest.mark.parametrize('kind', ['timeout','network','http','redirect','api','json','shape'])
def test_transport_api_and_json_errors_do_not_leak_key(monkeypatch,kind):
    """Input：超时/网络/HTTP/重定向/API错误/坏JSON/坏结构；Expected Output：明确安全错误且零重试；测试目的为失败不伪造且无URL凭据泄露。"""
    calls=[]
    def handler(request):
        """异常文本故意包含假凭据，验证不会透传。"""
        calls.append(request)
        if kind=='timeout':raise httpx.ReadTimeout('test-secret-do-not-log',request=request)
        if kind=='network':raise httpx.ConnectError(str(request.url),request=request)
        if kind=='http':return httpx.Response(500,text='test-secret-do-not-log')
        if kind=='redirect':return httpx.Response(302,headers={'Location':'https://example.com'})
        if kind=='api':return httpx.Response(200,json={'status':'0','infocode':'10001','info':'test-secret-do-not-log'})
        if kind=='json':return httpx.Response(200,text='bad')
        return httpx.Response(200,json=[])
    tools=make_tools(monkeypatch,handler)
    try:
        with pytest.raises((ToolRequestError,ToolResponseError)) as error:tools.resolve_city(CityRequest(destination='北京'))
        assert 'test-secret' not in str(error.value)
        assert 'https://' not in str(error.value)
        assert error.value.__context__ is None or error.value.__suppress_context__
        assert len(calls)==1
    finally:tools.close()


@pytest.mark.parametrize('row',[
    {'name':'香港特别行政区','adcode':'810000','level':'province'},
    {'name':'台北市','adcode':'710100','level':'city'},
    {'name':'澳门特别行政区','adcode':'820000','level':'province'},
    {'name':'浙江省','adcode':'330000','level':'province'},
    {'name':'东城区','adcode':'110101','level':'district'},
    {'name':'东京都','adcode':'990000','level':'city'},
])
def test_unsupported_destination_rejected(monkeypatch,row):
    """Input：港澳台/省份/区县/海外结果；Expected Output：UnsupportedDestinationError；测试目的为限定大陆单城市而非误用全国回退。"""
    tools=make_tools(monkeypatch,lambda request:httpx.Response(200,json=ok(districts=[row])))
    try:
        with pytest.raises(UnsupportedDestinationError):tools.resolve_city(CityRequest(destination=row['name']))
    finally:tools.close()


def test_empty_search_and_no_route_remain_explicit(monkeypatch):
    """Input：合法空POI与无路线；Expected Output：empty/no_route且数值None；测试目的为不把空结果伪造为零距离或虚构地点。"""
    tools=make_tools(monkeypatch,lambda r:httpx.Response(200,json=ok(pois=[]) if r.url.path.endswith('text') else ok(route={'paths':[]})))
    city=MainlandCity(name='北京',adcode='110000')
    try:
        assert tools.search_places(PlaceSearchRequest(city=city,keyword='不存在')).status=='empty'
        route=tools.route(RouteRequest(city=city,origin=place(),destination=place('p2')))
        assert route.status=='no_route' and route.distance_m is None and route.duration_s is None
    finally:tools.close()


@pytest.mark.parametrize('value',['-1','12.5',True,None])
def test_invalid_route_numeric_value_fails(monkeypatch,value):
    """Input：负数/小数/布尔/缺失路线距离；Expected Output：ToolResponseError；测试目的为防止转换截断或伪造数值。"""
    tools=make_tools(monkeypatch,lambda r:httpx.Response(200,json=ok(route={'paths':[{'distance':value,'duration':'100'}]})))
    try:
        with pytest.raises(ToolResponseError):tools.route(RouteRequest(city=MainlandCity(name='北京',adcode='110000'),origin=place(),destination=place('p2')))
    finally:tools.close()


def test_missing_key_and_schema_validation(monkeypatch):
    """Input：无Key及非法输入；Expected Output：配置错误/ValidationError；测试目的为工具不会携带默认凭据或接受未知坐标/模式。"""
    monkeypatch.delenv('AMAP_WEB_SERVICE_KEY',raising=False)
    with pytest.raises(ToolConfigurationError):AmapPlaceTools()
    with pytest.raises(ValidationError):Coordinates(longitude=float('nan'),latitude=30.0)
    with pytest.raises(ValidationError):MainlandCity(name='香港',adcode='810000')
    with pytest.raises(ValidationError):PlaceSearchRequest(city=MainlandCity(name='北京',adcode='110000'),keyword=' ',limit=6)
    with pytest.raises(ValidationError):RouteRequest(city=MainlandCity(name='北京',adcode='110000'),origin=place(),destination=place())


def test_plain_pytest_blocks_real_http_transport():
    """Input：未注入MockTransport的HTTP请求；Expected Output：立即AssertionError且不连网；测试目的为验证离线防护真实生效。"""
    with httpx.Client() as client:
        with pytest.raises(AssertionError,match='禁止真实 HTTP'):
            client.get('https://example.invalid')


def test_real_shaped_pois_with_extra_fields_and_local_limit(monkeypatch):
    """Input：故宫真实形状及非核心[]字段，返回2项而limit=1；Expected Output：首项合法保留、数量为1；测试目的为回归数量上限误报而不对非核心全字段建模。"""
    payload=ok(pois=[{
        'id':'B000A8UIN8','name':'故宫博物院','address':'景山前街4号',
        'type':'风景名胜;风景名胜;世界遗产|科教文化服务;博物馆;博物馆',
        'location':'116.397029,39.917839','adcode':'110101',
        'parent':[],'building':[],'tag':[],'postcode':[],
        'business_area':[],'photos':[{'title':[],'provider':[]}],
        'biz_ext':{'cost':[],'rating':'4.9'},
    },raw_place(id='B0FFKL520U',name='故宫博物院检票处')])
    tools=make_tools(monkeypatch,lambda request:httpx.Response(200,json=payload))
    try:
        result=tools.search_places(PlaceSearchRequest(city=MainlandCity(name='北京市',adcode='110000'),keyword='故宫博物院',limit=1))
        assert result.status=='ok' and len(result.places)==1
        first=result.places[0]
        assert first.place_id=='B000A8UIN8' and first.address=='景山前街4号'
        assert first.location.longitude==116.397029 and first.location.latitude==39.917839
        assert first.location.system=='GCJ-02'
        assert 'parent' not in first.model_dump() and 'biz_ext' not in first.model_dump()
    finally:tools.close()


@pytest.mark.parametrize('address', [None, [], '', '   '])
def test_reasonable_empty_address_is_allowed(monkeypatch,address):
    """Input：地址None/空列表/空白文本；Expected Output：None、其他核心信息保留；测试目的为兼容高德可选空值。"""
    row=raw_place();row['address']=address
    tools=make_tools(monkeypatch,lambda request:httpx.Response(200,json=ok(pois=[row])))
    try:
        result=tools.search_places(PlaceSearchRequest(city=MainlandCity(name='北京市',adcode='110000'),keyword='测试'))
        assert result.places[0].address is None
    finally:tools.close()


@pytest.mark.parametrize('field,value,error_path', [
    ('id', [], 'id'),('name',' ','name'),('address',{'unexpected':'value'},'address'),
    ('type',['非空异常列表'],'type'),('location',[],'location'),
    ('location','181,30','location.longitude'),('location','116,91','location.latitude'),
])
def test_core_validation_reports_safe_exact_path(monkeypatch,field,value,error_path):
    """Input：核心字段错误；Expected Output：含准确pois[0]字段路径的安全错误；测试目的为保持ID/名称/地址/类别/坐标严格而不暴露原始内容。"""
    row=raw_place();row[field]=value
    tools=make_tools(monkeypatch,lambda request:httpx.Response(200,json=ok(pois=[row])))
    try:
        with pytest.raises(ToolResponseError,match=r'pois\[0\]\.'+error_path.replace('.',r'\.')) as exc:
            tools.search_places(PlaceSearchRequest(city=MainlandCity(name='北京市',adcode='110000'),keyword='测试'))
        assert 'test-secret' not in str(exc.value) and 'unexpected' not in str(exc.value)
    finally:tools.close()


def test_search_requests_all_for_required_adcode(monkeypatch):
    """Input：base缺adcode而all包含的真实响应形状；Expected Output：请求all并保留城市校验；测试目的为回归真实smoke缺adcode的直接原因。"""
    calls=[]
    def handler(request):
        """模拟用户实测的字段差异，不访问真实高德。"""
        calls.append(request)
        row=raw_place(id='B000A8UIN8',name='故宫博物院',location='116.397029,39.917839')
        row.update(parent=[],building=[],tag=[],postcode=[],business_area=[])
        if request.url.params.get('extensions') != 'all':
            row.pop('adcode')
        return httpx.Response(200,json=ok(pois=[row]))
    tools=make_tools(monkeypatch,handler)
    try:
        result=tools.search_places(PlaceSearchRequest(city=MainlandCity(name='北京市',adcode='110000'),keyword='故宫博物院',limit=1))
        assert calls[0].url.params['extensions']=='all'
        assert calls[0].url.params['citylimit']=='true'
        assert result.places[0].adcode=='110101'
        assert 'parent' not in result.places[0].model_dump()
    finally:tools.close()
