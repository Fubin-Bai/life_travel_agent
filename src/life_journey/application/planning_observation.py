"""有限、多类需求召回及固定路线查询；不让 LLM 选择工具或生成搜索词。"""
import math
import re
from datetime import datetime, timezone
from life_journey.schemas import TravelContext
from life_journey.tools import (PlaceTools, CityRequest, PlaceSearchRequest, RouteRequest, PlanningObservation, NoPlacesError)
from life_journey.tools.schemas import RetrievalKeyword, RouteResult
from life_journey.tools.base import ToolError, ToolResponseError

from life_journey.tools.opening_hours import build_opening_checks

MAX_SEARCHES = 10
PER_KEYWORD_LIMIT = 2
MAX_CANDIDATES = 12
MAX_ROUTES = 12
MAX_ROUTE_PAIRS = 6
WALKING_RADIUS_M = 1500
LONG_WALK_SECONDS = 1800
MAX_GENERATED_KEYWORDS = 24

# 这些是公开可检查的检索同义/近义词，不表示用户接受所有扩展活动。
KEYWORD_FAMILIES = {
    'coffee': (('咖啡店','咖啡馆','咖啡厅','咖啡','cafe','cafes','coffee','coffee shops'), ('咖啡店','咖啡馆')),
    'craft': (('工艺品店','工艺品','手工艺品','手工艺','手作店','手作','crafts','craft shops','handicrafts'), ('工艺品店','手作店')),
    'bar': (('清吧','酒吧','酒馆','bars','bar','quiet bars'), ('清吧','酒吧')),
    'architecture': (('现代建筑','建筑地标','modern architecture','architecture'), ('现代建筑','建筑地标')),
    'exhibition': (('艺术展','艺术展览','看展','展览','art exhibitions','art exhibition'), ('艺术展览','美术馆')),
    'museum': (('博物馆','museums','museum'), ('博物馆',)),
    'walk': (('城市散步','城市漫步','city walk','city walks'), ('步行街','特色街区')),
}
WEAK_TERMS = {'随便','随便玩','正常玩','都可以','不限','没有','无','none','anything','放松','轻松','慢节奏','紧凑行程'}
LOCAL_FOOD_ALIASES = {'当地美食','当地菜','特色美食','地方美食','local food','local cuisine'}


def normalized(value: str) -> str:
    """仅去空白及统一大小写，不进行不透明语义推断。"""
    return re.sub(r'\s+', ' ', value.strip()).casefold()


def family_names(text: str) -> set[str]:
    """用有限词表识别明确出现的类别；英文按词边界，避免匹配词内片段。"""
    value = normalized(text)
    found = set()
    for family, (aliases, _) in KEYWORD_FAMILIES.items():
        for alias in aliases:
            pattern = r'(?<![a-z])' + re.escape(alias) + r'(?![a-z])' if alias.isascii() else re.escape(alias)
            if re.search(pattern, value):
                found.add(family)
                break
    return found


def excluded(keyword: str, exclusions: list[str]) -> bool:
    """排除明确文本/已知同义类别；不声称覆盖任意自然语言否定。"""
    value = normalized(keyword)
    families = family_names(value)
    for item in exclusions:
        item = re.sub(r'^(?:不要安排|不想去|不喜欢|不去|不要|排除)\s*', '', normalized(item))
        if item and (item in value or families & family_names(item)):
            return True
    return False


def variants(value: str, city_name: str) -> list[str]:
    """先保留具体名称；已知类别用中文检索别名，本地美食仅在明确表达后扩展。"""
    key = normalized(value)
    city = city_name.removesuffix('市')
    if key in WEAK_TERMS:
        return []
    if key in LOCAL_FOOD_ALIASES or key == normalized(city + '特色美食'):
        return [city + '特色美食', '烤鸭', '涮肉'] if city == '北京' else [city + '特色美食', '地方菜']
    for aliases, searches in KEYWORD_FAMILIES.values():
        if key in aliases:
            return list(searches)
    # 具体店名/明确活动先原样检索；仅补少量命中类别的近义查询。
    result = [value.strip()]
    for family in KEYWORD_FAMILIES:
        if family in family_names(value):
            result.extend(KEYWORD_FAMILIES[family][1])
    return list(dict.fromkeys(result))[:3]


def build_retrieval_keywords(context: TravelContext, city_name: str) -> list[RetrievalKeyword]:
    """先覆盖每项明确需求的主词，再轮流补变体，最多生成24词、执行前10词。

    不读取MBTI/性别/关系标签；排除项仅用于过滤，不作为正向来源。
    """
    trip = context.trip.context
    sources = [('required_activities', v) for v in trip.required_activities]
    sources += [('activity_preferences', v) for v in trip.activity_preferences]
    sources += [('food_preferences', v) for p in context.participants for v in p.food_preferences]
    sources += [('interests', v) for p in context.participants for v in p.interests]
    sources += [('shared_travel_preferences', v) for r in context.relationships for v in r.shared_travel_preferences]
    groups = []
    for field, value in sources:
        if excluded(value, trip.excluded_activities):
            continue
        words = [word for word in variants(value, city_name) if not excluded(word, trip.excluded_activities)]
        if words:
            groups.append((field, value, words))
    if not groups:
        # 中性召回种子，不转成用户偏好；排除项同样生效。
        seeds = [word for word in ('风景名胜','文化场馆','城市广场') if not excluded(word, trip.excluded_activities)]
        groups = [('fallback', '未提供可检索的具体活动需求', seeds[:1])] if seeds else []
    keywords = {}
    # 先完成所有主词，再第二/第三变体，避免咖啡同义词抢占工艺品/清吧等需求。
    for index in range(3):
        for field, value, words in groups:
            if index >= len(words):
                continue
            word = words[index]
            key = normalized(word)
            if key not in keywords:
                if len(keywords) >= MAX_GENERATED_KEYWORDS:
                    continue
                keywords[key] = RetrievalKeyword(keyword=word, source_fields=[], source_values=[])
            query = keywords[key]
            if field not in query.source_fields:
                query.source_fields.append(field)
            if value not in query.source_values and len(query.source_values) < 4:
                query.source_values.append(value)
    return list(keywords.values())


def nearest_route_pairs(candidates):
    """按候选需求优先顺序取前六个起点的近邻；最多六个有向组合，不验证完整行程。

    坐标接近仅用于决定查哪些路线，不能当作真实道路距离。
    """
    pairs = []
    for origin in candidates:
        others = [p for p in candidates if p.place_id != origin.place_id]
        if not others:
            break
        def proximity(destination):
            """同城粗略投影距离用于查询优先级，名称/类别不参与距离判断。"""
            lat = math.radians((origin.location.latitude + destination.location.latitude) / 2)
            dx = (origin.location.longitude - destination.location.longitude) * math.cos(lat)
            dy = origin.location.latitude - destination.location.latitude
            return dx * dx + dy * dy, destination.place_id
        pairs.append((origin, min(others, key=proximity)))
    return pairs[:MAX_ROUTE_PAIRS]


def collect_planning_observation(context: TravelContext, tools: PlaceTools) -> PlanningObservation:
    """有限搜索、轮流取候选、按ID去重并记录所有命中关键词；失败不回退编造。"""
    city = tools.resolve_city(CityRequest(destination=context.trip.destination))
    keywords = build_retrieval_keywords(context, city.name)
    queries = keywords[:MAX_SEARCHES]
    searches = [tools.search_places(PlaceSearchRequest(city=city, keyword=query.keyword, limit=PER_KEYWORD_LIMIT)) for query in queries]
    by_id = {}
    source_keywords = {}
    for result in searches:
        for place in result.places:
            by_id.setdefault(place.place_id, place)
            source_keywords.setdefault(place.place_id, [])
            if result.request.keyword not in source_keywords[place.place_id]:
                source_keywords[place.place_id].append(result.request.keyword)
    candidates = {}
    for index in range(PER_KEYWORD_LIMIT):
        for result in searches:
            if index < len(result.places) and len(candidates) < MAX_CANDIDATES:
                place_id = result.places[index].place_id
                candidates.setdefault(place_id, by_id[place_id].model_copy(deep=True, update={'source_keywords': source_keywords[place_id]}))
    places = list(candidates.values())
    if not places:
        raise NoPlacesError('高德查询没有可用地点或正向检索词，请调整需求；未调用规划模型')
    routes = collect_routes(city, places, tools)
    return PlanningObservation(city=city, searches=searches, places=places, routes=routes,
                               opening_checks=build_opening_checks(places, context.trip.start_date, context.trip.end_date),
                               retrieval_queries=queries, unqueried_keywords=[q.keyword for q in keywords[MAX_SEARCHES:]])


def collect_routes(city, places, tools):
    """最多六个有向近邻组合、十二次请求；近处先步行，远处先公交。

    次选模式只补当前证据缺口，驾车不自动替代游客交通；地点候选不因距离被删除。
    """
    routes = []
    for origin, destination in nearest_route_pairs(places):
        latitude = math.radians((origin.location.latitude + destination.location.latitude) / 2)
        distance = 111320 * math.hypot((origin.location.longitude-destination.location.longitude)*math.cos(latitude),
                                      origin.location.latitude-destination.location.latitude)
        primary = 'walking' if distance <= WALKING_RADIUS_M else 'transit'
        modes = [primary]
        for mode in modes:
            if len(routes) >= MAX_ROUTES:
                break
            request = RouteRequest(city=city, origin=origin, destination=destination, mode=mode)
            try:
                result = tools.route(request)
            except ToolError as error:
                reason = 'invalid_response' if isinstance(error, ToolResponseError) else 'request_failed'
                result = RouteResult(request=request, status='unknown', unknown_reason=reason,
                                     fetched_at=datetime.now(timezone.utc))
            routes.append(result)
            if len(modes) == 1 and (result.status != 'ok' or (mode == 'walking' and result.duration_s > LONG_WALK_SECONDS)):
                modes.append('transit' if mode == 'walking' else 'walking')
    return routes
