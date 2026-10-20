# 人生旅迹｜开发路线图 Roadmap

## 1. 总体开发原则

“人生旅迹”采用渐进式开发。

不追求一开始就构建完整 Agent 系统，而是按照：

> 先验证核心价值 → 再增加真实世界能力 → 再增加 Agent 能力 → 最后增加长期 Memory 和工程化能力

逐步推进。

每个阶段都应该回答一个明确问题。

只有当前阶段验证成立后，才进入下一阶段。

基础 Evaluation 从 V0 开始，并贯穿后续各阶段。V5 是扩展评估覆盖与模型优化的阶段，不是首次开始评估。

总体演进方向：

V0 个性化推荐验证
→ V1 真实世界信息
→ V2 Tool-Using Workflow
→ V3 Constraint Validation & Replanning
→ V4 Long-term Memory
→ V5 Evaluation Expansion & Model Optimization
→ V6 Production-oriented Agent System

---

## 2. V0｜验证个性化推荐

### 核心问题

首先验证：

> Person + Relationship + Trip Participants + Trip Context 是否能够让模型产生比普通旅游攻略更符合当前参与者和旅行情境的结果？

这个阶段不追求完整产品。

重点是证明“人生旅迹”的核心价值成立。

---

### 主要任务

#### 数据结构

建立最基础的结构化数据模型：

- Person
- Relationship
- Trip
- Trip Participants
- Trip Context
- Itinerary

数据暂时可以人工构造。

---

#### 个性化 Context

研究如何把：

- Person preference
- Relationship information
- Trip participants
- Trip purpose
- Temporary constraints

组合成有效的模型输入。

---

#### Structured Output

输出必须是结构化 itinerary，而不是一大段自然语言。

初步可能包括：

- Day
- Activity
- Place
- Time period
- Recommendation reason

---

#### 个性化理由

系统需要能够说明：

> 为什么这个地点适合这些用户。

而不是只输出地点名称。

---

#### 初步测试

构造少量固定 Persona 和 Trip Scenario。

例如：

##### Persona A

喜欢：

- 咖啡馆
- 城市散步
- 设计

不喜欢：

- 拥挤
- 历史建筑

##### Persona B

喜欢：

- 博物馆
- 历史
- Architecture

然后测试：

在相同目的地和旅行条件下，对比普通 Prompt 基线与个性化 Context 的结果，并检查差异是否确实来自已提供的偏好。行程不同本身不等于个性化质量更好。

---

### V0 暂时不做

- Real-world APIs
- Maps
- Weather
- Long-term Memory
- Vector Database
- Multi-Agent
- 完整前端
- 自动预订
- 复杂 Agent Framework

---

### V0 完成标准

V0 验收需要可重复的证据，不以单个示例或主观印象判定完成。

#### 固定案例与对比方法

- 固定 Persona、Relationship、Trip Participants、Trip Context 和预期行为；覆盖个人偏好变化、参与者变化、明确关系偏好变化、单次旅行目的/限制变化，以及热门地点与偏好不匹配的场景。
- 同一案例比较普通 Prompt 基线（目的地与本次旅行要求）和加入相关人物、关系信息的个性化版本；保持模型、生成参数、输出 Schema 与共同要求一致，记录 Prompt / Context 版本。
- 针对各类信息设计只改变一个因素的成对案例，检查变化方向是否符合输入。关系标签本身不作为浪漫、慢节奏或体力限制等偏好的证据。
- 每个案例按事先约定的次数重复运行，保留全部结果与失败；不挑选最好的一次作为结论。

#### 判断维度

- **结构可靠性**：统计有效 Schema 输出、无效输出、重试和最终失败；相关 Python 校验测试通过。
- **个性化与相关性**：推荐选择和理由能对应到已提供的偏好，而非仅更换名称或复述 Profile。
- **关系与参与者感知**：使用当前参与者及相关关系信息，不引入未参加的人，不凭关系标签编造共同偏好。
- **本次情境与限制**：明确的旅行目的、要求和排除项被考虑，不把临时要求描述为长期偏好。
- **推荐理由与避免盲从热门**：热门程度不替代适合度；解释有输入依据，不编造用户经历或偏好。

#### 完成判定与记录

在验收运行前固定案例版本、评分规则、重复次数及通过阈值，并由 Owner 确认；这些参数尚未确定时，不能声称 V0 已通过验收。初期可人工按统一规则评分，不要求自动评审系统。

记录各维度的结果、基线对比、失败案例，以及真实调用可获得的 model、Token 和 latency。只有在预定标准下，个性化版本呈现可重复的相关性收益，且结构可靠性与明确限制满足约定要求，并经 Owner 评审后，才判定 V0 完成。不得用平均分掩盖违反明确硬性限制的结果。

V0 不接入现实信息工具，因此本阶段验收不证明营业时间、路线、天气或现实行程可执行性；模拟或未验证信息须明确标识。

---

## 3. V1｜接入真实世界旅行信息

### 核心问题

V0 中模型可能“知道”很多地点，但无法保证信息真实、最新或可执行。

V1 开始解决：

> 如何让 itinerary 建立在真实世界数据上，而不是模型记忆上？

---

### 可能接入的信息

#### Places / POI

查询：

- 景点
- 餐厅
- 咖啡馆
- 商店
- Museums
- Parks

#### Opening Hours

确认：

- 是否营业
- 营业时间

#### Maps / Location

获得：

- 地址
- 经纬度
- 地理位置

#### Route / Transport

获得：

- 距离
- 交通方式
- Travel time

#### Weather

获得：

- 天气
- 温度
- 降雨等信息

---

### 核心原则

LLM 不应该猜：

- 距离
- 营业时间
- 路线
- 天气
- 精确交通时间

这些信息优先通过 Tool / API 获取。

---

### V1 完成标准

- itinerary 中使用的地点来自可靠数据源
- 关键现实信息可以被验证
- 模型不再主要依赖自己的知识猜测地点信息

---

## 4. V2｜Tool-Using Workflow

### 核心问题

V1 有工具之后，需要解决：

> Agent 什么时候应该调用哪个工具？

系统开始从：

> Prompt → Answer

演进为：

> Understand → Tool Call → Observe → Plan → Output

---

### 可能的 Tools

例如：

- search_places
- get_place_details
- get_opening_hours
- get_route
- get_weather

每个 Tool 应该职责单一、输入输出清晰。

---

### 当前原则

优先实现：

> Single Agent / Structured Workflow + Tools

而不是立即使用 Multi-Agent。

---

### V2 完成标准

Agent 能够根据任务：

- 判断什么时候需要查询现实信息
- 调用正确 Tool
- 使用 Tool Result 继续规划
- 避免无意义 Tool Call
- 最终产生完整 itinerary

---

## 5. V3｜Constraint Validation & Local Replanning

### 核心问题

一个看起来合理的 itinerary，不代表现实中真的能执行。

这个阶段重点解决：

> 行程是否可行？

以及：

> 用户修改局部需求后，能否只调整相关部分？

---

### Constraint Validation

可能检查：

#### 时间

- 活动是否冲突
- 行程是否过满

#### Opening Hours

- 到达时地点是否营业

#### Route

- 相邻地点是否距离过远
- 是否出现明显绕路

#### Budget

- 是否明显超过预算

#### Participants

例如：

- 长辈体力限制
- 饮食限制
- 不喜欢的活动
- Travel pace

---

### Local Replanning

例如用户说：

> 第二天下午太累了，换轻松一点。

系统应：

1. 理解影响范围
2. 保留不受影响的 itinerary
3. 重新规划相关时间段
4. 再次检查 constraints

而不是默认重新生成全部行程。

---

### V3 完成标准

- 能检测主要 itinerary 冲突
- 能解释发现了什么问题
- 能针对局部问题进行 replanning
- 不需要每次重新生成完整 itinerary

---

## 6. V4｜Long-term Memory

### 核心问题

前面的系统仍然主要依赖用户当前输入。

这个阶段开始解决：

> 如何让“人生旅迹”真正越来越了解用户？

---

### Memory 类型

#### Person Memory

记录个人长期偏好，例如：

- 喜欢什么
- 不喜欢什么
- Travel pace
- Spending style
- 历史行为
- Wishlist

---

#### Relationship Memory

记录某些人在一起旅行时形成的共同模式。

例如：

- 两个人一起时偏好慢节奏
- 某组朋友更喜欢夜生活
- 某家庭组合更重视交通便利

---

#### Trip Memory

记录某一次旅行发生过什么。

例如：

- 去过哪些地点
- 喜欢哪些推荐
- 拒绝哪些地点
- 行程做了什么修改

---

### Memory 原则

Memory 不等于：

> 把全部聊天历史重新发送给模型。

需要逐渐研究：

- Structured Memory
- Summary
- Retrieval
- Importance
- Confidence
- Correction
- Forgetting
- Preference update

---

### V4 完成标准

- 用户不需要重复提供所有长期偏好
- 系统能够正确取回相关信息
- 新反馈能够更新已有偏好
- 错误 Memory 可以被纠正
- 不相关 Memory 不应污染当前旅行规划

---

## 7. V5｜Evaluation Expansion & Model Optimization

### 核心问题

在 V0 已有固定案例、基线对比和基础回归评估的基础上，扩大数据集与评估覆盖，系统比较不同版本和模型的质量、成本与延迟。

此前各阶段也必须为新增能力补充相应评估；工具准确性、约束检查和 Memory 纠正等不能等到 V5 才首次验证。

---

### Evaluation 方向

#### Personalization

推荐是否真的反映用户偏好？

#### Relationship Awareness

多人旅行时是否真正考虑不同参与者？

#### Trip Context

本次目的和限制是否被遵守？

#### Anti-Conformity

系统是否只因为地点热门就默认推荐？

#### Constraint Satisfaction

行程是否可执行？

#### Hallucination

是否生成了错误或不存在的信息？

#### Tool Accuracy

是否正确使用 Tool Result？

#### Cost

每次规划使用多少 Token / API Cost？

#### Latency

完整任务需要多长时间？

---

### Test Dataset

逐步建立固定测试集：

- Personas
- Relationships
- Trip scenarios
- Constraints
- Expected behavior

用于 Regression Testing。

---

### Model Comparison

对比不同模型：

- 质量
- Token Usage
- Cost
- Latency

从而决定：

> 哪些任务需要强模型，哪些任务可以使用更便宜的模型。

---

### V5 完成标准

- 扩展已有固定 Evaluation Cases，覆盖前面各阶段已实现的能力与主要失败模式
- 能按统一规则重复比较系统版本，并识别质量回退
- 能在相同案例和可比条件下比较不同模型
- 能量化质量、成本和速度差异，并为模型选择提供依据

---

## 8. V6｜Production-oriented Agent Engineering

### 核心问题

前面的系统能够工作后，再开始解决：

> 如何让它稳定地长期运行？

---

### 可能加入

#### Observability

记录：

- LLM Call
- Tool Call
- Tokens
- Latency
- Errors
- Workflow

#### Reliability

逐渐加入：

- Retry
- Timeout
- Error handling
- Fallback
- Validation

#### Cost Control

例如：

- Model routing
- Context compression
- Caching
- Selective retrieval

#### API Layer

使用 FastAPI 等方式提供统一接口。

#### Persistence

存储：

- Person
- Relationship
- Trip
- Memory
- Itinerary

#### Deployment

将系统部署为可以持续使用的服务。

---

## 9. Multi-Agent｜暂不设为固定阶段

Multi-Agent 不作为当前路线中的必经阶段。

只有当项目中出现明确、长期稳定、相互独立的职责，并且单 Agent / Workflow 难以合理解决时，再考虑引入。

例如未来可能探索：

- Planner
- Constraint Checker
- Research Agent

但引入之前必须回答：

- 为什么一个 Agent 不够？
- 为什么不能用普通函数或 workflow？
- 不同 Agent 的职责是什么？
- 如何共享状态？
- 增加多少 Token 和 Latency？
- 是否真的提高系统质量？

Multi-Agent 是可能的技术选择，而不是项目目标。

---

## 10. 当前优先级

当前项目处于：

> V0 — Personalized Travel Recommendation Validation

当前第一阶段顺序：

1. 明确 Person 数据结构
2. 明确 Relationship 数据结构
3. 明确 Trip / Trip Context
4. 明确 Itinerary Output
5. 构造第一批固定测试案例，并定义预期行为与基础评分规则
6. 完成第一版 personalized itinerary generation
7. 运行普通 Prompt 基线与 personalized context 的重复对比
8. 根据基础 Evaluation 结果检查 V0 验收标准并改进

在 V0 核心价值验证之前，不提前开发后续复杂系统。

---

## 11. 路线图原则

整个项目遵循：

> 每增加一层复杂度，都必须解决一个已经真实出现的问题。

不因为某个技术流行就加入它。

不为了让 GitHub 看起来复杂而加入不必要组件。

每个重要技术选择最终都应该能够回答：

> 它解决了什么问题？

以及：

> 为什么当前阶段值得使用它？
