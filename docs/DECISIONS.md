# 人生旅迹｜技术决策记录 Decisions

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

Accepted

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

## 新决策如何加入本文档

未来形成新的重要技术结论时：

新增一个 ADR：

```text
ADR-XXX｜决策名称
```
