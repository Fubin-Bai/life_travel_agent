# 人生旅迹

> 一个长期理解“你是谁、和谁出发、为什么出发”的个性化 AI Travel Agent。

**人生旅迹**是一个正在开发中的个性化旅行 Agent 项目，探索如何结合个人偏好、人与人的关系，以及每次旅行的具体情境，生成更适合当前参与者的行程。

它希望回答：

> 对于这一次旅行中的这些人来说，什么才真正值得去？

**当前状态：V0 文档与设计准备阶段。尚未实现核心功能代码、可运行 Demo 或端到端旅行规划链路。** 下文描述产品目标与已批准设计，不代表已上线能力。

## 为什么做这个项目？

热门榜单、景点评分和“必去清单”能提供参考，但不足以描述一个人真正想要的旅行。

同一个人去东京，独自出发、与伴侣同行或带父母旅行，即使目的地和天数相同，也可能需要不同的安排。差异应来自具体参与者的偏好、需求和本次情境，而不是对关系标签的刻板推断。

人生旅迹希望为这些具体的人提供有依据、可解释的推荐。同时，本项目也是 Owner 学习 AI / Agent Engineering、积累工程经验与求职展示的个人项目，核心代码和决策必须能够被理解、修改和解释。

## 核心理念

### Person First：每个人都是独立实体

Person、Relationship 与 Trip Participation 是三个不同的概念：

- **Person**：独立的人及其个人偏好。
- **Relationship**：人与人之间的长期连接。
- **Trip Participants**：某次旅行实际参加的人。

系统不把一个人永久定义为另一个人的附属 Companion。一对夫妻可以共同旅行，也可以分别独自出发或与朋友同行。关系不等于同行。

### Relationship Awareness：区分“我喜欢”与“我们喜欢”

个人偏好不一定等于与特定的人一起旅行时的偏好。例如，一个人独自旅行时喜欢高强度探索，但与某位伴侣同行时更喜欢慢节奏。

这类差异需要来自明确提供的信息或反馈。`parent` 不自动意味着体力较弱，`partner` 也不自动意味着喜欢浪漫安排。

### Context Awareness：长期偏好与本次要求分离

一个长期喜欢城市探索的人，这次可能只想休息。系统应同时考虑两者，不能将单次旅行需求自动变成长期标签。

### Popularity ≠ Personal Relevance：热门不等于适合

知名度、评分和热度是参考信号，不能替代个人相关性。推荐可以包含经典景点，也可以跳过不匹配的热门地点；判断依据应是当前参与者及旅行情境，并能解释原因。

### Long-term Understanding：允许理解逐渐深化，也允许人改变

长期愿景是从“喜欢咖啡馆”逐渐理解到更具体的偏好，例如安静、有设计感的独立咖啡馆。系统也应允许偏好随生活阶段和旅行经验变化。

明确事实、明确偏好、具体反馈、系统推断与本次旅行情境需要分开。推断不能被当作用户已确认的事实，错误信息应能被纠正。**长期 Memory 尚未实现，不属于当前 V0 核心范围。**

## V0：验证个性化推荐

当前阶段：**V0 — Personalized Travel Recommendation Validation**。

核心假设是：结构化的 Person、Relationship、Trip Participants 和 Trip Context，能够让模型生成比普通旅游攻略更符合当前参与者和旅行情境的结果。

已批准、尚待实现的流程：

```text
Person Data + Relationship Data + Trip Participants + Trip Context
    → Context Builder
    → Prompt Builder
    → LLM Client
    → Structured Output / Itinerary
    → Basic Validation
    → Basic Evaluation
```

V0 可以使用人工构造的数据。重点是输入结构、相关上下文选择、结构化行程、推荐理由与基础评估。

当前已有产品定义、路线图、V0 设计、技术决策和协作规则文档；Schema、Context Builder、Prompt Builder、LLM Client、行程生成、测试和 Evaluation Cases 均尚未实现。最新进度以 [CURRENT_STATUS.md](docs/CURRENT_STATUS.md) 为准。

后续 V0 实现将围绕核心 Pydantic Schema、固定测试数据与评估案例，以及上述主流程逐步开展。

V0 暂不接入真实旅行 API、正式数据库、向量数据库、长期 Memory、复杂 Agent Framework、Multi-Agent、完整前端或自动预订。模拟或未经验证的现实信息需要明确标识；结构化输出本身不证明行程现实可执行。

## V0 Evaluation

Evaluation 从 V0 开始，贯穿后续阶段。目前已有评估方向与验收方法文档，尚无实际评估结果。

计划固定 Persona、Relationship、参与者、本次情境与预期行为，对比：

```text
普通 Prompt Baseline（目的地与本次旅行要求）
    vs
Personalized Context（加入相关人物与关系信息）
```

比较时保持模型、生成参数、输出 Schema 和共同要求一致，并通过单因素变化案例与重复运行，检查：

- 个性化与推荐相关性。
- 与已提供偏好的一致性。
- 对参与者、关系信息及本次情境的正确使用。
- 推荐理由是否有依据，是否盲从热门。
- 结构化输出可靠性及明确限制的遵守情况。

“两个结果不一样”不能单独证明个性化成功，也不能凭单个优秀示例断定整体提升。评分规则、重复次数和通过阈值须在验收前确定；具体方法见 [ROADMAP.md](docs/ROADMAP.md)。

## 开发路线

以下均为阶段规划，不代表已实现能力：

| 阶段 | 目标 |
| --- | --- |
| V0 | Personalized Recommendation Validation：验证个性化推荐 |
| V1 | Real-world Travel Information：接入真实旅行信息 |
| V2 | Tool-Using Workflow：使用工具的工作流 |
| V3 | Constraint Validation & Local Replanning：约束验证与局部重规划 |
| V4 | Long-term Memory：长期记忆 |
| V5 | Evaluation Expansion & Model Optimization：扩展已有评估与模型优化 |
| V6 | Production-oriented Agent Engineering：面向持续运行的工程能力 |

基础评估从 V0 开始，各阶段为新增能力补充评估。Multi-Agent 不是必经阶段，只有在普通函数、结构化工作流或 Single Agent 无法合理解决真实问题，且能证明收益时再考虑。

## 工程原则与技术选择

- **Simple First**：复杂度必须解决当前真实问题。
- **Structured First**：核心输入输出采用明确 Schema。
- **Deterministic Where Possible**：验证、查找、计算和规则检查优先由 Python 处理。
- **LLM for Semantic Decisions**：模型负责语义理解、偏好权衡、规划与推荐理由。
- **Measure Before Optimize**：从真实 API 调用开始尽量记录模型、Token 与延迟；成本可获得或可估算时注明依据，再根据质量与成本数据优化。

V0 已确认采用 Python、Pydantic、独立 LLM Client 与结构化输出，并分别使用单元测试验证程序逻辑、Evaluation 评估模型行为。这些是设计选择，尚未形成可运行实现。

具体 LLM Provider 和模型尚未选定。数据库、向量数据库、Agent Framework、前端与部署平台留到真实需求出现后再评估；V0 优先使用原生 Python 与人工数据。

## 项目文档

| 文档 | 内容 |
| --- | --- |
| [PRODUCT.md](docs/PRODUCT.md) | 产品定位、核心价值和用户体验 |
| [ROADMAP.md](docs/ROADMAP.md) | 阶段路线与 V0 验收标准 |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Current Architecture 与 Approved V0 Design |
| [DECISIONS.md](docs/DECISIONS.md) | 已确认决策、原因与取舍 |
| [CURRENT_STATUS.md](docs/CURRENT_STATUS.md) | 当前真实开发状态 |
| [AGENTS.md](AGENTS.md) | Coding Agent 的协作规则 |

当前尚无安装、运行或测试命令；相关说明将在可运行实现落地后补充。

## English Summary

**人生旅迹 (Life Travel Trace)** is a personalized AI travel agent project under development. Its long-term goal is to understand who people are, whom they travel with, and why each trip happens.

The project asks: **What is actually worth doing for these specific people on this specific trip?**

The approved V0 design combines person profiles, relationships, trip participants, and trip context to generate a structured itinerary. People are independent entities; relationships do not imply participation or preferences. Long-term preferences, temporary requirements, and inferred information remain distinct. Popularity is a signal, not a substitute for personal relevance.

The project is currently in **V0 — Personalized Travel Recommendation Validation**, at the documentation and design stage. No core implementation, runnable demo, or end-to-end travel agent exists yet. Real-world travel tools and long-term memory are future work.

V0 will compare personalized context against a generic travel-planning baseline using fixed cases, controlled comparisons, repeated runs, and explicit evaluation criteria. Evaluation begins in V0; complexity is introduced only when a real problem justifies it.
