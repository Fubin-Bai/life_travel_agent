# V4｜长期记忆与RAG

当前运行控制补充：预算、运行计数/缓存、hooks与trace已收口到[Agent Harness](AGENT_HARNESS.md)。本页业务契约与模式边界保留；Graph State不再保存这些runtime控制数据。
状态：Implemented local prototype，2026-10-26。新增`memory`模式，保留v0/amap/agent及原Interview行为；没有Multi-Agent、生产鉴权或复杂基础设施。

## 数据与写入

Memory区分person、relationship、trip；个人偏好不变成关系偏好，本次TripContext不自动写成长期记忆。

`MemoryCandidate`字段：memory_type、person_id、participant_ids、可选relationship_id/trip_id/destination、content(最多500字)、structured_tags、source_type(explicit/inferred/confirmed)、confidence、source_reference、stable、observation_count。

`Memory`再包含memory_id、created_at、updated_at、last_confirmed_at、active、superseded_by、embedding_model、embedding_dimensions、vector_id。SQLite独立memories表存结构化JSON与JSON数值向量，按person_id/active/updated_at建立索引；不复制人物资料或原始聊天。

```text
反馈或显式输入 → MemoryCandidate → 稳定性/临时语句过滤
→ Embedding验证 → 同事务去重/冲突覆盖 → SQLite
```

抽取器目前是有限显式规则：句中有“一直/长期/以后/通常/每次/平时/最近更喜欢”等稳定标记，且有偏好/习惯语义；含“今天/本次/这顿/天气/临时”等过滤。只保留最多8条，不保存整段反馈。源文本本身不会因模型推断变成confirmed。inferred至少两次观察才允许存储，召回后也永远是软参考。

重复正文/同scope复用ID；结构化pace及有限活动类别相反偏好由新的explicit/confirmed覆盖，旧记录inactive并记录superseded_by。inferred不能覆盖已有明确事实。跨人物/组合/原旅行不互相覆盖。当前Trip永远优先；本次明确pace冲突的旧pace记忆直接不进入Prompt。

支持通用candidate写入接口，但Web自动采集入口仅Feedback；Interview/Trip不会未经确认全量抽取或自动学习。任意自然语言矛盾、跨句指代和多次行为的自动聚合尚未实现。rating可接收但不参与长期记忆评分。

## Feedback API

`POST /api/trips/{trip_id}/feedback`

```json
{"feedback":"我一直喜欢安静的咖啡馆，以后旅行也想保留","rating":5,"memory_type":"person"}
```

可选person_id明确主体；缺省用本机profile，若只有一个参与者可用该人，多人且无profile则必须指定。主体必须参与本次旅行。relationship需显式relationship_id并与参与组合一致；trip记忆保留原旅行与目的地范围。

返回stored_memory_ids、confirmed_memory_ids及未写入说明。后续明确确认可提交`confirm_memory_ids`，只升级已存在且在本次scope的active记忆，写确认时间；重复使用/检索不会自动升级confirmed。无关ID拒绝422。前端仅提供文本反馈入口，复杂确认管理界面未做；API可完成确认。

## Embedding与向量方案

使用SQLite + 应用层精确余弦，是本地小规模向量方案；没有FAISS/Chroma服务或新依赖。避免另起基础设施，代价是没有ANN索引、大规模吞吐或自动重嵌入。

独立`EmbeddingProvider` Protocol：model标识、embed(texts)→vectors。生产`CompatibleEmbeddingProvider`调用显式配置的OpenAI-compatible embeddings完整HTTPS端点，不绑定服务商、不假设DeepSeek有Embedding API。验证返回index、数量、维数、有限数与非零范数，超时15秒、无重试/跳转、不记录Key。模型版本不同不混用向量；配置model应使用能区分向量空间的稳定版本标识。

根目录`.env`增加：

```dotenv
LIFE_JOURNEY_PLANNING_MODE=memory
LIFE_JOURNEY_EMBEDDING_URL=https://embedding.example.com/v1/embeddings
LIFE_JOURNEY_EMBEDDING_MODEL=your-embedding-model-version
LIFE_JOURNEY_EMBEDDING_KEY=your-embedding-key
```

上面全部是占位，不是可用真实服务。仍需原AMAP_WEB_SERVICE_KEY和DEEPSEEK_API_KEY。系统环境优先，修改后重启；Key不入前端、repo或日志。未配置Embedding返回明确配置错误，不降级为假语义向量。测试及固定评估只注入fake。

## Retrieval与排序

```text
Trip参与者/相关关系/目的地/目的/本次偏好与明确Profile兴趣
→ query → SQL人物scope → 组合与目的地过滤
→ 最多200条相关active候选 → query Embedding → cosine
→ similarity≥0.15 → rerank → TopK=5 → Agent/Planner
```

个人只给参与者；关系需要相同relationship_id、成员集合及双方参与；Trip记忆只有相同参与组合、相同目的地可用。无关scope在Embedding查询前过滤，无匹配时不调用queryEmbedding。语义打分前也排除不同模型向量和本次pace冲突。

排序为0.60×cosine + 来源权重(confirmed .24 / explicit .14 / inferred 0) + .08×confidence + .05×recency + 关系scope相关性.03。recency=1/(1+age_days/90)。同相似度时confirmed优于inferred；是可解释加权，不是学习排序。TopK默认5，调用接口允许1–10；有界Prompt，绝不直接发送全库。

State仅新增memory_query、retrieved_memories、retrieval_scores、memory_provenance。Provider和SQLite连接不入State。Agent和Planner均明确当前Trip explicit > confirmed > explicit > inferred；Validator不把记忆当hard constraint。

PlanningResponse.memory_provenance是本次召回并提供给模型的ID/type/source_type/score，**不证明每项rationale实际采用了它**。日志/trace不记录记忆全文、完整查询、Prompt、Key或隐藏推理。

## 图与模式

```text
START → retrieve_memory → agent ⇄ tools → finalize_draft → validate
                                                         ├─ valid/soft only → complete → END
                                                         └─ hard → replan(最多2轮) → validate → complete/未解决
```

v0：模型知识兼容。amap：V1固定工具流程。agent：V2原生工具决策，开LIFE_JOURNEY_VALIDATION=1可启用V3。memory：V2 + RAG + V3始终启用。无自动跨模式fallback。

## 验证与真实smoke

```bash
.venv/bin/pytest -q
PYTHONPATH=src .venv/bin/python -m life_journey.evaluation.memory_rag
PYTHONPATH=src .venv/bin/python -m life_journey.evaluation.version_smoke --stage v4 --city 北京
```

离线覆盖稳定写入/临时拒绝/去重/覆盖/确认、同义假向量召回/TopK/排序、人物/关系/Trip隔离、当前Trip优先、inferred软参考、API反馈→第二旅行→图与Planner输入、真实Embedding协议的MockTransport及失败原子性。

4个固定对照场景使用fake Embedding和脚本Planner，偏好匹配25%→100%、召回相关性100%、无关个性化0%；固定脚本草稿经Validator检查硬冲突0%。**这些是信息流夹具指标，不能作为真实LLM个性化收益或实际语义模型召回质量的证据。**

真实smoke使用临时SQLite、两次虚构旅行，第一旅feedback写入真实Embedding，第二旅真实Agent/高德/DeepSeek接收记忆，报告无关人物泄漏检查及行程。实际采用程度仍需人工检查rationale；该独立临时库smoke不等于本次Web手动测试；2026-10-27真实BAAI/bge-m3向量调用与Web长期偏好写入已通过，Owner确认RAG检索完成。完整检索响应尚未归档，详见CURRENT_STATUS。

## 当前限制与可讲述内容

可重点解释scope先于semantic retrieval、显式与推断来源分离、当前需求优先、覆盖与去重、RAG不等于全聊天拼接、Graph有界修复、可替换Provider和离线测试。

仍是prototype：有限抽取/矛盾规则、200条检索窗口/应用层余弦、没有真实Embedding质量基线、没有跨句语义记忆更新、自动行为归因、遗忘管理UI、生产鉴权、持久化图恢复或大规模向量索引。不要描述为生产推荐系统。

## 当前本地服务配置（2026-10-27）

长期记忆与RAG检索已实现。当前选用硅基流动BAAI/bge-m3：完整端点为https://api.siliconflow.cn/v1/embeddings，实测每条1024维。DeepSeek对话接口保持原样，不迁移到第三方。向量模型是可配置依赖，变更模型时需重新生成相应记忆向量；相同维度不代表相同向量空间。配置与手动演示见[LOCAL_DEMO](LOCAL_DEMO.md)。
