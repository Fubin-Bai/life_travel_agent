"""独立地点工具接口和可安全展示的错误；不引入工具选择框架。"""
from typing import Protocol
from .schemas import CityRequest, MainlandCity, PlaceSearchRequest, PlaceSearchResult, RouteRequest, RouteResult


class ToolError(RuntimeError):
    """安全错误不附请求 URL、凭据或 Provider 原文。"""


class ToolConfigurationError(ToolError):
    """工具未配置。"""


class ToolRequestError(ToolError):
    """HTTP/网络/超时，不自动重试。"""


class ToolResponseError(ToolError):
    """API 状态或规范化响应不合法。"""


class UnsupportedDestinationError(ToolError):
    """目的地不在第一版支持范围或无法唯一确认。"""


class NoPlacesError(ToolError):
    """查询成功但没有可用于规划的地点，不回退编造。"""


class PlaceTools(Protocol):
    """确定性工作流只依赖规范化接口，不依赖高德 JSON/SDK。"""
    def resolve_city(self, request: CityRequest) -> MainlandCity:
        """确认大陆单城市范围。"""
        ...
    def search_places(self, request: PlaceSearchRequest) -> PlaceSearchResult:
        """查询候选地点。"""
        ...
    def route(self, request: RouteRequest) -> RouteResult:
        """按明确模式查询同城有向步行、公交或驾车参考路线。"""
        ...
