# V0 Interview Evaluation

本目录的基准报告与普通单元测试分开。固定六例定义见 `src/life_journey/evaluation/cases.py`；评分器与手动入口见 `src/life_journey/evaluation/interview.py`。

## 运行

项目根目录执行（沿用现有环境变量 `DEEPSEEK_API_KEY`，可选 `DEEPSEEK_MODEL`，不自动加载 .env）：

```bash
PYTHONPATH=src .venv/bin/python -m life_journey.evaluation.interview --output evaluations/interview_v0_latest.json
```

每例独立初始 context/state，每例一次调用，总共六次真实调用；失败计入分母，无重试。输出每例 PASS/FAIL、失败原因、独立 forbidden 状态和汇总通过率；退出码 0 全过、1 至少一例失败、2 配置失败。不提供真实 Key，不将期望值发给模型。

`interview_v0_baseline.json` 是 2026-10-22 首次真实运行的固定基线，不建议用后续运行覆盖；新结果写入不同文件。报告包含实际结构输出、回复、状态、期望、失败原因、模型/token/latency 与 system prompt 哈希；仅保存固定虚构 benchmark 数据，不记录真实用户聊天。

## 评分边界

- 使用 Owner 指定的精确标准值；中文同义表达不会自动翻译成英文后放行。列表同时比较顺序与内容，禁止保留撤销旧值。不比较整段 assistant_message 是否与模板一致。
- Case 2/3/6 要求本轮明确输出对应字段并 confirmed，不能因为初始默认 [] 偶然通过。
- Case 5 使用 Alex+Bella partner + 自述 MBTI，要求未表达的活动与节奏保持未知，不新增这些主题确认。
- Case 6 按“只剩 excluded unknown”建立状态：其余五主题已确认；目的、节奏、必去内容按指定值保存，建议活动为空。系统 ready、消息收束分别评分。
- forbidden 检查只针对 Case 1 的 nature/spa 和 Case 5 的浪漫、拍照、慢节奏、MBTI 等中英文词。检查 context_update 和 assistant_message；其他 case 未配置禁用词，不代表已证明不存在任何越界推断。
- 词汇命中只表示风险：否定或澄清可能误报，同义词可能漏报；必须结合原文复核。自然收束检查要求没有常见追问形式并包含阶段结束信号，也是启发式。没有额外 LLM judge，不宣称覆盖全部语义质量。
- pytest 仅验证评分器、场景隔离与统计逻辑，使用 fake client，不运行真实 benchmark。单次六例结果不是模型整体稳定性或旅行现实可行性的证明。

## 首次实际结果

首次基线当时使用 deepseek-flash，报告为 interview_v0_baseline.json：3/6（50%）。这是历史结果，不代表最新 Prompt：

| Case | 结果 | 原因/观察 |
| --- | --- | --- |
| 1 放松慢节奏 | FAIL | pace=slow；purpose=放松休息，与 relaxation 不精确相等；禁用词未命中 |
| 2 必去/排除 | FAIL | 樱花观赏 / 迪士尼，与指定英文标准值不一致；两个 topic 均确认 |
| 3 明确没有 | PASS | 两个 [] 显式输出且确认 |
| 4 列表替换 | FAIL | 已完整替换为艺术展 / 建筑、未 merge；与英文标准值不一致 |
| 5 不按标签推断 | PASS | 空 update、无新增确认；禁用词未命中 |
| 6 最后确认并收束 | PASS | excluded=[] 已确认，系统 ready=true，回复自然结束 |

优先明确/调整 Prompt 的结构字段语言与标准化约定，再对同一 benchmark 回归；无需先修改当前支持自由字符串的 Schema 或可靠应用更新的 application logic。该次基线运行未修改 Prompt；后续已按用户需求更新 Prompt，并保留全部回归报告，未降低字段评分标准。

### 2026-10-23 对话策略回归

加 --include-dialogue 运行原六例 + 整句理解/避免重复确认两例。v2/v3/v4 保留各次真实结果，当时 v4 为 7/8；case_2 失败于中文活动标签与固定英文目标不一致，forbidden 检查均通过。两条新增对话用例通过，但透明词汇规则不能代替人工自然性评估。v3 的自然收束文案被旧收束关键词误判，已补充“了解得差不多/进入下一步”信号与单测；不改变字段精确比较规则。运行真实 benchmark 会产生调用费用；pytest 不访问网络。

## V0 收尾：当前报告与缺口（2026-10-23）

默认仍为六例；加 `--include-dialogue` 为八例，增加整句理解与避免重复确认。每例一次真实调用，无自动重试；普通 pytest 不访问网络。

| 报告 | 结果 | 主要观察 |
| --- | --- | --- |
| interview_v0_baseline.json | 3/6 | 早期中文标签与指定英文标准值差异 |
| interview_v0_natural_v2.json | 7/8 | 活动标签/扩大排除范围问题 |
| interview_v0_natural_v3.json | 5/8 | 标签、模糊节奏推断；自然收束被旧启发式误报 |
| interview_v0_natural_v4.json | 7/8 | 新收束启发式与模糊节奏规则后，case_2仍标签不一致 |
| interview_v0_partner_boundaries.json | 7/8 | case_2把Disneyland扩大为theme parks |
| interview_v0_gender_context.json | 7/8 | 最新保存报告；case_2中文标签与英文目标不一致 |

不同报告可能包含 Prompt/评分规则变化，不能直接把通过率差异当成严格受控提升。全部结果保留，不选择最好一次；现有八例不是行程质量 Evaluation。伴侣适度征询允许中性提问，旧禁用词扫描可能将澄清也标为风险，需人工复核；性别不同输入的成对行为尚未覆盖。

当前仍缺：itinerary evaluator、普通规划 Prompt 与个性化版本的对照、多次重复与人工相关性/约束评分、真实事实与可行性验证。一次虚构规划3天9活动 smoke只证明请求/结构/日期可贯通，未形成可提交的行程质量 benchmark 报告。V0 功能收尾不等于完成这些研究验收。

## V1第一阶段验证边界

本轮不改Interview，现有六/八例不覆盖地图召回或工具辅助行程，不重复运行无关真实访谈。新增test_amap_tools/test_planning_observation使用MockTransport/fake验证大陆范围、规范化、失败、凭据日志、调用上限、API门槛、候选引用与V0兼容；普通pytest完全离线。真实高德smoke未配置Key而明确失败，不能声称真实查询或推荐质量已验证。后续需建立大陆工具结果与行程引用/相关性固定案例；操作见docs/V1_TOOLS.md。

V1多类召回本轮新增离线tests/test_candidate_retrieval.py，覆盖有限别名/类别优先、来源、排除、去重、候选/路线预算和fast冲突；完整761测试通过。既有Interview真实benchmark不是检索或Planning评估，未重复跑无关访谈。扩展候选的真实覆盖率、多样性/重复率与节奏遵循尚需固定大陆场景和真实LLM验证，不从fake回归推断推荐质量提升。

V1.2营业时间新增tests/test_opening_hours.py：固定离线测试检查周规则、闭店、unknown、未来日期与API返回防伪，完整800通过。现有Interview benchmark不覆盖本功能；尚无真实营业文本覆盖率/LLM营业遵循专项报告，不把fake通过视为未来营业事实保证。

## V1收尾验证范围

V1已基本完成，但本目录仍是Interview质量benchmark，不是工具召回或Itinerary质量评分器。真实驾车/步行与Web4天行程成功只说明功能闭环，852项离线测试验证协议与规则；独立真实transit、重复失败率、跨场景召回/个性化对照仍待补证据。V2尚未开始，不因收尾新增评分器或自动工具选择。
