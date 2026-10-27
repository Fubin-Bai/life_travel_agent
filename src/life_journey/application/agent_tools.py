"""V2工具边界：参数、范围、配额与去重由Python管理，复用V1适配器。"""
import logging
from time import perf_counter
from pydantic import ValidationError
from life_journey.schemas.agent import (AgentBudget, AgentToolCall, AgentToolObservation,
    AgentActionTrace, SearchPlacesArguments, RouteArguments, tool_definitions)
from life_journey.tools import PlaceSearchRequest, RouteRequest, ToolError
from life_journey.tools.schemas import PlaceSearchResult
from .planning_observation import excluded
from life_journey.harness.runtime import call_fingerprint

ROUTE_MODES = {'get_walking_route':'walking', 'get_transit_route':'transit', 'get_driving_route':'driving'}
TOOL_ARGUMENTS = {'search_places':SearchPlacesArguments, **{name:RouteArguments for name in ROUTE_MODES}}




def error_observation(name: str, code: str) -> AgentToolObservation:
    """安全分类不回显任意模型参数、Provider响应或异常文本。"""
    return AgentToolObservation(name=name if name in TOOL_ARGUMENTS else 'unsupported_tool',status='error',error_code=code)


def sanitized_arguments(arguments) -> dict:
    """任意关键词可能含个人信息，只记长度；路线只记已验证候选ID。"""
    if isinstance(arguments,SearchPlacesArguments):
        return {'keyword_length':len(arguments.keyword),'limit':arguments.limit}
    if isinstance(arguments,RouteArguments):
        return {'origin_place_id':arguments.origin_place_id,'destination_place_id':arguments.destination_place_id}
    return {}


def execute_agent_tool(state: dict, call: AgentToolCall, tools, budget: AgentBudget, *, harness) -> AgentToolObservation:
    """更新仅限单次图状态；先验证/查缓存，再计真实执行预算，所有错误作为Observation。"""
    started=perf_counter()
    executed=False
    arguments=None
    known_name=call.name if call.name in TOOL_ARGUMENTS else 'unsupported_tool'
    hook_started=harness.tool_started(known_name)
    if not harness.admit_tool():
        result=error_observation(known_name,'total_budget_exhausted')
    else:
        result=None
        try:
            schema=TOOL_ARGUMENTS.get(call.name)
            if schema is None:
                result=error_observation(known_name,'unsupported_tool')
            else:
                arguments=schema.model_validate_json(call.arguments)
                if isinstance(arguments,SearchPlacesArguments):
                    city=state['city']
                    if arguments.city not in {city.name,city.name.removesuffix('市'),city.adcode,state['context'].trip.destination}:
                        result=error_observation(known_name,'city_out_of_scope')
                    elif arguments.limit > budget.max_search_limit:
                        result=error_observation(known_name,'search_limit_exceeded')
                    elif excluded(arguments.keyword,state['context'].trip.context.excluded_activities):
                        result=error_observation(known_name,'excluded_keyword')
                    else:
                        # 城市别名和关键词空白/大小写归一化，避免格式变化绕过重复保护。
                        arguments=arguments.model_copy(update={'city':city.adcode,'keyword':' '.join(arguments.keyword.split()).casefold()})
                elif any(pid not in state['places'] for pid in (arguments.origin_place_id,arguments.destination_place_id)):
                    result=error_observation(known_name,'unknown_place_id')
        except (ValidationError,ValueError,TypeError):
            result=error_observation(known_name,'invalid_arguments')
        if result is None:
            key=call_fingerprint(call.name,arguments)
            code,cached=harness.tool_permission(call.name,key,len(state['places']))
            if cached is not None:
                result=cached
            elif code:
                result=error_observation(known_name,code)
                if code!='duplicate_call_blocked':harness.cache[key]=result.model_copy(deep=True)
            else:
                executed=True
                try:
                    if call.name=='search_places':
                        request=PlaceSearchRequest(city=state['city'],keyword=arguments.keyword,limit=arguments.limit)
                        found=tools.search_places(request)
                        # 适配器和fake都必须满足同一规范；不允许注入其他请求的结果。
                        found=PlaceSearchResult.model_validate_json(found.model_dump_json())
                        if found.request != request:
                            raise ValueError('request mismatch')
                        allowed=[]
                        for place in found.places:
                            if excluded(place.name+' '+(place.category or ''),state['context'].trip.context.excluded_activities):
                                continue
                            if place.place_id not in state['places'] and len(state['places'])>=budget.max_candidates:
                                continue
                            chosen=state['places'].get(place.place_id,place).model_copy(deep=True)
                            if arguments.keyword not in chosen.source_keywords:
                                chosen.source_keywords.append(arguments.keyword)
                            state['places'][place.place_id]=chosen
                            allowed.append(chosen)
                        found=PlaceSearchResult(request=request,status='ok' if allowed else 'empty',places=allowed,fetched_at=found.fetched_at)
                        state['searches'].append(found)
                        result=AgentToolObservation(name=call.name,status='ok' if allowed else 'no_result',data=found.model_dump(mode='json'))
                    else:
                        request=RouteRequest(city=state['city'],origin=state['places'][arguments.origin_place_id],
                                             destination=state['places'][arguments.destination_place_id],mode=ROUTE_MODES[call.name])
                        from life_journey.tools.schemas import RouteResult
                        route=RouteResult.model_validate_json(tools.route(request).model_dump_json())
                        if route.request != request:
                            raise ValueError('request mismatch')
                        state['routes'].append(route)
                        result=AgentToolObservation(name=call.name,status=route.status,data=route.model_dump(mode='json'))
                except ToolError:
                    if call.name in ROUTE_MODES:
                        from datetime import datetime,timezone
                        from life_journey.tools.schemas import RouteResult
                        route=RouteResult(request=request,status='unknown',unknown_reason='request_failed',fetched_at=datetime.now(timezone.utc))
                        state['routes'].append(route)
                        result=AgentToolObservation(name=call.name,status='unknown',error_code='tool_request_failed',data=route.model_dump(mode='json'))
                    else:
                        result=error_observation(known_name,'tool_request_failed')
                except (ValueError,TypeError,AttributeError):
                    result=error_observation(known_name,'invalid_tool_response')
                except Exception as error:
                    trace=AgentActionTrace(tool_name=known_name,sanitized_arguments=sanitized_arguments(arguments),
                        call_count=harness.context.tool_call_count,status='error',error_code='unexpected_tool_error',
                        latency_ms=(perf_counter()-started)*1000,executed=True)
                    harness.tool_finished(trace,hook_started)
                    error.harness_recorded=True
                    raise

                # 失败也缓存；重试需要有效新参数，不在运行层隐藏HTTP重试。
                harness.cache[key]=result.model_copy(deep=True)
    safe_args=sanitized_arguments(arguments)
    if result.error_code in {'invalid_arguments','unknown_place_id','city_out_of_scope'}:
        safe_args={}
    trace=AgentActionTrace(tool_name=known_name,sanitized_arguments=safe_args,call_count=harness.context.tool_call_count,
        status=result.status,error_code=result.error_code,latency_ms=(perf_counter()-started)*1000,cached=result.cached,executed=executed)
    harness.tool_finished(trace,hook_started,result_count=len(result.data.get('places',[])) if call.name=='search_places' and result.data else int(result.status=='ok'))
    logging.getLogger(__name__).info('agent_tool %s',trace.model_dump_json())
    return result
