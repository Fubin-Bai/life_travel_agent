# 人生旅迹｜系统架构 Architecture

## 1. 文档目的

本文档描述“人生旅迹”当前已经确认的技术架构与系统边界。

它主要回答：

- 当前系统由哪些部分组成
- 各部分分别负责什么
- 数据如何在系统中流动
- 哪些任务应该由 LLM 完成
- 哪些任务应该由普通程序完成
- 当前 V0 有意不实现哪些能力

本文档严格区分当前已存在的架构与已经批准、尚待实现的 V0 设计。设计获批不代表功能已经实现；未来远期设计不属于 Current Architecture。

未来功能规划请参考：

`ROADMAP.md`

产品定义请参考：

`PRODUCT.md`

重要技术决策及其原因请参考：

`DECISIONS.md`

---

## 2. Current Architecture｜当前真实架构

当前项目处于 V0 — Personalized Travel Recommendation Validation 的文档准备阶段。

目前可确认存在：

- `AGENTS.md` 与 `docs/`：协作规则、产品、路线图、架构、决策和进度文档。
- `README.md`：项目介绍、阶段边界、评估概要与文档导航。
- `src/` 与 `tests/`：空目录。

尚无核心功能代码或可运行的端到端旅行规划链路。Schema、Context Builder、Prompt Builder、LLM Client、行程生成、Validation 和 Evaluation 均尚未实现；不能将下一节的流程描述为当前运行能力。

具体进度由 `CURRENT_STATUS.md` 维护；本节仅在实际实现发生变化时同步更新。

---

## 3. Approved V0 Design｜已批准的 V0 设计

本节记录已确认、准备实现的设计，不代表代码已存在。实现后，仅将已真实落地的部分同步到 Current Architecture，并说明验证情况；未实现部分继续保留设计状态。

V0 只验证一个核心假设：

> 结构化的 Person、Relationship、Trip Participants 和 Trip Context，能否帮助 LLM 生成明显更个性化的旅行行程。

因此 V0 不追求完整的 Travel Agent。

已批准的 V0 流程为：

```text
Person Data + Relationship Data + Trip Participants + Trip Context
    → Context Builder
    → Prompt Builder
    → LLM Client
    → Structured Output / Itinerary
    → Basic Validation
    → Basic Evaluation
```

上述流程与 `AGENTS.md` 中的 V0 约定一致。真实世界工具、长期 Memory 等后续能力不属于当前架构或本节的 V0 实现范围；其阶段安排以 `ROADMAP.md` 为准。
