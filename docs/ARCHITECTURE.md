# 人生旅迹｜系统架构

Last updated: 2026-10-23

## Current Architecture｜当前实现

V0 本地 Web 闭环已实现，功能收尾；不是生产部署，也不是推荐质量已完成验收。

```text
React / Vite / TypeScript
        ↓ /api（开发代理）
FastAPI → application functions → Pydantic domain models
        ↕
SQLite（本机资料、关系、旅行、访谈状态）
        ↓
TravelContext → InterviewPrompt → InterviewLLMClient → DeepSeek
        ↓                              ↓
TripContext + InterviewState ← validated InterviewTurnResult
        ↓ deterministic readiness + 用户点击
PlanningPrompt → PlanningLLMClient → Itinerary → 校验 → Web
```

### 模块边界

| 模块 | 职责 |
| --- | --- |
| schemas | Person、Relationship、Trip/TripBudget/TripContext、Create 输入、TravelContext、访谈与规划契约 |
| application/create.py | 接收已校验输入，生成前缀 UUID4，构造领域对象 |
| application/context_builder.py | 选择本次相关人物和关系，返回深拷贝后的结构化上下文 |
| application/interview.py | 初始化、缺失主题/就绪判断、安全应用更新；不理解自然语言 |
| application/interview_prompt.py | 集中任务规则、序列化当前数据和输出 Schema；不执行 extraction |
| application/interview_runner.py | 一次访谈调用、校验应用、返回新上下文/状态/单一回复与指标 |
| application/planning.py | 独立规划指令、最低就绪门槛、一次生成、Trip ID/日期校验 |
| llm | 独立访谈/规划 Protocol，DeepSeek transport 与调用指标/错误 |
| api.py / storage.py | 薄 HTTP 层、SQL/事务/引用检查；不复制访谈或规划规则，无 ORM/service framework |
| sample_data.py / tests/fixtures | 固定虚构输入，不向正式 SQLite 自动 seed |
| evaluation | 访谈固定 benchmark 与规则评分；不是行程质量评估器 |
| frontend | 表单、选择、单轮对话和行程展示；API Key 不进入浏览器 |

### 核心数据模型

- **Person**：person_id、name、interests、dislikes、preferred_pace、food_preferences、mbti、gender。性别可选 female/male/other/prefer_not_to_say；MBTI 限16型；不自动推断偏好或体力。旧 JSON 无 gender 默认 None。
- **Relationship**：relationship_id、person_a_id、person_b_id、relationship_type、shared_travel_preferences、preferred_pace_together。拒绝 self relationship。type 为 spouse/partner/friend/family/sibling/colleague/other；A/B 无方向。spouse 明确婚姻；partner 不声明婚姻；family 不推断 parent/child。
- **Trip**：trip_id、participant_ids、destination、start_date、end_date、budget、context。至少1人、重复 ID 报错，允许同日/历史日期，end_date 不早于 start_date。
- **TripBudget**：min_amount/max_amount（至少一项，正有限 Decimal，min≤max）、currency（三位大写字母，仅格式）。不验证汇率或真实价格，也未规定人均/全组等口径。
- **TripContext**：purpose、preferred_pace、activity_preferences（软偏好）、required_activities（本次要求）、excluded_activities（本次排除）。不检查三者冲突，不回写长期 Profile。
- **Create**：PersonCreate 不带 person_id，RelationshipCreate 不带 relationship_id，TripCreate 不带 trip_id/context。create_trip 初始化独立空 TripContext。Input Schema ≠ Internal Domain Model。
- **TravelContext**：trip、participants、relationships；只保存当前选择，不是 Prompt 文本。
- **Itinerary**：trip_id、summary、days；day 为 date/theme/activities；activity 为 time_period（morning/afternoon/evening）、title、description、rationale。非空/未知字段/日期递增等结构规则由 Schema 检查；应用检查 ID 和起止日期逐日完整覆盖。

### Context Builder 选择规则

按 Trip.participant_ids 顺序选 Person，不把关系另一端自动加入旅行。所有输入 Person ID 必须唯一且参与者存在。完全不接触参与者的关系忽略；接触任一参与者的关系检查两端引用，只有双方均参与才输出。最终入选关系按关系 ID、无方向人物对+类型判重，不静默去重。API 从库中只取双方参与的关系。个人/共同/本次偏好保持独立；不推断、不覆盖、不修改输入。

### Travel Interview

```text
TravelContext + InterviewState + 最新用户消息
→ InterviewPrompt(system_prompt, user_prompt, output_schema)
→ 一次 LLM 调用
→ InterviewTurnResult
→ apply_interview_update
→ 新 TripContext / InterviewState + 一条 assistant_message
→ 等待下一条 User Turn
```

InterviewTurnResult 必含 context_update、confirmed_topics、missing_topics、ready_to_plan、assistant_message；无 next_question。assistant_message 是完整 Assistant Turn，可含简短回应和一个主要问题，也可自然收束；应用层不从回复反向提取状态。

六主题为 purpose、preferred_pace、activity_preferences、required_activities、excluded_activities、special_requirements；状态 unknown/confirmed。**最低门槛为完整 Trip Setup + purpose/preferred_pace/required_activities/excluded_activities 四主题 confirmed**，另外两项不阻塞。

- 省略字段保留；标量提供值覆盖，显式 None 清空。
- 列表提供时完整替换，[] 明确没有，显式 null 拒绝；不 append/union/合并历史。
- confirmed_topics 累计明确确认；空值可 confirmed，不要求非空。未提供 update 时确认当前已有值，不隐式清空。
- 更新值本身不自动确认主题；LLM ready/missing 为建议。系统每次重算就绪，不信任客户端布尔值或回复文案。
- special_requirements 暂无具体内容字段，仅支持确认状态；不代表实际要求已保存/满足。
- Prompt 要求整句多主题理解，不按 missing 顺序填表；足够就收束，不重复问已表达内容。
- 性别/MBTI/关系标签不是兴趣或体力事实。partner 可用于中性、可拒绝的约会氛围征询；仅明确同意后记录本次需求，拒绝/正常玩/信息足够时不推动，不问私密细节。

apply_interview_update 返回新对象，run_interview_turn 把新 TripContext 放进新的完整 TravelContext，输入不修改。旧 apply_interview_turn 仅返回状态；新调用优先使用组合入口。

### Planning

用户点击后重新加载当前 Trip/人物/关系/InterviewState并检查系统门槛，未通过零模型调用。build_planning_prompt 仅序列化相关 TravelContext 和 Itinerary JSON Schema；PlanningLLMClient.generate_itinerary 返回独立 PlanningCallResult，不复用访谈输出模型。现有 DeepSeekInterviewClient 实现两种方法并共用 transport/LLMCallMetrics。

rationale 要解释明确个人/共同偏好或本次需求的适配，Popularity ≠ Personal Relevance。不从性别/MBTI/关系标签编造偏好。不接实时工具，固定返回 `V0_FACT_NOTICE`：行程基于模型知识，未验证营业时间、交通、价格或实时信息。**Schema 合法不等于事实准确或现实可执行。**

只返回结果，不写入 SQLite；前端成功后禁用同页重复规划，刷新不恢复行程。本轮没有 refinement 或自动从访谈跳到模型规划。

### SQLite 与主体

| 表 | 记录 |
| --- | --- |
| persons | id 主键 + 完整 Person JSON |
| relationships | id、规范化两端 Person 外键、type、JSON；人物对+type 唯一 |
| trips | id + 含 TripContext 的完整 Trip JSON |
| trip_participants | trip_id/person_id 外键与 position，保留参与者顺序 |
| interview_states | trip_id 一对一外键 + 可还原 InterviewState JSON，不存派生字段 |
| local_profile | singleton=1 + person_id 外键，本机唯一主体指针 |

读回 JSON 再经领域校验。默认 .local/life_journey.sqlite3，LIFE_JOURNEY_DB 可覆盖。无自动 fixtures seed；旧库通过 CREATE TABLE IF NOT EXISTS 补缺表，没有正式迁移框架。

我的资料在空库首次保存时原子创建并绑定；有旧人物时需明确首次选择，不能猜测或静默换绑。后续更新保留同一 ID，添加同行人不改变主体。这是本机入口语义，不改变 Person 独立模型，不构成认证。

Trip 与参与者原子创建；访谈 Trip.context 与 InterviewState 同一事务写回。LLM 调用期间不持 SQLite 写锁，结束前比较 Trip/State 快照，变化返回409。未覆盖人物/关系修改的完整并发版本控制；没有请求幂等或网络失败后的自动恢复。

人物/关系普通 PUT 为完整替换，省略字段使用 Create 默认值；不当成 PATCH。人物/关系分步保存，后者失败不撤销前者。聊天、草稿、行程不持久化。无删除、通用 Trip 更新、主体换绑或备份恢复产品接口。

### API

| 路径 | 方法 | 职责 |
| --- | --- | --- |
| /api/profile | GET / PUT | 读取固定主体或创建/更新主体资料；GET 不创建 |
| /api/profile/{person_id} | PUT | 首次绑定已有主体；不同人换绑409 |
| /api/persons | GET / POST | 人物列表/新增独立人物 |
| /api/persons/{person_id} | GET / PUT | 读取/完整更新人物 |
| /api/relationships | GET / POST | 关系列表/创建 |
| /api/relationships/{relationship_id} | GET / PUT | 读取/完整更新关系 |
| /api/trips | GET / POST | 列表/创建 Trip Setup |
| /api/trips/{trip_id} | GET | 回读旅行 |
| /api/trips/{trip_id}/interview | GET / POST | 无模型恢复状态 / {user_message}执行一轮 |
| /api/trips/{trip_id}/planning | POST | 重新检查 readiness 后生成 itinerary |

访谈返回 trip_id、assistant_message、ready_to_plan（系统）、llm_ready_to_plan（建议）、context、state、metrics。规划返回 itinerary、notice、metrics。两种调用默认 metrics=null，debug=true 可查看，不持久化日志。

404 不存在，422 校验/引用非法，409 重复或主体绑定/未就绪/状态冲突，503 配置缺失，502 模型请求/输出失败。前端明确显示错误，不自动重试；网络异常可能出现在服务端已提交后，应刷新结构化状态再决定重发。

### Provider、Web 与开发入口

当前实现配置为 DeepSeek Responses，BASE_URL=https://api.deepseek.com，默认 deepseek-flash，可用环境变量覆盖。SDK 使用 instructions/input 和 text.format=json_schema，非流式、reasoning=none、自动重试关闭。普通访谈2048 output tokens/60秒；Web规划8192/120秒。配置来自 os.environ，不自动读取 .env，不记录 Key、完整 Prompt 或原始响应。记录可获得的 model/tokens/latency，缺失为 None，不虚构费用。

前端 React/Vite/TypeScript/原生 CSS；照片本地 public/journey-flower.jpg，桌面取景右移以避开正文，暗调视觉、中文关系标签。共用 PersonFields 支持性别/MBTI，form/input autocomplete=off。当前只做 turn-based，无 streaming/打断/并发消息队列。开发代理 /api→8000，CORS 仅本地5173；启动见根 README。

CLI 复用 sample_data 固定场景，仅内存访谈，就绪退出，不生成 itinerary。tests 使用 fake Client/临时数据库；真实访谈 benchmark 独立手动运行，报告与边界见 evaluations/README.md。最新功能检查692 pytest通过、前端build通过，推荐质量验收尚未完成。

## Approved V0 Design｜尚未完成的验证

本地核心流程已经实现，不再把它列为待开发。原 V0 的普通 Prompt baseline 对照、成对场景多次运行、行程个性化/限制一致性评分仍缺少完整证据；尚无 itinerary evaluator。保留为验证缺口，不把功能收尾说成研究假设已获证明。

未来实时信息、工具、Memory、部署等见 ROADMAP，均未在当前任务授权开发。
