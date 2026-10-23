# V0 固定输入

所有人物与偏好均为虚构数据，不包含真实用户信息，不代表真实景点或旅行建议。固定数据唯一来源为 src/life_journey/sample_data.py，供开发 CLI 和测试共用；tests/fixtures/v0.py 保留原导入兼容。它不是生产用户数据或持久化服务。

## 加载方式

pytest 测试中使用：

```python
from fixtures import load_persons, load_relationships, load_trips

persons = load_persons()
relationships = load_relationships()
trips = load_trips()
trip = trips["trip_tokyo_alex_bella"]
```

三个函数分别返回以固定 ID 为键的字典。每次调用重新构造并校验模型，不缓存可变对象，不调用 create_*，不使用随机 UUID。当前 Context Builder、访谈/规划测试、CLI 和 Evaluation 已复用这些输入；本模块只负责数据，评分器另见 src/life_journey/evaluation。

## 人物与关系

- Alex：独立咖啡馆、设计、城市散步；不喜欢拥挤与大型主题乐园；个人节奏快。
- Bella：博物馆、历史、建筑；个人节奏适中。
- Casey：自然、甜品、轻松体验；个人节奏慢。
- Alex—Bella：friend，共同偏好为设计展、历史街区，共同节奏适中。
- Alex—Casey：friend，共同偏好为安静公园、甜品，共同节奏慢。

两个关系使用相同标签，明确共同偏好仍不同，避免将标签当作偏好来源。Alex / Casey 的 MBTI 为模拟自述，偏好独立填写，不能用人格类型覆盖明确输入。

## 场景

所有旅行：东京，2026-11-10 至 2026-11-12，预算 2000–3000 AUD。预算仅作固定规划输入，不表示真实价格已验证，不引入汇率差异。

| Case | Trip ID | 固定条件与变化 | 未来检查方向 |
| --- | --- | --- | --- |
| A | trip_tokyo_alex_bella / trip_tokyo_alex_casey | 除场景 ID 外，仅 participant_ids 改变；Context 均为空 | 更换同行人后，是否考虑当前人物及明确关系偏好 |
| B | trip_tokyo_alex_bella_slow / trip_tokyo_alex_bella_fast | 除场景 ID 外，仅 context.preferred_pace 为 slow / fast；其他 Context 也完全相同 | 本次节奏变化是否被合理考虑，且不回写长期偏好 |
| C | trip_tokyo_alex_personal_relevance | Alex 独自旅行；明确咖啡/设计兴趣，排除大型主题乐园 | 是否因热门而忽略明确兴趣、不喜欢项或排除项 |

Case A 的目标变量是参与者组合；对应人物与相关关系信息会随选择变化，不能据此独立归因某个关系字段的效果。Case B 才是节奏字段的严格单因素对比。两个 Case 的 trip_id 差异仅用于追踪案例。

Case C 不提供真实 POI、排名或“正确行程”。这些是固定输入，不能声称已验证推荐质量、抗热门偏差或现实可执行性。它也不是已经定义评分规则的成对基线实验。

V0 收尾：正式 Web 数据来自独立 SQLite，不自动导入本模块。新可选 gender 在现有样本未提供时为 None；不要按 MBTI、性别或关系标签补造偏好。已有场景可构建上下文，不等于已完成行程个性化对照实验。
