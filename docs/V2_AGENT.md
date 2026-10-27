# V2｜LangGraph Tool-Using Agent

当前运行控制补充：预算、运行计数/缓存、hooks与trace已收口到[Agent Harness](AGENT_HARNESS.md)。本页业务契约与模式边界保留；Graph State不再保存这些runtime控制数据。
当前补充：本页描述保留的V2兼容路径。Owner后续已授权并实现[V3](V3_CONSTRAINTS.md)/[V4](V4_MEMORY.md)原型；“未进入V3”等措辞仅指V2自身边界。agent加LIFE_JOURNEY_VALIDATION=1可走V3，memory模式加入RAG且始终校验修复。

Last updated: 2026-10-26

## 当前实现

本轮直接使用LangGraph StateGraph，当前安装验证版本1.2.17，依赖约束`langgraph>=1.0.6,<2`。不先实现手写Tool Loop，不使用LangChain高层Agent，不迁移已有domain/application/高德adapter/SQLite。V0/V1保留，未进入V3。

```text
START → agent ──tool calls──→ tools → agent
             └─ready/guard─→ finalize → END
```

agent调用Provider-independent AgentLLMClient.decide；DeepSeek现有Client复用Responses原生function_call，返回Pydantic AgentDecision。不调用工具时只输出`{"ready_to_plan":true}`；不索取或保存隐藏chain-of-thought。tools逐个校验并执行本轮最多3个请求，function_call/output按call_id配对，规范化结果进入下一轮消息。finalize仅调用原run_planning一次及其全部守卫，无自动Replanning。

## State与职责

TypedDict AgentState保存trip_id、context（包含TripContext、参与者和相关关系）、InterviewState、已确认city、必要messages、pending_calls、searches/places/opening_checks/routes、tool_call_count/tool_counts、history、used_tool_arguments、决策次数/实际指标、连续重复次数、ready/stop_reason、错误/警告分类及最终response。客户端通过节点闭包注入，数据库连接、Key、raw高德/DeepSeek回复和隐藏推理均不入State。

每次API请求独立建图/状态，无checkpoint、跨请求缓存、长期Memory或新SQLite表。context/state深复制，不改用户原对象。normalized消息历史有预算上限，仍可能包含本次明确偏好，只供决策模型；不记入日志。

## Tools

| 名称 | Pydantic参数 | 行为 |
| --- | --- | --- |
| search_places | city、keyword、limit=1..2 | 只查已确认大陆城市，复用V1地点/营业规范化 |
| get_walking_route | origin_place_id、destination_place_id | 候选池内不同ID、有向步行 |
| get_transit_route | 同上 | 同城公交/地铁 |
| get_driving_route | 同上 | 补充驾车，不作为默认游客交通 |

城市范围在进入图前由Python确认一次；模型不能切换城市、提供任意坐标或创造provider ID。搜索limit/空字符串/额外字段等严格拒绝，错误为`invalid_arguments`等固定分类，不回显原文。搜索排除项和返回候选做V1有限文本/别名过滤，不声称完整否定理解或新增V3语义Validator。

输出只来自V1 normalized模型，外层区分ok/no_result/no_route/unknown/error。营业随POI返回，不增加独立营业Tool。失败/空结果可让Agent改词/改参数；路线请求失败保留unknown交通证据，不能编造数值。相同失败参数也缓存，不把重复调用做成隐式重试。

## 集中预算与终止

默认AgentBudget定义于schemas/agent.py：

| 项目 | 上限 |
| --- | --- |
| Tool尝试（含非法/重复） | 12 |
| 真实搜索 | 6，每次最多2候选 |
| 真实路线 | 总6，每个模式3 |
| 候选池 | 12 |
| 模型decide | 8 |
| 连续重复 | 2次后强制停止 |
| LangGraph recursion_limit | 22 |
| 每次决策输出Token | min(客户端上限,1536) |

默认真实地图HTTP最多1城市确认+12工具=13次；被拒绝/重复不发HTTP。city请求与总Tool尝试单独计数。图可能在更少调用时结束；决策上限再加一次finalize，工具请求各沿用V1超时5秒，API客户端LLM请求120秒，不代表整条请求有120秒总时限。

相同tool+规范化Pydantic参数作为缓存键，JSON字段顺序/首尾空白/城市别名不产生新HTTP。缓存Observation加cached标识，仍占尝试预算防止无限重复。总尝试/决策上限或连续重复强制进入finalize；没有候选则NoPlacesError，不退回V0编造。recursion触发时安全失败，不在图外绕过限制追加调用。Provider协议失败明确停止，非法工具参数属于可纠正Observation。

批次超过预算的其余调用返回预算错误并配对输出，不执行HTTP；超大/无效原生决定明确报LLMResponseError。模型输出ready表示它建议证据充分，不证明必需需求已完整覆盖，最终仍受现有守卫限制。

## Finalize与兼容API

继续复用原TravelContext、PlanningObservation、PlanningPrompt、Itinerary及run_planning。具体POI必须在已查候选池；营业closed、unknown伪称confirmed open、错误有向端点/交通模式/分钟、日期覆盖和明确pace冲突继续拒绝。不改Interview，不增加新的Constraint Validator、不自动修复行程或Replan。

`POST /api/trips/{trip_id}/planning`不变，返回仍为itinerary、notice、observation、metrics：

- v0：原模型知识路径（默认）。
- amap：V1固定Python检索/路线抽样。
- agent：V2由LLM决定工具/参数/继续或停止。

现有前端无需改动；V1与V2是显式legacy/agent切换，失败不自动跨模式fallback。默认metrics=None，`?debug=true`时安全AgentRunMetrics序列化为既有metrics.agent_run JSON字符串，兼容原字段值类型。

## 可观察性与安全

AgentRunMetrics包含工具次数/实际执行次数、decision_count、实际决策model/token/latency、stop_reason、候选/路线/营业检查数量、脱敏actions和安全warnings。原metrics中model/tokens仍指最终Planning调用；决策调用单独列出，不估算缺失费用。

action日志仅记录允许工具名、搜索词长度/limit或已验证POI ID、状态、固定错误分类、时延、缓存/执行标志与次数，不记录任意搜索词、个人信息、Key、完整Prompt或Provider原文。固定虚构smoke可以显式打印其搜索词和生成行程；不读正式用户数据。finalize失败时异常附安全轨迹供smoke展示，API仍只返回原安全错误。

LangGraph传递依赖包括langchain-core/langsmith/checkpoint等；安装不代表启用对应产品功能。执行显式`tracing_context(enabled=False)`、callbacks=[]，即使开发机设LANGSMITH_TRACING也不自动上传图状态。所有普通pytest阻止真实httpx/httpx2传输，fake/MockTransport/TestClient不受影响。

## 手动真实smoke

根目录.env配置两家Key，系统环境仍优先。执行前确认无旧占位export，启动加载规则见[README](../README.md)。smoke无需修改当前Web的planning mode：

```bash
PYTHONPATH=src .venv/bin/python -m life_journey.evaluation.agent_smoke --city 北京 --case architecture_coffee --max-tool-calls 4
PYTHONPATH=src .venv/bin/python -m life_journey.evaluation.agent_smoke --city 北京 --case architecture_art --max-tool-calls 4
```

会消耗真实配额；输入为sample_data虚构人物/固定Trip，未访问SQLite。输出行动顺序/状态、实际次数、停止原因、真实计数/时延与最终行程；失败返回1并保留可用安全轨迹，无隐藏重试。不是质量scorer，不要求或打印隐藏推理。

2026-10-26实际结果：

- architecture_coffee（4 Tool预算）：真实链路已到finalize，最终模型把closed地点排入对应时段，被原守卫拒绝。本次失败保留，没有自动Replan或放宽营业校验；当时失败轨迹尚未附加，随后补齐并做离线回归。
- architecture_art（4 Tool预算）：两次search_places均ok，实际执行2次、4候选、0路线，模型两轮决定后stop_reason=sufficient_evidence，生成3天行程。端到端约21.5秒；这是一次工具/Provider/图/finalize成功，不是质量结论。该场景模型没有选路线，不能冒充已验证真实walking/transit Agent决策。

普通测试与构建的最终数量见CURRENT_STATUS。现有Interview Evaluation不覆盖V2工具策略；新增固定离线回归/真实smoke不能证明召回覆盖或个性化收益。

## 仍需验证

真实Agent路线选择、多关键词/语言变体、失败后的自主修正、预算耗尽与recursion的真实行为、V1/Agent同输入重复对照、真实Web agent模式、成本/时延和最终事实/偏好遵循率。当前“信息充分”主要是LLM判断加确定性最小候选/事实守卫，不是完整需求覆盖证明。

不包含V3 Constraint Validator/Replanning、RAG、长期Memory、向量库、多Agent、酒店/航班、天气、Browser Search、审批流、Streaming、Auth或部署。生成行程和图State不持久化，刷新后不能恢复本轮Agent运行。

## 官方依据

- [LangGraph Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)
- [DeepSeek Responses API](https://api-docs.deepseek.com/api/create-response/)

