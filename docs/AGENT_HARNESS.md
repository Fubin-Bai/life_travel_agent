# Agent Harness｜轻量运行控制层

Implemented local prototype，2026-10-26。V4工程化收口，不进入V5，无新增产品功能、业务Tool、外部依赖或监控服务，未commit/push。

**LangGraph = orchestration layer；Harness = runtime control layer。**

准确定位：在LangGraph之上增加轻量runtime harness，用于统一策略、预算、hooks、trace、错误处理与behavioral evaluation；不是另一个Agent框架，也不替代Domain、AMap适配器、RAG或Validator。

## 架构与职责

```text
POST /api/trips/{trip_id}/planning
→ AgentHarness.run（每次请求独立实例）
  ├─ AgentRunContext / HarnessPolicy
  ├─ hooks / timing / sanitized trace
  ├─ budget / fingerprint cache / termination
  └─ structured errors / explicit recovery
→ 现有LangGraph
  retrieve_memory → agent ⇄ tools → finalize_draft → validate ⇄ replan → complete
→ 既有Domain / Tools / SQLite / Embedding / LLM
```

v0/amap仍走原工作流；agent/memory使用Harness。API参数解析、readiness、依赖配置创建和最后快照409检查仍是外围API职责，不伪造为已经启动的Agent run。没有新的持久化run表或全局运行缓存。

Graph State保存TravelContext、messages、候选/路线/营业Observation、retrieved memories、草稿、ValidationResult和最终业务结果。预算、计数、缓存、重复次数、错误、stop reason和运行trace从Graph State移出；节点通过闭包共享本次Harness，不各建一份policy。

## 核心文件

| 文件 | 职责 |
| --- | --- |
| `harness/policy.py` | 不可变集中策略与少量环境覆盖 |
| `harness/schemas.py` | AgentRunContext、HarnessError、TraceEvent、AgentRunSummary |
| `harness/hooks.py` | 十二个默认no-op观察hook |
| `harness/runtime.py` | 生命周期、预算、缓存、错误、hooks与事件收口 |
| `application/agent_planning.py` | 将同一Harness注入既有图节点和graph.invoke |
| `application/agent_tools.py` | 保留领域参数/范围/结果校验，向Harness申请运行预算 |
| `evaluation/harness_behavior.py` | 固定行为评估及本地聚合指标 |
| `evaluation/harness_smoke.py` | 默认离线的运行轨迹展示 |

## AgentRunContext与Summary

Context包含run_id、trip_id、planning_mode、started_at/finished_at、current_stage/current_graph_node、tool_call_count、model_call_count、decision_count、executed_tool_calls、tool_counts、cache_hits、replan_round、memory_retrieval_count、validation_passes/failures、warnings、结构化errors、stop_reason、status、timing_ms、policy_snapshot、memory_degraded。

生命周期为created → running → completed / unresolved / stopped / failed。预算正常结束且产生可用结果可为completed；硬冲突保留为unresolved；时限/递归耗尽且无结果为stopped；致命错误或critical hook为failed。

Context不保存API Key、原始Provider响应、完整Prompt、隐藏推理、SQLite连接或数据库对象。规范化工具结果cache只属于本次Harness私有运行数据，不序列化到Context/trace，不跨请求复用。

结束产生AgentRunSummary：run_id、final_status、total_duration_ms、model_calls、tool_calls、executed_tool_calls、cache_hits、memory_retrievals、validation_passes/failures、replan_rounds、warning_count、error_count、stop_reason。

计数定义：

- tool_calls为Agent准入尝试，包括非法参数/缓存/被per-tool预算拒绝的尝试；总预算上限后不再增加。真实search/route执行数另记，城市范围确认仍额外最多一次，不混入Agent工具预算。
- model_calls为决策、Planning草稿/兼容finalize、修复的调用尝试，Provider失败仍计数；无候选导致前置停止不虚记最终模型调用。Embedding调用属于Memory检索，不算生成模型调用。
- memory_retrievals为检索节点尝试次数，不等于Embedding HTTP次数；无匹配scope也可能完成一次检索。
- validation_passes为完成的校验轮数，包含invalid轮；validation_failures为其中仍有hard violation的轮数。校验器本身不能执行是结构化fatal error，不能标为valid。
- warning_count按发生次数统计runtime提醒与校验软规则代码；重复验证可能再次计入同一提醒。硬约束未解决是业务结果，不等于运行内部bug。
- error_count包括recoverable诊断但不把budget_exhausted计作内部错误；run是否失败以status判断。

## HarnessPolicy

唯一默认来源位于`harness/policy.py`，冻结后不可变。旧`AgentBudget`是兼容别名；V3的MAX_REPLAN_ROUNDS和V4的MEMORY_TOP_K引用同一默认policy，不再另写默认值。

| 策略 | 默认 |
| --- | --- |
| Agent决策轮数max_decisions / max_agent_rounds | 8 |
| 总工具准入尝试 | 12 |
| 实际search / route执行 | 6 / 6 |
| 每个route mode | 3 |
| 候选池 / 单搜索limit | 12 / 2 |
| 连续重复阈值 | 2 |
| 最大修复轮数 | 2，可注入0–2 |
| Memory TopK | 5，可注入1–10 |
| LangGraph基础recursion_limit | 22 |
| 整次协作式时限 | 默认不启用 |
| Memory失败策略 | fail |

V3/Memory有效递归上限为基础值 + `2*max_replan_rounds+5`，默认31，显式预留草稿/校验/完成节点；这不增加Agent决策或Tool预算。

仅开放两个可选非秘密env：LIFE_JOURNEY_MAX_TOOL_CALLS、LIFE_JOURNEY_MAX_RUN_SECONDS；其他测试/开发策略用Python HarnessPolicy注入，避免环境配置膨胀。Schema硬上限、单城市/已查候选ID等领域守卫仍保留。

## Hooks

支持before_run/after_run、before_model/after_model、before_tool/after_tool、before_memory_retrieval/after_memory_retrieval、before_validate/after_validate、before_replan/after_replan。

默认均no-op；多个hook按注册顺序执行。参数只给AgentRunContext和可选TraceEvent的深拷贝，不给业务结果、Prompt、SDK或数据库。修改快照不会修改主结果。普通hook执行或属性读取失败仅记录安全warning/error，不中断运行，不回显异常原文。

只有显式`critical=True`才允许终止。critical hook失败不会被replan的普通恢复吞掉。Hook是可信Python扩展点，不是第三方代码沙箱；实现同步、无独立超时或线程隔离。

## 统一Trace

TraceEvent包含event_id、run_id、UTC timestamp、event_type、graph_node、可选tool_name、sanitized_args、status/error_code、duration_ms、result_count、cache_hit、stop_reason、validation_issue_count、validation_issues、replan_round、memory_ids、retrieval_scores。

覆盖RUN_STARTED/COMPLETED/FAILED、NODE_ENTERED/EXITED、MODEL_CALLED、TOOL_REQUESTED/COMPLETED/FAILED/CACHE_HIT、MEMORY_RETRIEVED、VALIDATION_COMPLETED、REPLAN_STARTED/COMPLETED、BUDGET_REACHED、DUPLICATE_CALL_BLOCKED、FINALIZED。

搜索只记录keyword_length/limit；路线只记录已经通过候选范围验证的端点ID。无效参数不回显原文。校验trace只记录issue_id/type/severity，不记用户约束正文；Memory只记ID与分数，不记记忆全文。没有完整Prompt、原始AMap/LLM JSON、Key或chain-of-thought。旧agent_run/validation_trace是同一runtime数据的兼容投影，而非第二套控制状态；LangSmith仍显式关闭。

## Fingerprint与预算

先执行Pydantic参数、城市/候选范围、excluded等领域校验；城市别名、关键词空白/大小写规范化后，用工具名和validated args的排序JSON生成SHA-256 key。

首次执行并缓存规范化Observation，失败结果也缓存；相同调用优先返回副本，不再发HTTP。连续重复达到阈值后阻止继续决定，记录DUPLICATE_CALL_BLOCKED；同一批次后续调用也阻止。兼容旧行为：达到阈值的当前缓存结果仍可返回，阻止的是后续执行/模型决定，不无故丢失原生call/output配对。

工具总尝试、search/route/per-mode执行、候选池、Agent轮数、修复轮数、TopK和recursion均使用同一Policy。预算耗尽是正常终止信号；若没有任何真实候选仍明确失败，不回退模型编造。

## Error / Recovery

HarnessError为code/category/message/recoverable/stage/metadata，分类包括provider_model、tool、invalid_tool_arguments、policy_violation、budget_exhausted、memory_retrieval、validation、replanning、unexpected_internal、hook。message取固定安全分类，不保存Provider异常正文。

| 情况 | 行为 |
| --- | --- |
| 已知Tool失败/非法参数 | 结构化Observation，可在预算内改参数继续 |
| 相同失败参数 | 命中cache，不隐藏HTTP重试 |
| 未知内部Tool错误 | fatal，不把bug伪装成空结果 |
| Provider/model失败 | fatal，无整次run自动重试 |
| Memory/Embedding失败 | 默认fail；显式continue_without_memory才降级，notice与trace明确未使用历史记忆 |
| Validator不能执行/坏规范化结果 | fatal，不产生已验证最终结果 |
| 普通修复请求/补丁失败 | 保留原稿，消耗一轮再验证；最多policy轮数 |
| critical hook/时限 | 不可被局部修复恢复吞掉 |
| 无法解决硬约束 | 返回unresolved，非假成功 |

时限是协作式边界检查，不能抢占已阻塞的同步HTTP/SDK调用；既有Provider自己的timeout仍有效。没有async worker、队列、distributed tracing或外部SaaS。

## API兼容

仍使用`POST /api/trips/{trip_id}/planning`。无效Harness环境策略在运行前返回503配置错误，不误报为Planning输出失败。默认成功响应与现有前端保持兼容，metrics=None；默认失败仍是既有状态码与detail。

`?debug=true`成功时，在原metrics中增加JSON字符串harness_summary/harness_trace/harness_context；保留agent_run与validation_trace。失败时可附harness_summary/harness_trace/harness_errors，仅限已经启动的运行。无新增公开run查询端点或run持久化；本地debug不是生产权限系统。

API可注入harness_policy与harness_hooks，run_agent_planning亦支持policy/hooks或本次Harness；CLI/smoke同用入口。未改前端，未修改真实.env、正式用户数据或新增业务Tool。

## Behavioral Evaluation与Smoke

```bash
.venv/bin/pytest -q
PYTHONPATH=src .venv/bin/python -m life_journey.evaluation.harness_behavior --output evaluations/harness_behavior_report.json
PYTHONPATH=src .venv/bin/python -m life_journey.evaluation.harness_smoke
```

固定11例运行真实LangGraph、fake LLM/Tools/Embedding和临时SQLite，检查Tool预算、重复/cache、Memory scope、hard→replan、soft不强修、最大轮数unresolved、closed替换、unknown不冒充verified、当前Trip覆盖旧Memory、候选外地点拒绝、含Memory与修复的组合路径。

聚合指标：run_success_rate、avg_tool_calls、avg_model_calls、avg_replan_rounds、cache_hit_rate、validation_failure_rate、unresolved_constraint_rate、memory_retrieval_count、avg_latency_ms，并单独记录behavior_pass_rate。

当前全量pytest 991项通过（V4基线949项 + Harness新增42项），前端build、pip check、compileall与diff检查通过；没有配置独立lint任务。当前11/11行为符合预期；10/11运行完成，另1例故意unresolved且符合预期。因此100%行为合规不等于100%成功行程。报告是本地fixture控制验证，不是新模型评分、推荐质量提升或真实服务时延基准。

默认smoke为memory_repair：3次Tool尝试、1次真实桩执行、2次cache hit、1次Memory retrieval、1轮修复，展示Run ID、模式、节点迁移、校验问题、stop reason、总时延与最终状态。全程离线，不输出隐藏推理；Harness阶段没有新增真实服务联网验收；2026-10-27后续Web与Embedding手动验证见CURRENT_STATUS，不代表每种Harness分支都通过联网验收。

## Prototype边界

同步、本机、单次内存运行；无checkpoint、持久化run查询、强制取消、并行安全hook框架、生产鉴权或跨进程缓存。run summary不等同HTTP最终快照提交成功；API外围409仍可能丢弃已计算结果。旧V2 finalize把模型输出和既有守卫组合在一起，错误归因粒度不如V3独立Validator。领域语义规则、真实Memory质量与真实Provider稳定性仍继承V4限制。
