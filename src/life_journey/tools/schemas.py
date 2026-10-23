"""地图工具的最小规范化输入输出；不向业务层传递 Provider 原始 JSON。"""
from typing import Annotated, Literal, Self
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator
NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

MAINLAND_PREFIXES = frozenset('11 12 13 14 15 21 22 23 31 32 33 34 35 36 37 41 42 43 44 45 46 50 51 52 53 54 61 62 63 64 65'.split())


class ToolModel(BaseModel):
    """统一严格输入，拒绝未知字段；业务模型不依赖高德字段命名。"""
    model_config = ConfigDict(extra='forbid', strict=True)


class CityRequest(ToolModel):
    """仅接受单个城市中文名或行政编码，服务端再确认大陆城市范围。"""
    destination: NonEmptyString = Field(max_length=60)


class MainlandCity(ToolModel):
    """高德确认的大陆城市或四个直辖市；不是任意经纬度包围盒判断。"""
    name: NonEmptyString
    adcode: str = Field(pattern=r'^\d{6}$')

    @model_validator(mode='after')
    def mainland_only(self) -> Self:
        """拒绝境外、港澳台及省份/区县编码；直辖市用省级编码。"""
        if self.adcode[:2] not in MAINLAND_PREFIXES or not self.adcode.endswith('00'):
            raise ValueError('仅支持中国大陆城市')
        if self.adcode.endswith('0000') and self.adcode[:2] not in {'11', '12', '31', '50'}:
            raise ValueError('请提供城市，不是省份')
        return self

    def contains(self, adcode: str) -> bool:
        """校验 POI 行政代码属于所选城市，不把搜索建议当作范围确认。"""
        prefix = self.adcode[:2] if self.adcode[:2] in {'11','12','31','50'} else self.adcode[:4]
        return len(adcode) == 6 and adcode.isdigit() and adcode.startswith(prefix)


class Coordinates(ToolModel):
    """仅用高德 GCJ-02 坐标；经度在前，不混用 WGS84。"""
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    system: Literal['GCJ-02'] = 'GCJ-02'


class OpeningInterval(ToolModel):
    """当地日历日内的分钟范围，结束不包含；V1.2不猜测跨夜营业。"""
    start_minute: int = Field(ge=0, le=1439)
    end_minute: int = Field(ge=1, le=1440)

    @model_validator(mode='after')
    def positive_interval(self) -> Self:
        """拒绝空区间、倒序与隐式跨日。"""
        if self.end_minute <= self.start_minute:
            raise ValueError('营业时间区间必须同日递增')
        return self


class WeekdayOpening(ToolModel):
    """weekday采用Python约定0周一至6周日；未列出的日子不推断关闭。"""
    weekday: int = Field(ge=0, le=6)
    status: Literal['open', 'closed']
    intervals: list[OpeningInterval] = Field(default_factory=list)

    @model_validator(mode='after')
    def valid_intervals(self) -> Self:
        """关闭不应有区间，营业至少一个区间；不接受重叠。"""
        if (self.status == 'open') != bool(self.intervals):
            raise ValueError('营业状态与时间区间不一致')
        ranges = sorted((v.start_minute, v.end_minute) for v in self.intervals)
        if any(left[1] > right[0] for left, right in zip(ranges, ranges[1:])):
            raise ValueError('营业时间区间重叠')
        return self


class OpeningHours(ToolModel):
    """known仅表示部分明确周规则可解析，不保证未来实际营业。"""
    status: Literal['known', 'unknown'] = 'unknown'
    weekly: list[WeekdayOpening] = Field(default_factory=list, max_length=7)
    source_text: NonEmptyString | None = None
    source_field: Literal['biz_ext.opentime2', 'biz_ext.open_time'] | None = None
    source: Literal['amap', 'not_provided'] = 'not_provided'
    fetched_at: AwareDatetime | None = None
    timezone: Literal['Asia/Shanghai'] = 'Asia/Shanghai'
    unknown_reason: NonEmptyString | None = 'not_provided'

    @model_validator(mode='after')
    def consistent_knowledge(self) -> Self:
        """unknown不能携带猜测周表，known须有明确非重复日规则与来源。"""
        if (self.status == 'known') != bool(self.weekly):
            raise ValueError('营业知识状态与周规则不一致')
        if len({v.weekday for v in self.weekly}) != len(self.weekly):
            raise ValueError('周规则重复')
        if self.status == 'known' and (self.source != 'amap' or self.fetched_at is None or self.source_text is None):
            raise ValueError('已知周规则必须保留来源和时间')
        return self


class OpeningCheck(ToolModel):
    """当前抓取周规则在给定weekday/时段的条件判断，不是假日/未来承诺。"""
    place_id: NonEmptyString
    weekday: int = Field(ge=0, le=6)
    time_period: Literal['morning', 'afternoon', 'evening']
    status: Literal['open', 'closed', 'unknown']
    available_intervals: list[OpeningInterval] = Field(default_factory=list)
    reason: NonEmptyString
    needs_verification: bool = True


class Place(ToolModel):
    """保留真实POI基本字段和保守营业规则；不保证实际营业或价格。"""
    place_id: NonEmptyString
    name: NonEmptyString
    address: NonEmptyString | None = None
    category: NonEmptyString | None = None
    adcode: str = Field(pattern=r'^\d{6}$')
    location: Coordinates
    source_keywords: list[NonEmptyString] = Field(default_factory=list)
    opening_hours: OpeningHours = Field(default_factory=OpeningHours)


class PlaceSearchRequest(ToolModel):
    """限定已解析城市，一次一个关键词、小页数，不隐式扩大搜索范围。"""
    city: MainlandCity
    keyword: NonEmptyString = Field(max_length=100)
    limit: int = Field(default=3, ge=1, le=5)


class PlaceSearchResult(ToolModel):
    """empty 为真实查询空结果，绝不补造地点；时间为本次获取时间。"""
    request: PlaceSearchRequest
    status: Literal['ok', 'empty']
    places: list[Place]
    source: Literal['amap'] = 'amap'
    source_url: Literal['https://restapi.amap.com/v3/place/text'] = 'https://restapi.amap.com/v3/place/text'
    fetched_at: AwareDatetime

    @model_validator(mode='after')
    def validate_places(self) -> Self:
        """规范化结果仍须验证状态、数量、重复与城市范围。"""
        if (self.status == 'ok') != bool(self.places) or len(self.places) > self.request.limit:
            raise ValueError('地点状态或数量不一致')
        if len({p.place_id for p in self.places}) != len(self.places):
            raise ValueError('地点 ID 重复')
        if any(not self.request.city.contains(p.adcode) for p in self.places):
            raise ValueError('地点超出当前城市')
        return self


class RouteRequest(ToolModel):
    """两个已查询同城地点及明确模式；驾车默认仅为旧直接调用兼容。"""
    city: MainlandCity
    origin: Place
    destination: Place
    mode: Literal['driving', 'walking', 'transit'] = 'driving'

    @model_validator(mode='after')
    def validate_endpoints(self) -> Self:
        """两端需属于同一已确认城市并具有不同 POI ID。"""
        if self.origin.place_id == self.destination.place_id:
            raise ValueError('路线需要两个不同地点')
        if not all(self.city.contains(p.adcode) for p in (self.origin,self.destination)):
            raise ValueError('路线端点不属于当前城市')
        return self


class RouteResult(ToolModel):
    """有方向的分模式交通事实；unknown/no_route不伪造为零距离或可达。"""
    request: RouteRequest
    origin_place_id: NonEmptyString | None = None
    destination_place_id: NonEmptyString | None = None
    mode: Literal['driving', 'walking', 'transit'] | None = None
    status: Literal['ok', 'no_route', 'unknown']
    distance_m: int | None = Field(default=None, ge=0)
    duration_s: int | None = Field(default=None, ge=0)
    source: Literal['amap'] = 'amap'
    source_url: str = ''
    walking_distance_m: int | None = Field(default=None, ge=0)
    transfer_count: int | None = Field(default=None, ge=0)
    unknown_reason: Literal['request_failed', 'invalid_response'] | None = None
    fetched_at: AwareDatetime

    @model_validator(mode='after')
    def validate_status(self) -> Self:
        """成功需有时长；公交距离可缺失，未知/不可达必须无数值。"""
        for field, expected in (('origin_place_id', self.request.origin.place_id),
                                ('destination_place_id', self.request.destination.place_id), ('mode', self.request.mode)):
            if getattr(self, field) not in (None, expected):
                raise ValueError('路线端点或模式与请求不一致')
            setattr(self, field, expected)
        path = 'transit/integrated' if self.request.mode == 'transit' else self.request.mode
        expected_url = 'https://restapi.amap.com/v3/direction/' + path
        if self.source_url and self.source_url != expected_url:
            raise ValueError('路线来源与模式不一致')
        self.source_url = expected_url
        values = (self.distance_m, self.duration_s, self.walking_distance_m, self.transfer_count)
        if self.status == 'ok' and (self.duration_s is None or (self.request.mode != 'transit' and self.distance_m is None)):
            raise ValueError('成功路线缺少距离/时间')
        if self.status != 'ok' and any(v is not None for v in values):
            raise ValueError('无路线或未知路线不能包含数值')
        if self.request.mode != 'transit' and any(v is not None for v in values[2:]):
            raise ValueError('非公交路线不能包含公交字段')
        return self


class RetrievalKeyword(ToolModel):
    """查询词及其明确输入来源，检索变体不等于新增偏好。"""
    keyword: NonEmptyString = Field(max_length=100)
    source_fields: list[Literal['required_activities', 'activity_preferences', 'interests', 'food_preferences', 'shared_travel_preferences', 'fallback']]
    source_values: list[NonEmptyString]


class PlanningObservation(ToolModel):
    """供规划消费的有限候选池和有向路线；不是完整行程可执行性证明。"""
    city: MainlandCity
    searches: list[PlaceSearchResult]
    places: list[Place] = Field(min_length=1, max_length=12)
    routes: list[RouteResult]
    opening_checks: list[OpeningCheck] = Field(default_factory=list)
    retrieval_queries: list[RetrievalKeyword] = Field(default_factory=list)
    unqueried_keywords: list[str] = Field(default_factory=list)
    source: Literal['amap'] = 'amap'
