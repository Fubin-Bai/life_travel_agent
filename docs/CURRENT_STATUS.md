# 人生旅迹｜当前状态

Last updated: 2026-10-23

## 阶段结论

**V0 本地功能已基本完成，按 Owner 决定进入收尾。** 可以实际完成 Profile → People → Trip Setup → Travel Interview → 手动 Planning → 结构化 Itinerary。

这表示功能闭环可运行，不表示已完成普通攻略与个性化行程的正式对比验收，也不证明现实可执行性。V1 尚未开始，不自动开发下一阶段。

## 已实现

- Pydantic strict Schema 与 Create 输入，未知字段拒绝；应用生成前缀 UUID4 ID。
- Person 包含可选性别、MBTI；Relationship 使用中性枚举，个人/共同偏好独立。
- Trip 保存确定性 Setup、Decimal 预算和独立 TripContext；固定虚构数据支持 A/B/C 场景。
- Context Builder 按 participant_ids 选择人物与相关关系，不增加参与者、不推断偏好。
- 六主题 InterviewState，四主题最低 readiness；访谈更新省略保留、标量覆盖/清空、列表完整替换。
- Interview Prompt、单轮 LLM Client 与 run_interview_turn；每轮同时返回机器状态和一条 assistant_message。整句多主题理解，避免逐字段问卷。
- 最小 Planning Prompt/Client/Itinerary，校验 trip_id 与完整日期覆盖，返回固定非实时事实说明与推荐理由。
- FastAPI + SQLite，真实 Web 访谈写回 TripContext 与独立 InterviewState；规划需系统就绪后点击。
- Web 固定本机主体资料、同行人/关系编辑、旅行创建/回读、访谈及行程展示；暗调本地照片、中文关系标签、输入 autocomplete=off。
- 本机主体绑定存入 local_profile，保存不新增人物；旧库需明确首次绑定，不按姓名猜测或合并。
- Terminal CLI 仅作虚构输入访谈开发入口，状态在内存，就绪后结束。

## 数据与调用

SQLite 保存 persons、relationships、trips、trip_participants、interview_states、local_profile。默认 `.local/life_journey.sqlite3`，不 seed fixtures；测试使用独立临时数据库/端口。正式库不应混入开发人物。

人物、关系、Trip、TripContext、InterviewState 可跨刷新恢复；未保存草稿、聊天记录和生成行程不持久化。主体指针不是登录/权限模型。人物和关系分两次保存，关系失败不回滚已创建人物。

当前 Provider 为 DeepSeek Responses，通过既有 OpenAI-compatible SDK；默认模型 deepseek-flash，可由环境覆盖。应用不自动加载 .env。访谈默认 2048 output tokens/60 秒，Web 规划 8192/120 秒；均非流式、关闭 SDK 自动重试。可获得 model、tokens、latency 等指标；API 默认隐藏 metrics，debug=true 可返回，不持久化调用日志或估算费用。

## 验证证据

| 验证 | 实际结果与范围 |
| --- | --- |
| 最新完整 pytest | 692 passed；1 项既有 Starlette/httpx 弃用提示；普通测试完全离线 |
| 前端 | TypeScript/Vite build 通过；已有独立测试库浏览器验证保存、刷新、访谈和规划展示 |
| 依赖 | 最近功能验证 pip check 无冲突；没有新增格式/静态工具链 |
| 真实访谈最新回归 | interview_v0_gender_context.json：7/8（87.5%），原六例5/6，新增对话两例通过 |
| 真实规划 smoke | 虚构输入生成3天9活动，通过结构与日期覆盖；非推荐质量结论 |

最新访谈 case_2 返回中文活动名称，与预设英文标准值不一致；历史 partner_boundaries 报告曾把 Disneyland 扩大为 theme parks。结果会波动，全部报告保留，不以最好一次代替结论。禁用推断和自然收束为启发式，尚无完整语义裁判；新增性别澄清策略尚无成对行为 benchmark。详见 [Evaluation](../evaluations/README.md)。

## 已知限制与未完成验证

- V0 itinerary 不是实时事实保证；未验证 POI、营业时间、交通、价格、季节或预算可行性。
- 没有行程质量评分器、普通 Prompt 对照与多次重复的个性化收益证明；原路线图研究验收仍待补证据。
- 活动标签语言/标准化与抽取范围仍需改进；本轮不扩大 Schema 或悄悄放宽 benchmark。
- special_requirements 只有确认状态，无具体文本存储；不能声称具体特殊要求已被保存或满足。
- 无时间/距离/费用/偏好冲突的确定性行程验证；预算人均/全组、每日/全程口径未建模。
- 没有登录、用户隔离、生产部署、删除接口、主体换绑、通用 Trip 更新、行程 refinement 或持久化、聊天历史、搜索/地图/工具调用、Memory、Multi-Agent。
- 普通资料 PUT 为完整替换且无版本锁；访谈/规划仅比较 Trip/State 快照，不能视为完整并发协议，网络失败后无请求幂等恢复。
- SQLite 无产品化迁移、备份/恢复 UI；人工备份与清空操作不是已实现的删除功能。

## 收尾与下一阶段入口

本次仅整理文档，未修改业务代码、用户数据库、模型或配置，未自动 commit。V0 当前功能边界冻结供继续测试；后续优先明确行程评估与结构标签标准化，是否推进 V1 实时信息由 Owner 另行决定。启动、测试命令见 [README](../README.md)，完整 API/状态语义见 [架构](ARCHITECTURE.md)。
