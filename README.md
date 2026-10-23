# 人生旅迹

一个结合“我是谁、和谁出发、这次想要什么”的个性化 AI 旅行原型。

**当前状态：V0 本地功能收尾（2026-10-23）。** 已可在 Web 完成人物资料、同行关系、旅行创建、真实 AI 访谈和结构化行程生成。推荐质量仍有已知缺口；本次收尾不代表已证明个性化显著优于普通攻略，也不是生产发布。

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
PYTHONPATH=src .venv/bin/python -m uvicorn life_journey.api:app --host 127.0.0.1 --port 8000
```

终端 B 启动前端：

```bash
cd frontend
npm ci
npm run dev
```

打开 [本地前端](http://127.0.0.1:5173/)。开发代理把 `/api` 转发到 8000，后端仅允许本地 5173 的 CORS。API 文档为 [本地 Swagger](http://127.0.0.1:8000/docs)。这些是本地开发方式，尚无部署配置。

人物/旅行保存不需要模型 Key；真实访谈、规划需要在**启动后端的终端**配置 `DEEPSEEK_API_KEY`。可选 `DEEPSEEK_MODEL`，当前代码默认 `deepseek-flash`。程序不自动加载 `.env`，`.env.example` 仅作配置说明，不把 Key 放进前端或提交 Git。

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

最新功能验证：**692 项 pytest 通过**，1 项既有第三方弃用提示；前端 TypeScript/Vite build 通过。普通测试离线，不调用 DeepSeek：

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

未实现：实时搜索/地图/价格、工具调用、可执行性和费用验证、行程质量对比评分、行程持久化/修改、聊天历史持久化、登录、部署、长期 Memory、Multi-Agent。当前没有删除/主体换绑/通用 Trip 修改 UI 或接口。常规 Person/Relationship 更新是完整替换，不是 PATCH；预算尚未明确人均/全组等口径。

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

## English summary

Life Journey is a locally runnable V0 personalized travel prototype: persistent profiles, relationships and trips, a real AI interview, and user-triggered structured itinerary generation. React talks to FastAPI, SQLite and provider-independent Python application logic. DeepSeek is the current provider. V0 feature implementation is closing; comparative itinerary quality validation is still incomplete. No real-time travel tools, authentication, deployment, conversation-history storage or itinerary persistence are implemented.
