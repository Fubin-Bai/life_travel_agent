"""手动高德真实冒烟入口；不调用 LLM，不接触 SQLite，不放进 pytest。"""
from life_journey import environment

import argparse
import json
from . import AmapPlaceTools, CityRequest, PlaceSearchRequest, RouteRequest, ToolError


def main(argv: list[str] | None = None) -> int:
    """查询一个城市、两组关键词及首个不同POI之间的驾车参考。"""
    environment.load_project_env()
    parser=argparse.ArgumentParser(description='高德真实工具 smoke（会消耗 API 配额）')
    parser.add_argument('--city',default='北京',help='中国大陆中文单城市名')
    parser.add_argument('--origin',default='故宫博物院',help='起点搜索关键词')
    parser.add_argument('--destination',default='景山公园',help='终点搜索关键词')
    parser.add_argument('--mode', choices=['driving','walking','transit'], default='walking')
    args=parser.parse_args(argv)
    tools=None
    try:
        tools=AmapPlaceTools()
        city=tools.resolve_city(CityRequest(destination=args.city))
        origin=tools.search_places(PlaceSearchRequest(city=city,keyword=args.origin,limit=1))
        destination=tools.search_places(PlaceSearchRequest(city=city,keyword=args.destination,limit=1))
        if not origin.places or not destination.places:
            print('EMPTY：至少一组关键词没有结果，未查询路线；请更换关键词。')
            return 1
        if origin.places[0].place_id == destination.places[0].place_id:
            print('EMPTY：两个关键词命中同一地点，请更换其中一个。')
            return 1
        route=tools.route(RouteRequest(city=city,origin=origin.places[0],destination=destination.places[0],mode=args.mode))
        print(json.dumps({'city':city.model_dump(mode='json'), 'searches':[origin.model_dump(mode='json'),destination.model_dump(mode='json')],
                          'route':route.model_dump(mode='json')},ensure_ascii=False,indent=2))
        print('工具结构 smoke 已完成；不证明未来营业、未来班次或未来实际交通。')
        return 0 if route.status=='ok' else 1
    except ToolError as exc:
        print(f'FAILED：{exc}')
        return 1
    finally:
        if tools is not None:tools.close()


if __name__=='__main__':
    raise SystemExit(main())
