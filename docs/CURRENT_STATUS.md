# 当前状态｜2026-10-27

V0/V1保留；V2 LangGraph单Agent、V3 Constraint Validator + Local Replanning、V4 Long-term Memory + RAG已实现本地面试原型，随后完成轻量Runtime Harness工程化收口。本轮Owner明确授权V3/V4，旧文档中的“不进入V3/Memory”是历史边界，已被本轮授权取代。未commit/push。

## 已实现与入口

- v0：原Interview与模型知识Planning。
- amap：大陆单城市高德POI、营业周规则、步行/公交/驾车Observation，固定Python检索。
- agent：V2原生Tool Calling/预算/缓存/安全停止；设LIFE_JOURNEY_VALIDATION=1启用V3，默认兼容V2。
- memory：先隔离检索TopK Memory，再V2工具决策、草稿、确定性校验及最多两轮局部修复。
- Feedback API与最小前端反馈表单；记忆写SQLite向量表，旧原始聊天/行程/Observation仍不持久化。
- 未解决草稿明确返回unresolved_constraints，Web显示警示；不是静默接受不合规结果。

## 验证证据

2026-10-27推送准备复核：全量离线pytest **991 passed**，前端TypeScript/Vite构建、pip check、git diff --check和本地Markdown链接检查通过；.env未跟踪，.env与本地SQLite均被忽略。未自动commit/push。

V3完成后先跑915项全量离线测试通过，再开始V4。V4基线949项离线通过；Harness新增42项回归，当前全量991项通过。前端TypeScript/Vite build、pip check、compileall、git diff --check通过；仓库没有配置独立lint命令，未引入新lint依赖。

V3固定12个合成场景全部识别对应冲突；预设补丁的硬冲突场景比例66.7%→8.3%，修复成功87.5%、硬问题解决94.4%，有unsupported事实的场景25%→0%。V4固定4例fake向量/脚本Planner对照匹配25%→100%、相关性100%、无关个性化0%；固定草稿Validator硬冲突0%。这些证明规则和信息流，不能声称真实LLM质量提升。

真实历史证据：V1驾车/步行与Web成功；V2真实两次搜索、4候选、0路线生成三天行程；亦保留closed初稿失败记录。2026-10-27 Owner完成本地网页启动与操作测试，真实硅基流动 BAAI/bge-m3 返回2条1024维向量；Web Feedback返回非空 stored_memory_ids，长期偏好已保存。Owner确认完成RAG检索测试；本次协作未保存对应 planning 的 memory_provenance 响应作为可复查报告。长期记忆与RAG检索已实现，真实召回质量/修复成功率仍无系统基线。独立真实transit验收仍缺。

## Harness工程化收口

agent/memory运行由AgentHarness包裹现有LangGraph，集中RunContext、冻结Policy、十二个hooks、脱敏事件、统一错误/恢复与有界终止；Graph State移出计数/缓存/运行错误。默认API不变，debug可查看成功/失败summary与trace，无新前端/Tool/依赖。

11个固定behavioral场景全部符合预期，10次completed、1次预期unresolved；离线smoke已实际展示Memory、cache、校验和修复。真实服务质量不由此证明。同步时限只在边界检查，不能强制取消阻塞调用；无run持久化、监控SaaS或生产鉴权，不进入V5。详见[AGENT_HARNESS](AGENT_HARNESS.md)。

## 配置与已知限制

启动方式不变，根目录.env系统变量优先。memory需另外配置独立Embedding URL/MODEL/KEY，不能假设DeepSeek Key可直接用于Embedding。具体见[V4_MEMORY](V4_MEMORY.md)。

仅大陆单城市、有限候选/路线；营业是未来周规则条件参考，不保证未来开门；事实与required/否定校验仍是窄启发式。修复只用已有证据，不额外取证；局部以天为单位，不保证最优解。Memory只自动处理明确长期反馈，Trip/Interview不全量自动学习；复杂语义矛盾、行为聚合、遗忘管理和真正个性化收益尚待验证。

SQLite向量精确余弦、最多200条scope候选，适合本机小规模；无生产鉴权、多用户安全边界、图checkpoint、聊天/行程恢复、预订或部署。不进入V5训练/优化或其他扩展。

[完整架构](ARCHITECTURE.md) · [V2](V2_AGENT.md) · [V3](V3_CONSTRAINTS.md) · [V4](V4_MEMORY.md) · [决策](DECISIONS.md) · [路线图](ROADMAP.md)

## 本次展示验收与待核查

当前本地默认选择memory；DeepSeek官方负责对话/规划，硅基流动BAAI/bge-m3负责向量化，高德负责地点/路线，本地SQLite保存长期记忆。配置与切换见[本地展示指南](LOCAL_DEMO.md)。本地.env不提交，其他人需自行填写Key。

本次Web行程中出现“10月12日全天关闭但仍待核实安排”以及将2026-10-14写成周二的文字冲突；尚未取得该次Observation和Validation响应定位根因。保留为事实表达/校验待核查项，不能以单次生成成功证明所有代码无缺陷。
