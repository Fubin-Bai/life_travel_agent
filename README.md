# 人生旅迹

一个结合“我是谁、和谁出发、这次想要什么”的个性化 AI 旅行原型。

**当前状态：V0/V1 保留，V2 LangGraph、V3 有限约束修复、V4 Memory/RAG 本地原型已实现（更新至2026-10-27）；验证结果与限制见 CURRENT_STATUS。** 已可在 Web 完成人物资料、同行关系、旅行创建、真实 AI 访谈和结构化行程生成。推荐质量仍有已知缺口；本次收尾不代表已证明个性化显著优于普通攻略，也不是生产发布。

## 已实现的体验

1. **我的资料**：固定本机主体，保存更新同一个 Person；姓名、可选性别/MBTI、兴趣、不喜欢、食物偏好和旅行节奏。
2. **同行人**：新增或编辑独立人物，并单独保存与本人的关系、共同旅行偏好及共同节奏。
3. **新建旅行**：目的地、起止日期、预算与参与者，保存到本地 SQLite。
4. **行程访谈**：围绕本次需求自然交谈；一条用户消息对应一次模型调用、一条完整 AI 回复，逐步更新本次情境和确认状态。
5. **开始规划**：达到系统最低门槛后手动点击，展示按日组织的活动和“为什么适合你”。

人物/关系/旅行/访谈状态会保存；**聊天记录和生成行程仅在当前页面内存中，刷新后不恢复**。V0 行程基于模型知识，不保证地点、营业时间、交通、价格或季节性信息实时准确，出行前需要核实。

## 本地启动

需要 Python 3.11+ 与可运行当前 Vite 的 Node.js/npm。项目目录下首次准备 Python 环境：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
```

终端 A（项目根目录）启动后端：

```bash
.venv/bin/python -m uvicorn life_journey.api:app --app-dir src --host 127.0.0.1 --port 8000
```

终端 B 启动前端：

```bash
cd frontend
npm ci  # 首次安装或依赖锁文件变化时执行
npm run dev -- --strictPort
```

打开 [本地前端](http://127.0.0.1:5173/)。开发代理把 `/api` 转发到 8000，后端仅允许本地 5173 的 CORS。API 文档为 [本地 Swagger](http://127.0.0.1:8000/docs)。这些是本地开发方式，尚无部署配置。

人物/旅行保存不需要模型 Key；真实访谈、规划需在根目录 `.env` 或启动终端环境中配置 `DEEPSEEK_API_KEY`。可选 `DEEPSEEK_MODEL`，当前代码默认 `deepseek-flash`。FastAPI、CLI、smoke自动读取根目录 `.env`（系统环境优先），`.env.example` 仅作配置说明，不把 Key 放进前端或提交 Git。

默认数据库为 `.local/life_journey.sqlite3`，可用 `LIFE_JOURNEY_DB` 指定其他路径；数据库及辅助文件已忽略。空库先创建我的资料；已有多个人物但未绑定主体时，首次选择自己的资料并保存。之后主体固定，不因刷新、重试或添加伙伴改变。没有登录或用户隔离。

## 数据流和边界

```text
React → FastAPI → application/domain → SQLite
                            ↓
Trip + relevant Persons/Relationships → TravelContext
                            ↓
Interview Prompt → LLM → validated update → TripContext + InterviewState
                            ↓
deterministic ready → 用户点击 → Planning Prompt → LLM → Itinerary → Web
```

- Person、Relationship、Trip participants 分开；关系不自动增加参与者，个人偏好和共同偏好不合并。
- Create 输入不带自身 ID；应用生成带 `person_` / `relationship_` / `trip_` 前缀的 UUID4。
- Trip Setup 为目的地、日期、预算和参与者；TripContext 是本次访谈形成的结构化理解，不回写长期 Profile。
- 不根据性别、MBTI 或关系标签认定兴趣/体力；伴侣可被适度征询约会氛围，只有明确接受才记录。
- Popularity ≠ Personal Relevance；推荐理由应来自明确偏好与本次情境。
- LLM ready 只是建议；系统重算 readiness，未通过时 Planning API 返回 409 且不调用模型。

## 验证与已知限制

最新功能验证数量见[当前状态](docs/CURRENT_STATUS.md)；前端 TypeScript/Vite build 通过。普通测试离线，不调用 DeepSeek：

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m pip check
cd frontend
npm run build
```

真实访谈 benchmark 与 pytest 分开，运行会产生模型调用费用：

```bash
PYTHONPATH=src .venv/bin/python -m life_journey.evaluation.interview --include-dialogue --output evaluations/interview_v0_latest.json
```

最新已保存报告为 `evaluations/interview_v0_gender_context.json`，7/8（87.5%）；失败例仍有中英文活动标签不一致，历史运行还出现过排除范围扩大。评分含词汇启发式，不能证明不存在语义推断。真实规划曾以虚构输入通过 3 天/9 活动的结构与日期校验，不代表推荐事实或质量已充分验证。详见 [Evaluation](evaluations/README.md)。

V0 兼容模式仍不调用地图；V1 可启用高德地点/驾车工具，详见下节。未实现：价格查询、完整可执行性和费用验证、行程质量对比评分、行程持久化/修改、聊天历史持久化、登录、部署、Multi-Agent。当前没有删除/主体换绑/通用 Trip 修改 UI 或接口。常规 Person/Relationship 更新是完整替换，不是 PATCH；预算尚未明确人均/全组等口径。

## 项目结构与文档

| 位置 | 职责 |
| --- | --- |
| `src/life_journey/schemas/` | 用户输入、内部领域、访谈、规划契约 |
| `src/life_journey/application/` | 创建、上下文选择、访谈应用与编排、规划 |
| `src/life_journey/llm/` | Provider-independent Protocol 与 DeepSeek transport |
| `src/life_journey/api.py` / `storage.py` | 本地 FastAPI 与 SQLite |
| `frontend/` | React/Vite/TypeScript，本地照片与暗色视觉 |
| `tests/` / `sample_data.py` | 离线测试与固定虚构输入 |
| `evaluations/` | 手动真实访谈 benchmark 与报告 |

[产品](docs/PRODUCT.md) · [当前状态](docs/CURRENT_STATUS.md) · [架构/API](docs/ARCHITECTURE.md) · [路线图](docs/ROADMAP.md) · [决策](docs/DECISIONS.md) · [协作规则](AGENTS.md) · [前端](frontend/README.md)

开发 CLI：`PYTHONPATH=src .venv/bin/python -m life_journey.cli --debug`。使用虚构 Alex+Bella 场景，内存多轮访谈，`/quit` 或 `/exit` 退出；系统就绪后结束，CLI 不生成行程、不连接正式人物库。

## V1：高德真实数据辅助规划

`LIFE_JOURNEY_PLANNING_MODE=amap` 启用中国大陆单城市模式。Python 固定执行城市确认、有限 POI 检索、营业周规则与游客路线查询，再将规范化 Observation 提供给原 Planning；不是 LLM tool calling。默认 `v0` 保留模型知识模式，V1 失败不偷偷回退 V0。

根目录 `.env` 使用这些变量（实际 Key 仅填本地文件）：

```dotenv
DEEPSEEK_API_KEY=your_deepseek_api_key_here
AMAP_WEB_SERVICE_KEY=your_amap_web_service_key_here
LIFE_JOURNEY_PLANNING_MODE=amap
```

`.env` 已 gitignored；不要把 Key 写到前端或日志。系统同名变量优先，修改 `.env` 后需停止并重启后端。若终端残留旧值，在出现 shell 提示符后执行，再启动后端：

```bash
unset DEEPSEEK_API_KEY AMAP_WEB_SERVICE_KEY LIFE_JOURNEY_PLANNING_MODE
```

若每次新开终端旧值都会回来，应检查 `~/.zshrc`、`~/.zprofile` 或编辑器终端配置中的旧设置；只移除对应变量，不删除项目 `.env`。避免用 echo 打印真实 Key。

候选检索最多10次、每词2项、12个去重候选，保留命中词及明确需求来源。路线最多6个有向组合/12次请求，1500米粗距内先步行、其余先公交；驾车保留作补充直接工具。总高德请求上限23次，无隐藏重试。单条路线失败记 unknown，城市/POI失败明确停止。

营业字段仅解析保守周规则，closed 安排拒绝、unknown 待核实；后端控制营业标签与连续活动路线引用。UI显示来源和营业核实说明；完整交通 Observation/route_note 在 API 返回，未新增交通面板。

真实高德 smoke（不调用 LLM / SQLite；每条最多4次地图请求）：

```bash
PYTHONPATH=src .venv/bin/python -m life_journey.tools.smoke --city 北京 --origin 故宫博物院 --destination 景山公园 --mode walking
PYTHONPATH=src .venv/bin/python -m life_journey.tools.smoke --city 北京 --origin 故宫博物院 --destination 景山公园 --mode transit
```

`--mode driving` 保留，默认 walking。真实驾车、步行和北京4天 Web 规划已有成功记录；独立真实 transit 验收、重复成功率与推荐质量尚待补证据。最近完整离线测试852项通过，1项既有弃用提示。POI存在不等于未来营业或活动必然可行，路线不是未来班次/交通保证；V1兼容路径没有价格、天气、酒店、航班、Memory 或自动 Replanning；后续V3/V4见下节。

详见 [当前状态](docs/CURRENT_STATUS.md) 与 [V1工具契约](docs/V1_TOOLS.md)。V1 功能收尾不等于推荐质量已完成验收；V2为另行授权的新模式，V1仍保留原行为。

## English summary

Life Journey is a local personalized travel prototype with persistent profiles, relationships, trips and interview state. V1 now adds bounded Amap POI retrieval, conservative opening-hours checks and walking/transit route observations to a deterministic Python planning workflow. A real four-day Beijing itinerary has been displayed through the Web flow. V1 is closing; V2 is now available as an opt-in LangGraph tool-selection mode. Future operating hours, transit schedules, itinerary quality and repeated success rates are not guaranteed. Chat history and generated itineraries are not persisted.

## V2：LangGraph单Agent（可选模式）

根目录.env设置`LIFE_JOURNEY_PLANNING_MODE=agent`并重启后端，仍调用原`POST /api/trips/{trip_id}/planning`。`v0`保留模型知识模式，`amap`保留V1固定Python检索；三种模式显式切换，不自动fallback。API顶层仍是itinerary/notice/observation/metrics，前端无需修改。

V2由LangGraph编排`agent → tools → agent → finalize`：DeepSeek原生function calling决定搜索词、已查候选之间的路线模式和何时停止；Python控制参数/大陆同城范围/预算/去重，最终复用V1 Planning与全部事实守卫。LangGraph不替代领域模型、高德适配器、SQLite或Pydantic。此V2兼容路径不包含V3/Memory；后续V3/V4按显式模式启用，仍无多Agent、Streaming或Checkpoint。

新增直接依赖langgraph（当前验证版本1.2.17），安装方式仍为`.venv/bin/python -m pip install -e ".[dev]"`；其传递依赖包括langchain-core/langsmith，但不使用LangChain高层Agent，也不自动开启LangSmith上传。默认最多12次Tool尝试、6次搜索/6次路线、每路线模式3次、12候选、8次模型决策；连续重复2次强制停止，recursion_limit=22。详见[V2说明](docs/V2_AGENT.md)。

固定虚构输入的真实smoke（会消耗高德与DeepSeek配额，不访问SQLite）：

```bash
PYTHONPATH=src .venv/bin/python -m life_journey.evaluation.agent_smoke --city 北京 --max-tool-calls 4
```

输出脱敏行动顺序、状态、预算/停止原因与最终行程。错误或无证据不会伪造行程；最终模型违反既有营业/路线/节奏守卫仍可能失败，不自动重新规划。Agent指标在API `?debug=true`的metrics.agent_run JSON字符串中；默认不返回指标。

## V3 / V4 面试原型

V1固定工具→V2自主取证→V3确定性校验/最多两轮局部修复→V4按人物/关系/旅行隔离的Memory RAG。保留旧模式，不自动跨模式回退。`agent`设置`LIFE_JOURNEY_VALIDATION=1`启用V3；`memory`始终包含RAG及V3。Memory仅参考，不覆盖当前Trip明确需求；未解决约束返回带警示的草稿。

`POST /api/trips/{trip_id}/feedback`仅保存明确长期偏好，前端有最小反馈表单；临时反馈不写长期记忆。使用SQLite存向量，无新增V3/V4依赖。memory需在根目录.env另配`LIFE_JOURNEY_EMBEDDING_URL`、`LIFE_JOURNEY_EMBEDDING_MODEL`、`LIFE_JOURNEY_EMBEDDING_KEY`，端点采用兼容embeddings协议；`.env.example`只有占位。没有Embedding配置时明确报错，不生成假向量。

```bash
.venv/bin/pytest -q
PYTHONPATH=src .venv/bin/python -m life_journey.evaluation.constraints
PYTHONPATH=src .venv/bin/python -m life_journey.evaluation.memory_rag
PYTHONPATH=src .venv/bin/python -m life_journey.evaluation.version_smoke --stage v3 --case closed --city 北京
PYTHONPATH=src .venv/bin/python -m life_journey.evaluation.version_smoke --stage v4 --city 北京
```

普通pytest完全离线。固定评估用脚本补丁/fake向量，不代表真实模型质量；独立V3/V4 smoke入口不等于已运行验收；2026-10-27真实Embedding和Web长期偏好写入通过，Owner确认RAG检索完成，详见当前状态。完整Schema、预算、数据流与边界见[V3](docs/V3_CONSTRAINTS.md)、[V4](docs/V4_MEMORY.md)、[当前状态](docs/CURRENT_STATUS.md)。

## 轻量 Agent Harness（V4工程化收口）

在LangGraph之上增加轻量runtime harness，用于统一策略、预算、hooks、trace、错误处理与behavioral evaluation。**LangGraph负责orchestration，Harness负责runtime control**；原图与领域守卫保留，不进入V5。

agent/memory自动使用Harness；v0/amap不受影响。默认Planning响应不变，`?debug=true`查看脱敏summary/trace。没有新依赖、外部监控或前端改版。

```bash
PYTHONPATH=src .venv/bin/python -m life_journey.evaluation.harness_smoke
PYTHONPATH=src .venv/bin/python -m life_journey.evaluation.harness_behavior --output evaluations/harness_behavior_report.json
```

两者均默认离线，使用真实LangGraph和fake依赖，不代表真实模型质量。完整运行上下文、集中Policy、hooks、计数口径、恢复策略与边界见[AGENT_HARNESS](docs/AGENT_HARNESS.md)。

## 本地展示与模式切换

长期记忆与RAG检索已实现；当前本机使用DeepSeek官方对话接口、硅基流动BAAI/bge-m3向量接口与高德工具。2026-10-27验证记录和已知问题见[当前状态](docs/CURRENT_STATUS.md)。三种模式、固定启动命令、网页测试与推送检查见[本地展示指南](docs/LOCAL_DEMO.md)。
