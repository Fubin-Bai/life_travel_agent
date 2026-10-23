# V1｜高德真实世界工具契约

Last updated: 2026-10-23

**Implemented / 基本完成并收尾。** V2尚未开始。本文描述现行实现，不保证推荐质量或现实旅行可执行性；证据汇总见 [CURRENT_STATUS](CURRENT_STATUS.md)。

## 模式与配置

默认 `LIFE_JOURNEY_PLANNING_MODE=v0` 保留模型知识规划；根目录 `.env` 设置 `amap` 启用V1，需 `AMAP_WEB_SERVICE_KEY`（高德Web服务类型）及 `DEEPSEEK_API_KEY`。变量示例见 [配置模板](../.env.example)，实际Key不提交、不放前端、不输出日志。

FastAPI create_app、CLI main、smoke main通过python-dotenv加载固定源码项目根目录.env，override=False且不插值，不根据工作目录搜索其他文件。**系统变量优先，包括旧占位值和空值**；修改文件后重启后端。旧终端值可在shell提示符下unset；若启动配置仍有export，重开终端可能重新带入。DeepSeek非ASCII/内部空白Key在请求前返回明确配置错误，不打印凭据。

```bash
PYTHONPATH=src .venv/bin/python -m uvicorn life_journey.api:app --host 127.0.0.1 --port 8000
```

前端另开终端进入frontend运行npm run dev。配置和常见旧环境变量排障见 [README](../README.md)。

## 固定数据流与预算

```text
Trip + 当前参与者/相关关系 + InterviewState
  → 复用deterministic readiness
  → 高德确认大陆单城市
  → 根据明确需求生成有限关键词 → 查询与去重候选
  → 营业周规则条件检查 + 有限步行/公交路线查询
  → 规范化PlanningObservation → 紧凑Prompt
  → 原Planning Client一次调用 → 结构/日期/候选/营业/路线/节奏检查
  → PlanningResponse → Web
```

没有LLM自主Tool选择、隐藏重试、框架、Memory、Replanning或新的数据库表。所有工具输出经Pydantic规范化，原始高德JSON不直接给Planning。完整Observation/行程不持久化。

| 常量（application/planning_observation.py） | 当前值 |
| --- | --- |
| MAX_GENERATED_KEYWORDS | 24个生成词 |
| MAX_SEARCHES / PER_KEYWORD_LIMIT | 10次搜索 / 每词2项 |
| MAX_CANDIDATES | 12个去重POI |
| MAX_ROUTE_PAIRS / MAX_ROUTES | 6个有向组合 / 最多12次路线请求 |
| WALKING_RADIUS_M / LONG_WALK_SECONDS | 粗距1500米 / 步行1800秒 |

最多1次城市+10次搜索+12次路线=23次高德HTTP；单请求5秒、顺序执行、无缓存或重试。该预算不包含后续一次LLM请求，不是整条Web请求的时延保证。

## V1.1候选检索

正向来源按required_activities、activity_preferences、参与者food_preferences/interests、明确shared_travel_preferences处理；不读取MBTI/性别/关系标签生成关键词。有限同义表覆盖咖啡、工艺品、清吧、现代建筑等，先轮流覆盖主词再补少量变体。明确本地美食需求可扩展本地类别；这些变体不是新增用户偏好。

excluded_activities仅用于过滤，不作正向检索；弱需求用少量中性种子，仍接受排除过滤。当前是有限文本/别名匹配，不是任意自然语言理解或自动翻译。

查询按轮取候选，按place_id去重并聚合source_keywords，防止首类别独占候选池。retrieval_queries记录词与明确来源，unqueried_keywords明确预算外需求；未查询不等于不重要。全空停止，不让模型补造真实地点。

## Pydantic输入输出

| 模型 | 核心契约 |
| --- | --- |
| CityRequest / MainlandCity | 单城市名或编码；确认大陆城市及行政范围 |
| Coordinates | 有限合法经纬度，longitude在前，system=GCJ-02 |
| Place | place_id、name、可空address/category、adcode、location、source_keywords、opening_hours |
| PlaceSearchRequest | city、keyword、limit（1–5；workflow为2） |
| PlaceSearchResult | request、ok/empty、places、source/source_url/fetched_at；数量/ID/城市校验 |
| RouteRequest | city、已查询origin/destination、mode=walking/transit/driving；同城不同ID |
| RouteResult | request、origin_place_id、destination_place_id、mode、ok/no_route/unknown、distance_m?、duration_s?、walking_distance_m?、transfer_count?、source/source_url/fetched_at、unknown_reason? |
| PlanningObservation | city、searches、places、routes、opening_checks、retrieval_queries、unqueried_keywords、source |

POI搜索使用v3/place/text的extensions=all取得真实adcode与营业字段。只投影必要字段，非核心parent/building/tag/postcode等即使为[]也不丢弃合法POI；合理空address/category允许None。核心ID/name/行政编码/GCJ-02位置继续严格校验，本地截取输出limit，错误只报告安全字段路径，不透传原文/Key。

## V1.2营业时间

OpeningHours：known/unknown、weekly、source_text、source_field、source、fetched_at、timezone=Asia/Shanghai、unknown_reason。WeekdayOpening使用weekday=0周一至6周日，status=open/closed；OpeningInterval为同日分钟范围。OpeningCheck保留place_id、weekday、time_period、open/closed/unknown、available_intervals、reason、needs_verification。

复用现有all搜索返回的biz_ext.opentime2；缺失/合理空值才看biz_ext.open_time，不额外HTTP。缺失、[]、空字符串、坏类型、复杂混合、节假日例外、临时调整、旺淡季、跨夜等保持unknown；不写复杂自然语言parser，不用抓取时间替代未来旅行日期。

本次日期映射为weekday，对morning 08:00–12:00、afternoon 12:00–18:00、evening 18:00–24:00作条件检查：

- open：明确周规则与时段有交集，访问需落在available_intervals内，不保证整时段或未来实际营业。
- closed：明确周规则关闭或与该时段无交集，不得返回对应活动。
- unknown：缺乏可解释确定证据，保留待核实，不伪装verified open。

后端覆盖模型opening_status/opening_note。Prompt优先同类可用替代；全候选全时段关闭时可返回通用自由活动并说明需求缺口，不自动Replan。保证性文案检查按分句处理否定/未来核实动作，避免将“需向商家确认营业时间”当作已确认；肯定保证仍拒绝。这只是启发式，仍可能误报或漏报。

## V1.3游客路线

v3/direction/walking、v3/direction/transit/integrated、v3/direction/driving分别对应明确模式，仅取首方案。公交city/cityd使用同一中文城市；成功必须有duration_s，walking/driving还需distance_m，公交总距离允许未知。walking_distance_m直接取可靠总字段；换乘次数只有在分段完整、无铁路/出租车、每乘车段仅一条线路时按段数减一。buslines备选线路不等于多次换乘，歧义保留None。

按需求优先顺序的前六个候选各取一个坐标近邻，坐标比较仅选查询对象，不是验证道路距离或重排用户偏好。粗距≤1500米先walking，其余先transit；主模式失败/无路线或步行>1800秒时补另一游客模式，每组合最多2次。不做N×N网络查询，不删除远但匹配的必需活动。驾车保留直接工具/smoke参考，不作为自动Planning默认交通，也不代替失败游客路线。

成功空方案=no_route；网络/超时/API错误/坏核心字段由workflow记录unknown（安全request_failed/invalid_response），数值均None。单条失败不拖垮Planning，其余查询继续，不回退编造数据；辅助字段异常只保持未知，不制造换乘次数或零距离。

Prompt要求优先walking/transit、严格区分方向与模式，不把驾车时间当步行，不把未查/反向/unknown/no_route写成已验证分钟。步行>30分钟、公交>60分钟或换乘≥2次提示较高成本；优先需求匹配相近的合理组合，但personal relevance和required activity优先于最短距离。此取舍由Planning解释，不是完整路径优化。

## Planning引用与返回

具体地点的place_id只能来自Observation.places；自由休息等通用活动可为null，不能借此编造具体地点。通常至少一项引用，全候选关闭例外需说明缺口。Trip ID和每日日期覆盖照旧校验。

route_from_previous和route_note由Python按同日紧邻活动的有向端点匹配并覆盖模型值；通用活动与跨天打断引用，没查的组合不补证据。窄规则检查明确模式/分钟数和保证性表述。TripContext.preferred_pace优先于个人/共同长期节奏，fast不得明确变成整程slow；检查仍是启发式。

API继续POST /api/trips/{trip_id}/planning，返回itinerary、notice、observation和可选debug metrics。前端保留原视觉，展示活动及营业核实说明；route_note/完整Observation在API返回，当前未新增交通面板。

## 错误边界

| 情况 | 处理 |
| --- | --- |
| 未就绪 / 状态冲突 | 409，未就绪不查询工具或模型 |
| 境外/港澳台/省份/多城市/无法确认城市，全部无候选 | 422，不退回模型编造 |
| Key缺失 / DeepSeek凭据格式错误 | 503，安全错误不含凭据 |
| 城市/搜索网络、API或坏核心数据 | 502，停止该次规划 |
| 单条路线请求失败 / 空方案 | unknown / no_route，保留证据缺口继续规划 |
| 模型请求、结构或事实引用/窄规则不通过 | 明确错误，不悄悄返回无效行程、无限重试或自动Replan |

HTTP仅固定高德HTTPS主机、不跟随跳转，压低HTTP库日志，安全错误不包含URL查询串/Provider原文。fetched_at是获取时间，不是数据更新时刻，也不是未来状态保证。

## 验证与真实smoke

普通pytest完全离线，清除真实凭据并阻止真实HTTPTransport，使用MockTransport/fake/临时数据库。最近完整852 passed，1项既有弃用提示；前端build和依赖/语法检查有通过记录，本次文档整理不重跑功能测试。

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m pip check
PYTHONPATH=src .venv/bin/python -m life_journey.tools.smoke --city 北京 --origin 故宫博物院 --destination 景山公园 --mode walking
PYTHONPATH=src .venv/bin/python -m life_journey.tools.smoke --city 北京 --origin 故宫博物院 --destination 景山公园 --mode transit
```

smoke默认walking，可选driving/transit；每条最多4次高德请求，不访问LLM/SQLite，消耗真实配额。成功路线退出0，错误/无结果/无路线退出1，不含隐藏重试。

已有真实证据：Owner驾车故宫→景山2563米/1076秒；Agent步行1445米/1156秒；浏览器真实生成北京4天行程，营业误判修复后再次成功。**独立真实transit成功验收尚未记录**；Web成功不证明所有交通模式、未来营业或行程质量。

仍未解决：未来班次/末班车/出入口、节假日或临时营业、复杂解析、全路线覆盖、重复成功率、跨场景召回与个性化对照。没有天气、价格/预订、酒店、航班/高铁、跨城交通、Memory或Replanning。既有Interview benchmark不覆盖工具/Planning质量，不因功能收尾宣称质量全面达标。

## 官方接口依据

- [高德地点搜索](https://developer.amap.com/api/webservice/guide/api/search/)
- [高德路径规划](https://developer.amap.com/api/webservice/guide/api/direction)

V1为固定workflow的已实现收尾版本；下一阶段须Owner另行授权。
