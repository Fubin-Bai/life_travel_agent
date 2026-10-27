# 本地启动、展示与验收指南

更新：2026-10-27。长期记忆与RAG检索已实现；验证分层和待核查项见[当前状态](CURRENT_STATUS.md)。

## 固定启动方式

终端A先进入项目根目录，启动后端：

```bash
.venv/bin/python -m uvicorn life_journey.api:app --app-dir src --host 127.0.0.1 --port 8000
```

`.venv/bin/python`使用项目环境；`-m uvicorn`启动服务器；`life_journey.api:app`加载FastAPI应用；`--app-dir src`指定包目录；`--host`只监听本机；`--port`指定后端端口。

终端B从根目录进入前端并启动：

```bash
cd frontend
npm run dev -- --strictPort
```

首次安装或锁文件变化时先执行`npm ci`。打开http://127.0.0.1:5173/；网页经Vite代理访问8000。两个终端都保持运行，不向运行中的服务器输入新命令。Ctrl+C停止服务；修改.env后停止并重启后端，前端无需因后端配置变化重启。正在进行的请求会被停止操作中断。

## 三种模式

| 模式 | 能力 | 设置 |
| --- | --- | --- |
| V1 | Python固定高德检索、营业周规则、有限路线证据 | PLANNING_MODE=amap，VALIDATION=0 |
| Agent | LangGraph工具选择、Harness；开启V3校验与有限修复 | PLANNING_MODE=agent，VALIDATION=1 |
| RAG | Agent、Harness、V3与SQLite长期偏好检索 | PLANNING_MODE=memory，VALIDATION=1 |

表中变量实际前缀均为`LIFE_JOURNEY_`；复制根目录.env.example可取得完整名称。只取消一组注释，其他组保持注释；代码未配置时仍兼容默认v0。Mode是程序工作流，不是Model模型。memory缺少Embedding配置会明确失败，不生成假向量。

根目录.env自动加载，系统环境变量优先。若当前启动终端有旧模式值，可在停止服务后执行：

```bash
printenv LIFE_JOURNEY_PLANNING_MODE LIFE_JOURNEY_VALIDATION
unset LIFE_JOURNEY_PLANNING_MODE LIFE_JOURNEY_VALIDATION
```

printenv无输出表示未导出这些变量，不是项目故障。不同终端环境不一定相同。`变量=值 命令`仅作用于该次命令；export会在当前终端后续命令中生效。正常Ctrl+C重启不要求每次unset。不要用echo/printenv打印Key。

## 当前服务分工

DeepSeek官方deepseek-flash负责访谈、工具决策与规划；硅基流动BAAI/bge-m3负责文本向量化；高德提供地点与路线证据；本地SQLite保存人物、旅行、访谈状态及记忆。Embedding端点为https://api.siliconflow.cn/v1/embeddings，密钥在本地.env自行填写。保存和检索使用兼容模型，换向量模型需处理旧向量重建。

## 网页演示顺序与证据

1. 首页/人物/同行人/旅行读取正常；后端GET返回200证明基础链路。
2. 新建未来日期的大陆单城市旅行，确认目的、节奏、必做和排除活动；本次访谈不是自动长期学习。
3. 在生成规划前打开浏览器Network，勾选Keep log，筛选planning，再点击开始规划。默认响应检查final_status、validation_result、unresolved_constraints、memory_provenance；debug=true才包含Harness摘要/轨迹等metrics。不要为查看记录而无意重复POST，生成会消耗真实配额。
4. 提交明确长期反馈，feedback响应的stored_memory_ids证明写入；confirmed_memory_ids为空不代表写入失败。
5. 同参与者新旅行不重复该偏好，检查memory_provenance是否包含对应记忆ID。召回不等于最终采用，采用情况需结合rationale；当前Trip要求优先。
6. 展示Harness需核对实际debug轨迹中的调用预算、真实执行、缓存与停止原因；并非每次都发生缓存命中或修复。未触发的分支可用离线harness_smoke说明，明确是fake依赖案例。

聊天与生成行程目前不跨刷新恢复；Network打开前的请求通常无法补看，不应为了抓记录刷新丢失行程。功能跑通不保证未来营业、实际交通、事实完整或推荐质量。

## 文档与代码入口

| 入口 | 分工 |
| --- | --- |
| README | 安装、启动及总导航 |
| PRODUCT / ROADMAP | 产品目标边界 / 分阶段目标 |
| ARCHITECTURE / DECISIONS | 当前数据流和模块 / 决策原因及取舍 |
| CURRENT_STATUS | 当前证据、进度和未解决问题 |
| V1_TOOLS / V2_AGENT / V3_CONSTRAINTS / V4_MEMORY | 各阶段专项实现 |
| AGENT_HARNESS | 运行管理、预算、事件、恢复和计数口径 |
| evaluations/README | 评估方式、历史报告及指标边界 |
| src/life_journey/api.py | Web接口及应用装配 |
| application/ | 上下文、访谈、规划、校验、修复和记忆业务流程 |
| llm/ / tools/ / schemas/ / harness/ | 模型适配 / 高德适配 / 数据契约 / 运行管理 |
| storage.py / frontend/ / tests/ | 本地持久化 / 网页 / 离线回归 |

## 推送前检查

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m pip check
npm --prefix frontend run build
git diff --check
git status --short
git check-ignore .env .local/life_journey.sqlite3
```

确认提交列表包含新增源文件、测试、文档；不包含.env、数据库、.venv、node_modules或真实用户记录。测试通过不是所有缺陷已消失；本次闭店和星期文案仍待核查。不自动commit/push，提交前查看暂存差异。
