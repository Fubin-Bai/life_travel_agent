# 人生旅迹｜技术决策记录 Decisions

Last reviewed: 2026-10-23

## V0 收尾决策索引

本文件为按时间记录的 ADR，早期 Context 保留当时事实，不代表当前状态。当前实现以 ARCHITECTURE/CURRENT_STATUS 为准。

- ADR-001 独立 Person 仍有效；ADR-028 新增本机固定本人入口，不改变领域独立性。
- ADR-007 暂不数据库已被 ADR-025 的 Owner 授权本地 SQLite 取代；不等于批准远程生产数据库。
- ADR-010 结构化 Itinerary、ADR-014 指标已实现；访谈与规划分离见 ADR-022～027。
- ADR-013 Provider 解耦仍有效；具体实现已由 ADR-024 采用 DeepSeek，不再处于未选定状态。
- ADR-016 指仓库文档作为事实源；本轮不推断已连接/推送 GitHub，也不自动 commit。
- 当前没有长期 Memory、实时工具、Multi-Agent 或部署。V0 功能收尾不等于行程质量研究验收完成。

## 1. 文档目的

本文档用于记录“人生旅迹”开发过程中已经确认的重要产品与技术决策。

每项决策尽量说明：

- Context：为什么需要做这个决定
- Decision：最终决定是什么
- Reasoning：为什么这么选
- Trade-offs：代价是什么
- Revisit When：什么情况下需要重新评估

本文件只记录已经形成明确结论的决策。

仍处于讨论阶段的想法，不应提前写成正式 Decision。

---

## ADR-001｜Person 是独立实体，不使用固定 Companion Profile

### Status

Accepted

### Context

旅行产品很容易采用：

> 一个主用户 + 若干同行者 Companion

的结构。

但“人生旅迹”的产品逻辑不是这样。

一个人首先是独立的人，其次才和其他人产生关系。

例如：

Person A 和 Person B 是夫妻，但：

- A 可以独自旅行
- B 可以独自旅行
- A 可以和朋友 C 旅行
- B 可以和朋友 D 旅行

因此，把 B 永久定义为 A 的 Companion 会限制未来数据模型。

### Decision

采用：

- Person
- Relationship
- Trip Participants

三个独立概念。

Person 表示独立的人。

Relationship 表示人与人之间的长期关系。

Trip Participants 表示某次旅行实际参加的人。

### Reasoning

这样能够：

- 支持 Solo Travel
- 支持不同朋友组合
- 支持夫妻分别旅行
- 避免重复创建人物 Profile
- 更接近真实社交网络结构
- 为未来 Relationship Memory 提供基础

### Trade-offs

数据模型会比：

> User + Companion

稍微复杂。

但这种复杂度来自真实产品需求，因此值得保留。

### Revisit When

目前没有计划改变这一核心模型。

只有在真实用户数据证明该结构产生明显不必要复杂度时再重新评估。

---

## ADR-002｜Person Preference 与 Relationship Preference 分开

### Status

Accepted

### Context

一个人的个人偏好，不一定等于他和某个人一起旅行时的偏好。

例如：

Person A 独自旅行时：

- 喜欢高强度探索

但 A 和伴侣 B 一起旅行时：

- 更喜欢慢节奏
- 更重视餐饮
- 更愿意安排休息

### Decision

未来数据结构中区分：

- Person-level preference
- Relationship-level preference

### Reasoning

系统需要同时理解：

> “我喜欢什么”

和：

> “我们在一起时喜欢什么”。

否则多人旅行只能简单合并两个 Person Profile，无法表示关系本身形成的旅行习惯。

### Trade-offs

Relationship 数据会逐渐增加复杂度。

因此 V0 只保留最基础 Relationship 信息，不提前建立复杂 Relationship Memory。

### Revisit When

当真实测试证明 Relationship-level 信息对推荐质量没有明显帮助时，可以缩减这一层设计。

---

## ADR-003｜V0 使用结构化数据，而不是自由文本 Profile

### Status

Accepted

### Context

用户 Profile 可以简单保存成：

> “Kelly 喜欢咖啡馆，不喜欢人多……”

这样的自然语言。

但自由文本：

- 不容易验证
- 不容易比较
- 不容易测试
- 后续难以做精准 Context Selection
- 容易不断膨胀

### Decision

V0 使用明确的结构化 Schema 表达：

- Person
- Relationship
- Trip
- Trip Context
- Itinerary

### Reasoning

Structured Data 可以：

- 明确字段含义
- 降低 Prompt 歧义
- 支持自动验证
- 支持 Unit Test
- 支持后续 API
- 支持未来 Memory Retrieval
- 更方便进行 Evaluation

### Trade-offs

结构化字段可能无法表达所有细微偏好。

因此未来允许结构化字段与自然语言补充信息共存。

### Revisit When

当出现大量无法合理放入固定 Schema 的真实用户信息时，重新设计 Schema 与 Free-form Memory 的边界。

---

## ADR-004｜V0 使用 Pydantic 定义核心 Schema

### Status

Accepted

### Context

项目需要定义多个结构化 Python 数据对象。

可选方式包括：

- dict
- dataclass
- Pydantic
- 自定义 class

### Decision

V0 使用 Pydantic。

### Reasoning

Pydantic 能够：

- 提供明确类型
- 自动 Validation
- 支持 JSON serialization
- 与 Structured Output 容易结合
- 后续与 FastAPI 兼容
- 代码仍然比较容易理解

### Trade-offs

引入了外部 dependency。

但当前收益明显高于依赖成本。

### Revisit When

如果未来技术栈发生明显变化，再重新评估。

---

## ADR-005｜V0 不使用 Multi-Agent

### Status

Accepted

### Context

Agent 项目很容易为了展示技术而设计：

- Planner Agent
- Research Agent
- Critic Agent
- Recommendation Agent
- Memory Agent

但当前 V0 核心任务只是：

> 根据结构化个人信息生成个性化 itinerary。

### Decision

V0 不使用 Multi-Agent。

优先采用：

> 普通 Python Workflow + 单模型调用

或在必要时使用少量明确的 LLM Call。

### Reasoning

当前 Multi-Agent 会带来：

- 更多 Token
- 更高 Latency
- 更复杂 Debug
- 更复杂 State
- 更难 Evaluation
- 更难解释失败原因

而目前没有明确问题需要多个 Agent 才能解决。

### Trade-offs

项目早期不会展示 Multi-Agent 技术。

但这是一项主动工程决策，而不是能力不足。

### Revisit When

当出现以下问题时重新考虑：

- 存在长期稳定、职责明确的独立任务
- 单一 Workflow 难以管理复杂分支
- 不同任务明显需要不同上下文或模型
- 多 Agent 能通过 Evaluation 证明带来质量收益

---

## ADR-006｜V0 不使用 LangChain / LangGraph

### Status

Accepted

### Context

LangChain 和 LangGraph 可以帮助构建复杂 LLM Workflow。

但 V0 当前流程很简单：

Person / Relationship / Trip
→ Context Builder
→ Prompt
→ LLM
→ Itinerary

### Decision

V0 首先使用原生 Python 实现 Workflow。

### Reasoning

这样：

- 更容易理解底层逻辑
- 更容易 Debug
- 更容易测试
- 减少 framework abstraction
- 更适合学习 Agent Engineering 原理
- 面试中能够解释系统实际如何运行

### Trade-offs

未来复杂 Workflow 可能需要自行编写更多 orchestration code。

### Revisit When

如果系统出现：

- 大量 branching
- persistent state
- retry graph
- 多 Tool Loop
- Human-in-the-loop
- workflow checkpoint

再评估 LangGraph 或类似框架。

---

## ADR-007｜V0 暂不使用数据库

### Status

Superseded by ADR-025（2026-10-23，本地 SQLite）；以下保留历史决策背景。

### Context

长期产品最终需要保存：

- Person
- Relationship
- Trip
- Itinerary
- Memory

但 V0 当前主要是验证个性化推荐逻辑。

### Decision

V0 初期使用：

- Python objects
- JSON / fixture files
- Mock data

进行开发与测试。

暂不接入正式数据库。

### Reasoning

当前数据库不能帮助验证核心产品假设。

过早加入数据库会增加：

- Schema migration
- connection management
- persistence logic
- setup complexity

### Trade-offs

V0 数据无法形成完整长期用户系统。

这是当前阶段可接受的限制。

### Revisit When

以下任一情况出现时引入数据库：

- 需要创建真实多个用户
- 需要跨 Session 持久化数据
- 开始开发长期 Memory
- 开始开发正式 API / Frontend

---

## ADR-008｜V0 不使用 Vector Database

### Status

Accepted

### Context

Vector Database 经常与 Memory 和 RAG 一起使用。

但 V0 当前没有大量：

- 长期聊天历史
- 用户行为
- Trip History
- 非结构化 Memory

需要检索。

### Decision

V0 不使用 Vector Database。

### Reasoning

当前数据量很小，并且大多数核心数据可以通过结构化字段直接读取。

Vector Retrieval 当前不会解决实际问题。

### Trade-offs

未来非结构化长期 Memory 增加后，需要重新设计 Retrieval。

### Revisit When

出现大量无法通过：

- ID
- Structured Field
- Database Query

直接定位的历史信息时重新评估。

---

## ADR-009｜LLM 与确定性代码职责分离

### Status

Accepted

### Context

LLM 可以完成很多任务，但不代表所有任务都应该交给模型。

例如：

- ID lookup
- 数学计算
- Schema validation
- Participant selection

都可以由普通 Python 更稳定地完成。

### Decision

原则上：

#### LLM 负责

- 语义理解
- 个性化判断
- Recommendation reasoning
- Preference balancing
- Planning
- Natural language

#### Deterministic Code 负责

- Validation
- Lookup
- State
- Calculations
- Rule checks
- API handling
- Data processing

#### External Tool 负责现实事实

未来例如：

- Weather
- Route
- Distance
- Opening hours
- Real POI

### Reasoning

这样能够提高：

- Reliability
- Debuggability
- Testability
- Cost efficiency

并减少 Hallucination。

### Trade-offs

系统需要设计明确的数据和模块边界，而不是只写一个巨大 Prompt。

这是有意接受的复杂度。

---

## ADR-010｜使用 Structured Output 生成 Itinerary

### Status

Accepted

### Context

如果 LLM 直接输出自由文本旅行攻略：

- 格式不稳定
- 后续无法可靠处理
- 难以测试
- 难以展示到 UI
- 难以进行 Constraint Validation

### Decision

LLM 的核心 itinerary 输出必须符合明确 Schema。

例如：

Itinerary
→ ItineraryDay
→ ItineraryActivity

### Reasoning

Structured Output 能够：

- 保证基本格式
- 自动 Validation
- 支持后续程序处理
- 支持 Evaluation
- 支持未来 Frontend
- 支持局部 Replanning

### Trade-offs

模型输出自由度降低。

但核心系统输出需要稳定，因此值得。

---

## ADR-011｜Popularity 与 Personal Relevance 分离

### Status

Accepted

### Context

普通旅行推荐系统通常高度依赖：

- 热门榜单
- Review Count
- Rating
- Top Attractions
- Social Media Trends

但“人生旅迹”的产品目标不是生成标准游客清单。

### Decision

系统中：

> Popularity ≠ Personal Relevance

热门程度可以作为一个信息信号，但不能直接成为推荐理由。

### Reasoning

一个著名地点可能：

- 很热门
- 很经典
- 评分很高

但与某个用户兴趣明显不匹配。

反之，一个不那么热门的地点可能更符合个人偏好。

因此最终推荐优先考虑：

> Personal Fit

### Trade-offs

系统可能生成与传统“必去攻略”明显不同的结果。

这不是错误，而是产品差异化的一部分。

### Revisit When

不会重新评估这一核心产品原则。

未来需要调整的只是 Popularity 在 Ranking 中占多大权重。

---

## ADR-012｜Memory 不等于完整聊天历史

### Status

Accepted

### Context

最简单的“长期记忆”方式是：

> 每次把全部历史 Conversation 发给模型。

但随着使用增加，这会导致：

- Context 无限增长
- Token Cost 上升
- irrelevant information 增加
- 模型更难找到真正重要的信息

### Decision

未来 Memory 采用：

> 保存有价值的信息 + 根据当前任务选择相关信息

而不是永久发送完整 Conversation History。

### Reasoning

长期方向应逐渐区分：

- Person Memory
- Relationship Memory
- Trip Memory
- Temporary Conversation Context

未来再根据需求选择：

- Structured Memory
- Summary
- Retrieval
- Embeddings

### Trade-offs

需要设计 Memory Update 和 Retrieval 逻辑。

但这是长期 Agent 必须解决的问题。

### Revisit When

具体 Memory 实现方式将在 V4 阶段重新设计。

---

## ADR-013｜模型 Provider 不与业务逻辑强绑定

### Status

Accepted

### Context

不同 LLM 在：

- Quality
- Structured Output
- Cost
- Latency

方面表现不同。

如果项目代码直接依赖一个模型 Provider，后续实验会困难。

### Decision

通过独立的 LLM Client / configuration 管理模型调用。

业务逻辑不直接依赖具体 Provider。

### Reasoning

这样方便：

- 切换模型
- 做 benchmark
- 比较价格
- 做 model routing
- 未来增加 fallback

### Trade-offs

会比直接在业务代码里调用 API 多一层 abstraction。

但这一层边界明确且有实际价值。

---

## ADR-014｜从第一版开始保留 Token 与 Latency 信息

### Status

Accepted

### Context

Token Cost 和 Latency 是 Agent 系统的重要工程指标。

如果项目后期才开始记录，无法比较不同版本的真实变化。

### Decision

从第一次真实 LLM API Call 开始，尽量记录：

- model
- input tokens
- output tokens
- total tokens
- latency

如果 Provider 能直接提供 cost 信息，也一并记录。

### Reasoning

未来可以回答：

- 哪个模型性价比更高？
- Context 增长了多少？
- 某次重构是否降低 Token？
- 强模型是否真的提高质量？

### Trade-offs

增加少量 logging 工作。

收益明显高于成本。

---

## ADR-015｜Evaluation 从 V0 开始，而不是最后补

### Status

Accepted

### Context

LLM 产品很容易出现：

> “这个回答看起来挺好。”

但没有固定标准判断系统是否真正变好。

### Decision

从 V0 开始构造固定：

- Persona
- Relationship
- Trip Scenario

用于重复测试。

### Reasoning

这样可以逐渐形成 Regression Evaluation。

例如模型升级或 Prompt 修改后，可以比较：

- Personalization
- Profile consistency
- Relationship awareness
- Recommendation relevance

而不是仅依赖主观感受。

### Trade-offs

早期需要额外维护测试 Case。

但这是 Agent Engineering 的核心能力之一。

---

## ADR-016｜GitHub Repository 作为项目事实源

### Status

Accepted

### Context

项目同时使用：

- Chat
- Work
- Codex

三个不同工作环境。

如果项目事实只存在于聊天中，很容易出现：

- 不同聊天理解不同
- 架构信息过期
- 新 Conversation 缺少上下文
- 重复发送大量 Prompt

### Decision

Repository 文档作为项目的 Single Source of Truth。

主要文件：

- `PRODUCT.md`
- `ARCHITECTURE.md`
- `ROADMAP.md`
- `DECISIONS.md`
- `CURRENT_STATUS.md`
- `AGENTS.md`

### Reasoning

Chat / Work / Codex 都可以围绕同一套项目文档工作。

长期信息不依赖某个具体 Conversation。

### Trade-offs

开发过程中必须保持文档同步。

这是可以接受且有价值的工程纪律。

---

## ADR-017｜当前优先保证项目 Owner 能理解核心代码

### Status

Accepted

### Context

该项目不仅是产品开发项目，也是 AI / Agent Engineering 学习和求职项目。

如果核心架构全部由 Coding Agent 自动生成但无法解释：

项目的学习价值和面试价值都会下降。

### Decision

AI 可以大量辅助机械开发工作。

但以下核心内容必须保持清晰、可解释：

- Data Model
- Context Construction
- Prompt Design
- LLM Client
- Agent Workflow
- Tool Calling
- Memory
- Evaluation
- Model Routing

### Reasoning

目标不是：

> 最大化 AI 自动生成代码数量。

而是：

> 在 AI 辅助下完成真实项目，同时真正掌握核心系统。

### Trade-offs

开发速度可能略慢。

但学习质量和求职价值更高。

---

## ADR-018｜第一版 Person 与中性 Relationship Schema

### Status

Accepted — Owner 已确认，本轮已实现并通过基础测试。

### Context

V0 需要可验证、可序列化的最小人物与关系数据，不提前引入 Trip、Memory 或偏好合并逻辑。

### Decision

- Person：`person_id`、`name`、`interests`、`dislikes`、`preferred_pace`、`food_preferences`。
- Relationship：`relationship_id`、`person_a_id`、`person_b_id`、`relationship_type`、`shared_travel_preferences`、`preferred_pace_together`。
- ID 使用显式字符串，不引入 UUID；姓名允许重复。
- 节奏值为 `slow / moderate / fast`，未知为 `None`；列表默认独立空列表，表示未记录。
- `food_preferences` 仅表示食物喜好，不承载硬性 dietary constraints。
- A/B 为无方向人物引用，不表达主从或 parent/child 角色。类型为 `spouse / partner / friend / family / sibling / colleague / other`。
- `sibling` 表示明确的兄弟姐妹关系；`family` 只表示家庭关系，不推断 parent/child 等具体身份。
- `spouse` 表示明确婚姻关系；`partner` 表示伴侣关系，不声明婚姻状态。
- 共同旅行偏好由明确输入记录，不自动计算兴趣交集，不覆盖 Person 偏好。
- Pydantic v2 严格校验类型、拒绝未知字段；字符串去首尾空白后非空；拒绝 self relationship。
- 使用 pytest 作为开发测试依赖，覆盖数据校验、默认列表隔离、偏好分离与 JSON roundtrip。

### Trade-offs

本 ADR 当时的单对象 Schema 不校验集合引用或重复；当前集合层由 Context Builder、SQLite 外键与唯一约束承担相应检查。仍不实现关系推断或偏好优先级，不将跨对象查询塞进 Schema。

### Revisit When

真实场景需要 parent/child 等角色、硬性限制或更细偏好结构时，再经 Owner 确认扩展。

---

## ADR-019｜Trip Setup 与对话形成的 TripContext 分离

### Status

Accepted — Owner 于 2026-10-22 授权，本轮 Schema 已实现并通过测试。

### Context

用户只需明确填写或选择旅行基础信息，其余本次需求未来通过对话逐渐获取。此前将目的地、日期放在 TripContext 的讨论提案已被本决策替代；未实施旧提案。

### Decision

- Trip 保存必填字符串 `trip_id`、至少一人的 `participant_ids`、`destination`、`start_date`、`end_date`、`budget`，以及默认独立空实例的 `context`。
- trip_id 为内部标识，fixture 可人工提供，未来由系统生成，用户不填写；本轮不实现生成器。
- participant_ids 引用 Person ID，标准化后重复报错，不静默去重；不复制 Profile，不从 Relationship 自动增加人物。
- 日期采用目的地当地日历，首尾包含；允许同日和历史日期，结束不得早于开始。
- TripContext 保存可空 `purpose`、`preferred_pace` 和默认独立空列表的 `activity_preferences`、`required_activities`、`excluded_activities`，分别表达软偏好、明确要求应安排、明确不要安排。
- TripContext 是未来对话提取和确认的内部结构化结果，不是逐项表单；本轮仅允许直接构造，不实现提取、更新、合并或回写长期 Profile。
- TripBudget 保存可空 `min_amount`、`max_amount` 和必填 `currency`；至少一个金额边界，金额为正有限 Decimal，下限不大于上限。允许仅下限、仅上限及相等边界。
- 币种只校验三位大写英文字母，不验证真实货币有效性，不默认币种。不增加酒店等费用拆分，也不自动推断预算的人均/全组、每日/全程或费用包含口径。
- 延续严格类型、拒绝未知字段与非空文本。Python 输入使用 date / Decimal；JSON 日期为 YYYY-MM-DD，Decimal 序列化为十进制字符串，支持完整 roundtrip。

### Trade-offs

本轮只提供数据契约，不保证人物存在、全局 ID 唯一、活动要求无冲突或真实行程可执行。预算是规划输入，不证明系统有真实价格验证能力；未来实际使用金额前需明确预算口径。

### Revisit When

需要预算计算、真实信息验证、个人适用约束或更细日期/目的地结构时，再根据场景扩展，不提前实现通用约束引擎。

---

## ADR-020｜Person 可选 MBTI 仅保存用户自述

### Status

Accepted — Owner 于 2026-10-22 授权，本轮已实现并通过测试。

### Decision

Person 新增 `mbti`，默认 None，仅允许标准 16 种大写类型；去除首尾空白，不自动更正大小写或接受 A/T 等扩展标签。其他 Person 字段语义保持不变。

只接受用户明确输入，不根据聊天或行为自动推断。MBTI 不自动转化为旅行偏好；明确偏好始终优先，不实现 MBTI 排序或推荐逻辑。

### Trade-offs

Schema 能验证类型和取值，不能证明输入来自用户；来源与未来更新流程必须遵循本约定，本轮不引入来源或 Memory 系统。

### Revisit When

未来需要对话更新 Profile 时，再设计明确确认与来源保障，不能放宽为自动推断。

---

## ADR-021｜用户 Create 输入与内部模型分离，应用层生成 UUID4 ID

### Status

Accepted — Owner 于 2026-10-22 授权，本轮已实现并通过测试。

### Context

内部模型需要稳定 ID，但用户不应手填新对象的系统 ID。TripContext 属于未来对话理解，也不属于初始 Trip Setup 表单。

### Decision

- User Input Schema ≠ Internal Domain Model。三个独立 Create 模型集中在 schemas/create.py，不继承完整内部模型以隐藏字段。
- PersonCreate 接受 Person 除 person_id 外的字段；RelationshipCreate 接受 Relationship 除 relationship_id 外的字段。
- TripCreate 仅接受 participant_ids、destination、start_date、end_date、budget，拒绝 trip_id 和 context。
- 延续严格类型、未知字段拒绝、非空文本、枚举、self relationship、参与者非空/重复、日期顺序及预算校验。MBTI 仅保存用户自述，不推断。
- application/create.py 提供 create_person、create_relationship、create_trip，只接收对应已校验输入。
- 使用 Python 标准库 uuid.uuid4，输出 person_<uuid>、relationship_<uuid>、trip_<uuid> 字符串。ID 由应用逻辑生成，不在输入 Schema 或内部模型的默认值中生成，也不由用户提供。
- 创建函数通过 model_dump(mode="python") 取得独立数据，再调用内部模型正常构造并校验；不使用跳过校验的 model_construct，不回写输入，不共享列表或嵌套预算。
- create_trip 显式创建独立空 TripContext。内部模型仍接受显式字符串 ID，保留现有 fixture 和 JSON roundtrip 能力。
- 不新增依赖，不访问数据库或文件，不查询引用人物，不实现持久化与更新流程。

### Reasoning

UUID4 无需数据库、全局计数器或协调服务，适合当前独立创建对象；类型前缀仅用于识别。输入模型显式声明字段，便于解释用户边界；保留少量短校验逻辑，不提前建立通用 Schema 生成框架或复杂继承。

### Trade-offs

UUID4 碰撞概率极低，但不是集合级唯一性证明；本轮不进行冲突查询。输入和内部模型的共同校验规则需要在字段演进时同步维护。每次调用 create 都创建新对象，不提供幂等重试语义。来源、引用存在性与全局唯一性仍需未来对应流程保障。

本决策替代 ADR-018 中“当前不引入 UUID”及 ADR-019 中“未来系统生成 ID”的阶段性约定；内部字段类型仍为字符串，不改写历史决策。

### Revisit When

出现持久化、幂等创建或具体引用完整性需求时，再设计对应边界，不提前引入 Repository Pattern 或 Service Framework。

---

## ADR-022｜动态访谈与独立确认状态，Python 保留最低 Planning 门槛

### Status

Accepted — Owner 于 2026-10-22 授权，状态、协议与确定性逻辑已实现。当时尚无真实对话；现已由 ADR-024/026 接入真实 Provider 与 Web，见当前架构。

### Context

TripContext 的空列表无法区分“尚未询问”和“明确没有”。访谈不能变成固定问卷，也不能让 LLM 单独决定是否进入 Planning。

### Decision

Interview questions are dynamically generated by the LLM.
Python defines interview goals, confirmation state, and minimum planning readiness.

- InterviewState 与 TripContext 分开，绑定 trip_id；六主题为 unknown / confirmed，不根据 Profile、关系标签、MBTI 或现有值自动确认。
- 四个最低主题为 purpose、preferred_pace、required_activities、excluded_activities；建议主题 activity_preferences、special_requirements 不绝对阻塞。special_requirements 仅保留主题状态，不提前增加具体要求 Schema。
- 完整 Setup 的检查复用 TripCreate，应用函数每次重检。phase、ready_to_plan、missing_topics 从内部确认与 Setup 快照派生，不接受 LLM 注入。
- LLM readiness judgment is advisory; deterministic minimum readiness is required before entering planning. LLM missing_topics 同样只是建议，不覆盖或撤销内部确认。
- TripContextUpdate 表达稀疏增量，省略不更新，列表 [] 表示明确没有，显式列表 null 拒绝；可空标量 null 表达明确无具体目的/节奏偏好。序列化保留实际提供字段。
- InterviewTurnResult 是未来单轮协议，不是实际调用实现。状态应用只累计 confirmed_topics，不自动合并增量、解析自然语言或生成问题。

### Trade-offs

最低就绪不等于所有信息已存储、已完成增量合并或已经规划。来源真实性、特殊要求具体值、确认撤销、冲突与补问工作流尚未实现；增量应用与确认一致性已在 ADR-023 实现；其他未完成项继续保留边界，避免将最低就绪误作全部执行保障。

### Revisit When

真实访谈案例证明最低门槛不足，或需要特殊要求存储、撤销确认时，再由 Owner 明确调整，不提前构建复杂状态机。

---

## ADR-023｜访谈字段更新采用显式覆盖、清空与列表完整替换

### Status

Accepted — Owner 于 2026-10-22 授权，本轮已实现并通过测试。

### Context

更新遗漏不等于清空；列表自动合并会保留用户已经撤销的旧偏好。情境与确认需要一起返回，同时保留 LLM 与确定性就绪的差异。

### Decision

Scalar fields use overwrite / explicit clear semantics.
List fields use replace semantics when present.
Omitted fields preserve existing values.

- TripContextUpdate 是字段级稀疏更新，但列表字段一旦提供，即表示新的完整列表，不是追加项；application 不 append、union 或去重。
- 标量具体值覆盖、显式 None 清空；列表 [] 明确清空；省略保持旧值。应用后重新验证 TripContext，输入对象不变。
- Application layer applies validated interview updates; it does not infer user intent.
- apply_interview_update 返回 AppliedInterviewTurn（updated_context、updated_state、llm_ready_to_plan、派生 deterministic_ready_to_plan）。现有 apply_interview_turn 保留只返回状态的兼容接口。
- 确认主题有字段更新时确认新值；未提供字段时确认当前已存值，包括已存 None / []。省略不被猜测为清空；内容不自动带来新增确认或撤销确认。
- special_requirements 只允许更新确认状态，不保存具体文本，不扩展 TripContext。
- 两种 ready 判断分别保留；确定性最低门槛仍必要，不因任一判断或其差异执行 Planning。本轮不实现 orchestration，不自动写回 Trip。

### Trade-offs

后续提取层需提供字段当前完整值并保障确认来源。当前不实现历史冲突、撤销确认或特殊要求具体值；返回的新情境需调用方明确接收，不偷偷修改共享对象。本决策推进 ADR-022 中尚未实现增量应用的阶段性状态，不改变其动态提问与确定性门槛原则。

### Revisit When

真实交互需要追加操作或撤销确认时，再设计显式操作协议，不通过自动合并猜测用户意图。

---

## ADR-024｜最小单轮 LLM Protocol 与 DeepSeek Responses Provider

### Status

Accepted — Owner 于 2026-10-22 授权；本轮实现通过 mock 测试与一次真实 API smoke test。

### Context

首次接入真实模型，需要保持业务与 Provider 解耦、保留字段省略语义，并从第一次调用提供真实 token/latency 信息。

### Decision

- 使用单方法 InterviewLLMClient Protocol 和具体 LLMCallResult，不预先泛化多任务平台或增加继承层级。
- DeepSeek 实现使用官方文档推荐的 openai Python SDK（新增最小依赖 openai>=2,<3），调用 Responses API；SDK 仅在 llm/deepseek.py 中导入。
- 默认模型 deepseek-flash，使用 os.environ 读取 Key/模型，不建立 Settings framework 或自动加载 .env。
- text.format=json_schema 直接使用现有 InterviewTurnResult Schema，不通过 SDK parse 自动严格化可省略字段；响应仍通过 JSON 与 Pydantic 验证。
- 每轮只请求一次，max_retries=0，不做自动 HTTP/结构重试或额外用户回复调用；错误交给未来上层处理。
- 返回调用指标，不默认写完整 Prompt/响应日志，不持久化请求。缺失指标为 None，不编造成本。

### Reasoning / Trade-offs

SDK 避免手写 HTTP，Protocol 允许 fake/其他 Provider 替换。关闭重试使调用数和失败边界明确，但暂不自动恢复临时错误。原生 JSON Schema 不能替代 Python 跨字段校验；Provider 不负责偏好推断、状态应用或 Planning。

### Verification

官方参数来源：[Responses API](https://api-docs.deepseek.com/api/create-response/)、[SDK 示例](https://api-docs.deepseek.com/guides/responses_api/)。已用 fake HTTP 验证正常/错误路径，另有一次虚构场景真实调用成功；未验证多轮或规划能力。

### Revisit When

出现真实恢复需求或第二个 Provider 时，再据调用失败证据评估有限重试/适配；不提前引入 routing 或通用服务框架。

---

## ADR-025｜本地 FastAPI CRUD 与最小 SQLite 持久化

### Status

Accepted — Owner 于 2026-10-23 明确授权并实现；替代早期“暂不使用数据库”的阶段约定，不引入远程存储。

### Decision

使用 FastAPI + 标准库 sqlite3。HTTP 输入复用既有 Create Schema，创建复用 create_* / UUID4；更新为 PUT 完整替换用户字段并保留 ID。SQLite 保存领域 JSON，关系和 Trip participant 引用使用外键，当前库内主键唯一；同人物对同类型关系拒绝重复。多表旅行写入使用单事务，不引入 ORM/Repository Pattern/Service Framework。

### Trade-offs

优先少量可解释代码，JSON 保留 Decimal/date/列表语义；暂不支持复杂字段 SQL 查询、迁移、备份、删除和多用户认证。PUT 不是 PATCH，省略字段重置为已有 Schema 默认值；无并发版本锁。人物与关系独立保存，符合 Person ≠ Relationship；UI 两步保存不是联合事务。此处原为可切换 Person；已由 ADR-028 的本机固定主体绑定取代。前端代理仅开发环境，本轮不部署。

### Revisit When

真实多用户、复杂查询或 schema 演进产生需求时再评估迁移/索引/身份与并发控制。本轮不持久化 InterviewState、不接 DeepSeek 或 run_interview_turn；后续接口须明确状态生命周期和 TripContext 写回。

---

## ADR-026｜Web 访谈按 Trip 保存结构化状态，情境与确认原子写回

### Status

Accepted — Owner 于 2026-10-23 授权 Web Interview 接入。

### Decision / Trade-offs

保留现有 runner / Provider / Prompt，API 只加载当前 Trip 相关数据并组合调用。interview_states 以 trip_id 一对一保存可还原 InterviewState JSON，TripContext 不拆表、不复制。模型调用期间不占 SQLite 写锁，完成后核对快照并在同一事务提交 Trip 与状态；冲突拒绝覆盖，无自动重试。GET 恢复状态不调用模型，首次成功 POST 才持久化。系统 ready 为返回值，模型 ready 仅建议；不根据 assistant_message 更新后端状态。完整聊天记录暂不持久化，前端刷新只恢复结构化理解，可能需继续澄清；异常断网时需先刷新确认服务端状态。

### Revisit When

需要跨刷新完整对话、幂等请求或真正并发协作时，再评估历史/版本/队列，不在当前 V0 提前实现。后续最小 Planning 实现见 ADR-027。

---

## 新决策如何加入本文档

未来形成新的重要技术结论时：

新增一个 ADR：

```text
ADR-XXX｜决策名称
```

## ADR-027｜独立规划输出契约与 V0 事实边界

Status：Accepted / Implemented（Owner 本轮明确授权）。

确定性就绪后仍需用户主动点击规划；PlanningPrompt、PlanningLLMClient 与 Itinerary 独立于访谈协议，复用既有 Provider transport 和 metrics，不引入框架。用普通 Python 校验 Trip ID 与逐日日期覆盖；不把模型知识声明为实时查询或事实保证。返回固定核实说明，rationale 解释明确个人/共同偏好和当前情境的适配。

本轮不保存 Itinerary，前端仅内存展示，刷新后丢失；需要跨会话恢复时再设计持久化与版本。本轮不实现行程 refinement、工具或自动重试。

## ADR-028｜Web 本机固定主体，独立人物模型不变

Accepted / Implemented：Owner 明确本人为个人资料主体。使用单例 local_profile 外键，不复制 Person，不引入认证或账户系统。固定后保存更新原 ID；已有多人物需首次明确选择，不根据同名记录猜测、删除或合并。伙伴仍在同行人管理。

## ADR-029｜可选性别与关系标签的澄清边界

Status：Accepted / Implemented（Owner 已确认）。

Person/PersonCreate 新增可选 gender，female/male/other/prefer_not_to_say，默认 None。仅保存明确提供的数据，旧 JSON 缺字段兼容；不按性别推断兴趣、体力或步行强度，可以中性澄清需求，明确回答优先。

partner 可以在适当时机引导中性、可拒绝的约会氛围征询，不能当成偏好事实；不问私密细节、不默认安排，拒绝或信息足够时停止。接受后只记录本次明确需求，不改长期资料。中文标签简化不改变 spouse/partner/family/sibling 的内部语义。

不新增人群画像推断、优先级 Schema、固定问卷或对话历史。此决策记录现有实现，不授权新的推断机制。
