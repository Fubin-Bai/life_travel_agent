"""高德 Web Service 适配器；只在此处解析原始响应，Key 仅从环境读取。"""
import logging
import os
import re
from datetime import datetime, timezone
import httpx
from pydantic import ValidationError
from .base import ToolConfigurationError, ToolRequestError, ToolResponseError, UnsupportedDestinationError
from .schemas import CityRequest, MainlandCity, Coordinates, Place, PlaceSearchRequest, PlaceSearchResult, RouteRequest, RouteResult

from .opening_hours import normalize_opening_hours

BASE_URL = 'https://restapi.amap.com'


def optional_text(value):
    """只规范化合理空值；其他类型原样交给核心字段的严格校验。"""
    if value is None or value == []:
        return None
    if isinstance(value, str):
        return value.strip() or None
    return value


class AmapPlaceTools:
    """每次操作一次 HTTP 请求，无重试/跳转；支持离线 mock transport。"""
    def __init__(self, *, transport: httpx.BaseTransport | None = None):
        """凭据不进入公开配置/repr；压低 HTTP 库日志，避免 Key 查询串外泄。"""
        key = os.environ.get('AMAP_WEB_SERVICE_KEY', '').strip()
        if not key:
            raise ToolConfigurationError('AMAP_WEB_SERVICE_KEY 未配置')
        self._key = key
        # httpx 的 INFO 请求日志含 URL；httpcore DEBUG 也不应记录请求头/查询串。
        for name in ('httpx', 'httpcore'):
            logging.getLogger(name).setLevel(logging.WARNING)
        self._client = httpx.Client(base_url=BASE_URL, timeout=5.0, follow_redirects=False, transport=transport)

    def close(self):
        """关闭自有 HTTP 连接，不保存搜索历史。"""
        self._client.close()

    def _request(self, path: str, params: dict) -> dict:
        """只输出固定安全错误；不透传异常、info 或包含 Key 的请求对象。"""
        try:
            response = self._client.get(path, params={**params, 'key': self._key, 'output': 'JSON'})
            response.raise_for_status()
        except httpx.TimeoutException:
            raise ToolRequestError('高德请求超时，请稍后重试') from None
        except httpx.HTTPError:
            raise ToolRequestError('高德请求失败，请检查网络或服务状态') from None
        try:
            data = response.json()
        except (ValueError, UnicodeError):
            raise ToolResponseError('高德返回非 JSON 响应') from None
        if not isinstance(data, dict):
            raise ToolResponseError('高德响应结构错误')
        if data.get('status') != '1' or data.get('infocode') != '10000':
            code = data.get('infocode')
            code = code if isinstance(code, str) and re.fullmatch(r'\d{5}', code) else 'unknown'
            raise ToolResponseError(f'高德 API 错误（代码 {code}），请检查 Key 权限/配额') from None
        return data

    def resolve_city(self, request: CityRequest) -> MainlandCity:
        """用行政区查询唯一匹配中文城市或编码，不接受全国/省/海外回退。"""
        data = self._request('/v3/config/district', {'keywords':request.destination, 'subdistrict':0, 'extensions':'base'})
        rows = data.get('districts')
        if not isinstance(rows, list):
            raise ToolResponseError('高德城市响应结构错误')
        matches=[]
        for row in rows:
            if not isinstance(row, dict):
                raise ToolResponseError('高德城市条目错误')
            name, code = row.get('name'), row.get('adcode')
            if not isinstance(name, str) or not isinstance(code, str):
                raise ToolResponseError('高德城市字段格式错误')
            if request.destination in {name, name.removesuffix('市'), code}:
                if row.get('level') == 'city' or (row.get('level') == 'province' and code in {'110000','120000','310000','500000'}):
                    try:
                        matches.append(MainlandCity(name=name, adcode=code))
                    except ValidationError:
                        pass
        if len(matches) != 1:
            raise UnsupportedDestinationError('V1 仅支持唯一可确认的中国大陆单个城市，请填写中文城市名或城市行政编码')
        return matches[0]

    def search_places(self, request: PlaceSearchRequest) -> PlaceSearchResult:
        """请求 all 以取得同城校验所需 adcode；仅投影必要 POI 字段。

        base 在真实响应中可能缺 adcode；不为兼容而跳过城市校验或伪造编码。
        """
        data = self._request('/v3/place/text', {'keywords':request.keyword, 'city':request.city.adcode,
                             'citylimit':'true', 'offset':request.limit, 'page':1, 'extensions':'all'})
        rows = data.get('pois')
        if not isinstance(rows, list):
            raise ToolResponseError('高德地点校验失败：pois 必须是列表')
        fetched_at = datetime.now(timezone.utc)
        places = []
        seen_ids = set()
        # limit 是本地输出上限，不能依赖 Provider 一定按 offset 返回相同数量。
        # 只投影要使用的前 limit 项；忽略非核心原始字段，不做全量响应建模。
        for index, row in enumerate(rows[:request.limit]):
            prefix = f'pois[{index}]'
            if not isinstance(row, dict):
                raise ToolResponseError(f'高德地点校验失败：{prefix} 必须是对象')
            for field in ('id', 'name', 'location', 'adcode'):
                if field not in row:
                    raise ToolResponseError(f'高德地点校验失败：{prefix}.{field} 缺失')
            try:
                lon, lat = row['location'].split(',')
                longitude, latitude = float(lon), float(lat)
            except (ValueError, TypeError, AttributeError):
                raise ToolResponseError(f'高德地点校验失败：{prefix}.location 必须是经度,纬度') from None
            try:
                place = Place(place_id=row['id'], name=row['name'],
                              address=optional_text(row.get('address')),
                              category=optional_text(row.get('type')), adcode=row['adcode'],
                              location=Coordinates(longitude=longitude, latitude=latitude),
                              opening_hours=normalize_opening_hours(row.get('biz_ext'), fetched_at))
            except ValidationError as exc:
                # 仅输出字段路径，不回显输入值/Provider原文，避免敏感信息进入错误日志。
                parts = list(exc.errors(include_input=False, include_context=False)[0]['loc'])
                if parts and parts[0] in {'longitude', 'latitude'}:
                    parts.insert(0, 'location')
                if parts:
                    parts[0] = {'place_id': 'id', 'category': 'type'}.get(parts[0], parts[0])
                field_path = '.'.join(str(part) for part in parts) or 'core_fields'
                raise ToolResponseError(f'高德地点校验失败：{prefix}.{field_path}') from None
            if not request.city.contains(place.adcode):
                raise ToolResponseError(f'高德地点校验失败：{prefix}.adcode 超出当前城市')
            if place.place_id in seen_ids:
                raise ToolResponseError(f'高德地点校验失败：{prefix}.id 重复')
            seen_ids.add(place.place_id)
            places.append(place)
        return PlaceSearchResult(request=request, status='ok' if places else 'empty', places=places,
                                 fetched_at=fetched_at)

    def route(self, request: RouteRequest) -> RouteResult:
        """按明确模式采用第一条方案；仅投影米/秒，不保证未来班次或出行。"""
        def coordinate(place):
            """高德要求经度在前，小数最多六位。"""
            return f'{place.location.longitude:.6f},{place.location.latitude:.6f}'
        mode = request.mode
        path = 'transit/integrated' if mode == 'transit' else mode
        params = {'origin': coordinate(request.origin), 'destination': coordinate(request.destination)}
        if mode == 'transit':
            params.update(city=request.city.name, cityd=request.city.name, strategy=0, nightflag=0)
        elif mode == 'driving':
            params.update(strategy=0, extensions='base')
        data = self._request('/v3/direction/' + path, params)
        try:
            paths = data['route']['transits' if mode == 'transit' else 'paths']
            if not isinstance(paths, list):
                raise ValueError()
            timestamp = datetime.now(timezone.utc)
            if not paths:
                return RouteResult(request=request, status='no_route', fetched_at=timestamp)
            def integer(value):
                """仅接受非负整数字符串，不截断小数或把空数组变成零。"""
                if not isinstance(value, str) or not re.fullmatch(r'\d+', value):
                    raise ValueError()
                return int(value)
            def optional_integer(value):
                """辅助字段异常仅记未知，不污染已知总时长。"""
                try:
                    return integer(value)
                except ValueError:
                    return None
            first = paths[0]
            extra = {}
            if mode == 'transit':
                extra['walking_distance_m'] = optional_integer(first.get('walking_distance'))
                segments = first.get('segments')
                rides = 0
                reliable = isinstance(segments, list) and bool(segments)
                for segment in segments if reliable else []:
                    if not isinstance(segment, dict) or segment.get('railway') or segment.get('taxi'):
                        reliable = False
                        break
                    bus = segment.get('bus', {})
                    lines = bus.get('buslines') if isinstance(bus, dict) else None
                    if not isinstance(lines, list):
                        reliable = False
                        break
                    if lines:
                        # buslines是同一乘车段的备选线路，不是换乘次数。
                        if len(lines) != 1 or not isinstance(lines[0], dict):
                            reliable = False
                            break
                        rides += 1
                extra['transfer_count'] = max(0, rides - 1) if reliable and rides else None
            distance = optional_integer(first.get('distance')) if mode == 'transit' else integer(first['distance'])
            return RouteResult(request=request, status='ok', distance_m=distance,
                               duration_s=integer(first['duration']), fetched_at=timestamp, **extra)
        except (KeyError, ValueError, TypeError, IndexError, AttributeError):
            raise ToolResponseError('高德路线数据缺失或格式不合法') from None
