# V3｜约束校验与局部修复

当前运行控制补充：预算、运行计数/缓存、hooks与trace已收口到[Agent Harness](AGENT_HARNESS.md)。本页业务契约与模式边界保留；Graph State不再保存这些runtime控制数据。
状态：Implemented prototype，2026-10-26。Owner本轮明确授权，取代旧V2阶段“不进入V3”的限制；不改变v0/amap默认行为。

## 入口和图

`agent`保留V2兼容默认；设置`LIFE_JOURNEY_VALIDATION=1`启用V3。`memory`始终启用V3，无需该开关。Python调用`run_agent_planning(..., validated=True)`同样可用。

```text
START → agent ⇄ tools → finalize_draft → validate
                                           ├─ 无硬冲突 → complete → END
                                           ├─ 有硬冲突且轮次<2 → replan → validate
                                           └─ 达到2轮 → complete(unresolved) → END
```

LangGraph负责条件边，Validator和补丁应用是普通Python；没有第二个Agent、隐藏工具调用或图外重试。保留原工具预算：12次Tool尝试、search6、route6且每模式3、候选12、决策8。V3最多再调用一次草稿LLM、两次修复LLM；修复不额外查工具。默认recursion22在新路径预留9个节点步数，不能无限循环。

## Schema

- `DraftItinerary(trip_id, summary, days)`：日期仍是合法date、活动仍用原Schema；暂允许重复/乱序日期供诊断。旧`Itinerary`严格递增日期规则未放宽。
- `ConstraintIssue`：issue_id、severity(hard/soft)、type、message、day(零起始索引)、date、activity_reference(`dN:aN`)、evidence_reference、repair_hint。
- `ValidationResult`：valid、violations、warnings、hard_violation_count、soft_warning_count、affected_days、affected_activity_ids、constraint_types、summary；计数由Python推导。
- `ReplanPatch`：days(day_index/replacement)、可选trip_id/summary；replacement=null删除错误日期，day_index=null只可补缺失日期。不是完整行程重写协议。
- PlanningResponse新路径增加validation_result、unresolved_constraints、final_status(valid/unresolved)、replan_round；旧模式不输出这些默认字段。

活动引用是当前版本草稿的位置引用，替换后重新校验生成，不作为跨轮持久ID。

## 硬规则

明确必需活动缺失、排除活动泄漏、候选池外ID、具体已知地点缺ID、按周规则closed的安排、unsupported营业保证或确认性事实、路线模式/端点/分钟数不符、no_route/unknown冒充已验证、日期覆盖/重复/越界/乱序、trip_id不同、同日morning→afternoon→evening顺序不合法。继承fast下明确慢节奏文案冲突检查。

必需活动匹配使用字面文本与有限同义类别；来源关键词本身不作为活动真实满足的事实证据。失配提示“未找到/无法安排”不统计为已满足。营业仍是未来日期的条件周规则，不把unknown视为开放。

这些是保守启发式，不能识别任意隐晦POI实体、否定、语义相似活动或所有确认性事实。没有LLM Semantic Validator；不能把`valid`解释为全面可执行性保证。

## 软规则

单地点超过两次、同类至少三次、fast一天少于3项/slow一天超过4项、坐标显示近→远→近明显折返、相邻已查询交通超过一小时且存在同需求候选、过短/模板理由、多类required集中一天、同一餐饮地点重复。阈值可解释且保守；软提醒不触发强制修复，不为距离短覆盖个人偏好。

## 局部修复与失败

Replanner收到TravelContext、本次需求、草稿、结构化问题、全部规范化POI/营业/路线证据；memory模式还收到TopK记忆。优先同类候选替换closed、合理调整相邻活动、补required、删除excluded。程序只接受受硬冲突影响的日期；required全局缺口每轮最多改一个原本无冲突日期；日期覆盖问题才允许补日/删除重复或越界日期。未受影响日禁止修改。

修复调用失败/补丁越界计入一轮，保留原稿并在安全trace记录repair_failed；仍要重验。达到`MAX_REPLAN_ROUNDS=2`后返回明确unresolved，不自动降级V0。无真实候选仍直接失败，不启动无证据规划。

通过后才由后端覆盖opening_status/note与有向route引用；未通过草稿清除可信营业/交通标签。Web显示“未完成校验的草稿”及未解决问题，不能当作已通过行程。草稿/Observation不写正式库。

## Evaluation与运行

`evaluations/v3_constraints.json`包含12个合成固定场景：闭店、required缺失、excluded、伪造地点、模式串用、no_route、fast太松、slow太密、餐厅重复、折返、成功局部修复、两轮未解决。

```bash
.venv/bin/pytest -q
PYTHONPATH=src .venv/bin/python -m life_journey.evaluation.constraints
PYTHONPATH=src .venv/bin/python -m life_journey.evaluation.version_smoke --stage v3 --case closed --city 北京
PYTHONPATH=src .venv/bin/python -m life_journey.evaluation.version_smoke --stage v3 --case required --city 北京
PYTHONPATH=src .venv/bin/python -m life_journey.evaluation.version_smoke --stage v3 --case route --city 北京
```

离线评估使用预设补丁验证机制，不评估真实LLM修复能力。当前12例全部识别对应类型；硬冲突场景比例66.7%→8.3%，有硬冲突例的脚本修复成功率87.5%，硬问题解决率94.4%，有unsupported事实的场景比例25%→0%。软提醒不强修，最后一例故意保留未解决。

真实smoke使用刚取得的真实高德Observation、真实DeepSeek修复与真实LangGraph，但控制初稿以触发冲突；取证Agent决策由ready桩跳过，因此是V3组件联调而非完整V2取证质量评估。closed证据缺失时明确skipped，不注入假闭店。尚未运行联网验收。

核心文件：`schemas/validation.py`、`application/constraint_validator.py`、`application/replanning.py`、`llm/replanning.py`、`application/agent_planning.py`。
