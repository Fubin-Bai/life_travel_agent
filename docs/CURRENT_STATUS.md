# 人生旅迹｜当前状态

Last updated: 2026-10-23

## 阶段结论

**Owner 已确认 V1 基本完成，当前进入收尾；V0 已收尾，V2 尚未开始。**

当前可在本机完成 Profile → People → Trip Setup → Travel Interview → 用户点击 Planning → 高德真实数据辅助的结构化行程展示。功能闭环完成不等于推荐质量、稳定成功率或现实可执行性已经通过完整验收；剩余验证缺口保留，不自动进入下一阶段。

## 已实现

- Person / Relationship / Trip / TripContext、Create Schema 与 application 创建逻辑；输入与内部模型分离，系统生成前缀 UUID4 ID。
- Web 固定本机主体资料，同行人物和共同关系偏好分别保存；性别、MBTI、关系标签不直接推断兴趣或体力。
- Context Builder 只选择实际参与者与双方均参与的关系，不增加人物，不合并个人与共同偏好。
- 单轮自然访谈、结构化更新和 deterministic readiness；省略保留、标量显式清空、列表完整替换，一轮一条 assistant_message。
- FastAPI / SQLite 持久化资料、关系、TripContext 和 InterviewState；系统就绪后由用户手动触发 Planning。
- V1.1：高德大陆单城市 POI、有限需求关键词、多类别候选池、按 POI ID 去重及来源关键词。最多生成24词、查询10词、每词2项、候选12项；排除项只过滤。
- V1.2：复用搜索营业字段，规范化简单周规则；按旅行日期/时段判断 open / closed / unknown。closed 安排拒绝，unknown 不标成已确认营业，后端生成窗口/核实说明。
- V1.3：步行、同城公交/地铁规范化 Observation，保留驾车工具。最多6个有向近邻组合、12次路线调用；近处先步行、较远先公交。单路线失败记录 unknown，不中断整次 Planning。
- Python 按同日紧邻活动端点匹配 route_from_previous，生成 route_note；不信任模型手写引用。分模式交通、候选引用、日期覆盖及明确节奏冲突做窄范围检查，不是通用 Constraint Validator。
- FastAPI、CLI、smoke 自动加载固定项目根目录 .env，系统环境优先；Key 不进前端或日志。DeepSeek Key 非 ASCII / 内部空白在请求前报配置错误。

## 当前数据流

```text
React → FastAPI → SQLite读取当前Trip/参与者/相关关系/InterviewState
  → deterministic readiness
  → 确认大陆单城市 → 有限POI检索 → 营业周规则与有限步行/公交路线
  → 规范化PlanningObservation → Planning Prompt → 一次DeepSeek调用
  → Schema/日期/候选/营业/路线/节奏检查 → Web展示
```

仍是固定 Python workflow，不让 LLM 自主选择 Tool；无 LangChain、LangGraph、Multi-Agent 或自动 Replanning。

## 配置与持久化

默认保留 `LIFE_JOURNEY_PLANNING_MODE=v0`；根目录 .env 设置 `amap` 才启用 V1，配置 `AMAP_WEB_SERVICE_KEY` 和 `DEEPSEEK_API_KEY`。系统同名变量优先于文件；旧占位值需在启动终端 unset，若写在 shell 启动配置中还需移除。修改配置后重启后端。启动和排障见 [README](../README.md)。

SQLite 默认 `.local/life_journey.sqlite3`，包含 persons、relationships、trips、trip_participants、interview_states、local_profile。不 seed fixtures，不把正式用户数据用于自动化测试。主体指针不是登录/权限系统。

**聊天历史、生成行程、Observation 和未保存草稿不持久化，刷新不会恢复行程。** 人物与关系分开保存；普通 PUT 为完整替换，访谈/规划使用快照冲突检查，尚无完整幂等恢复或并发协议。

## 验证证据

| 验证 | 已获得的证据 |
| --- | --- |
| 最近完整 pytest | 852 passed；1项既有 Starlette/httpx 弃用提示；全部离线 |
| 构建与检查 | 最近前端 TypeScript/Vite build、pip check、compileall、diff 检查通过；本次仅整理文档，未重跑功能测试 |
| 真实高德驾车 | Owner 提供故宫→景山 smoke 成功：2563米、1076秒 |
| 真实高德步行 | Agent 实际 smoke 成功：故宫→景山1445米、1156秒 |
| 真实 Web | 浏览器选择原北京4天旅行、点击开始规划，接口200且实际显示4天行程；营业误判修复后再次验证成功 |
| 真实公交/地铁 | 已有离线成功/多分段/异常回归；没有独立确认的真实 transit 成功验收记录 |
| 访谈 Evaluation | 最近固定 gender_context 报告7/8，原六例5/6；历史报告保留，不以单次最好结果代表稳定性 |

排障已修复路线引用由模型手写导致不匹配、错误终端凭据被误报输出校验、营业检查误拒绝否定/未来核实动作。保留安全拒绝规则；一次 Web 成功不证明模型每次都会通过。

## 已知限制与待验证事项

- 仅中国大陆单城市；候选池和路线覆盖有限，不是完整行程路线优化。未查询组合、unknown/no_route 不代表已验证可达。
- 营业 open 只是抓取周规则与时段的条件交集，不保证未来实际开门；节假日、临时调整、旺淡季、跨夜、复杂文本仍可能 unknown。
- 公交参考不保证未来班次、末班车、拥堵或具体出入口；真实 transit / 多城市泛化、时延和重复成功率仍待验证。
- 自然语言营业/交通/节奏检查为启发式，可能误报或漏报；无完整语义事实校验、价格/预算可行性、实时天气或预订验证。
- 尚无工具召回/行程质量 scorer、普通攻略对照和多次个性化收益证明。访谈 benchmark 不替代 Planning Evaluation；活动语言归一化与部分抽取边界仍有缺口。
- special_requirements 只有确认状态，具体要求文本未存储。
- 无登录、多用户隔离、删除流程、聊天/行程持久化、通用 Trip 更新、行程 refinement、Memory、部署；无 V2 工具自主选择、Replanning 或通用 Constraint Validator。

## 后续入口

当前保留 V1 收尾状态。后续可先补真实 transit 与固定大陆场景的重复质量/失败率验证；具体下一阶段设计和开发由 Owner 另行授权，不自动实施 V2。

[架构](ARCHITECTURE.md) · [V1工具契约](V1_TOOLS.md) · [决策](DECISIONS.md) · [路线图](ROADMAP.md) · [Evaluation](../evaluations/README.md)
