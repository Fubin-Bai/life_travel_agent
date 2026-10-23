# 人生旅迹前端｜V0 本地原型

React + Vite + TypeScript + 原生 CSS。我的资料、同行人、旅行、访谈和规划已接真实 FastAPI；DeepSeek 只由后端调用。暗调照片保存在 public/journey-flower.jpg，不依赖外链。

## 启动

先在项目根目录终端启动后端（真实访谈/规划需该终端配置 DEEPSEEK_API_KEY；自动加载项目根目录 .env，系统环境变量优先）：

```bash
PYTHONPATH=src .venv/bin/python -m uvicorn life_journey.api:app --host 127.0.0.1 --port 8000
```

另一终端：

```bash
cd frontend
npm ci
npm run dev
```

打开 http://127.0.0.1:5173/ 。开发代理将 /api 转发到8000；不是生产部署配置。`npm run build` 执行 TypeScript 校验和 Vite 构建。

## 页面与数据

- **我的资料**：SQLite local_profile 固定本人，首次空库创建；旧库有多个人物时明确选择并保存一次。之后保存更新原 ID，不再切换主体，不依赖 localStorage。
- **同行人**：独立 Person 编辑与 Relationship 编辑分开保存。可选性别/MBTI；关系类型显示中文，传给后端仍是英文枚举。关系保存失败不撤销已保存人物。
- **新建旅行**：目的地、日期、预算、参与者。金额字符串保留 Decimal 精度；节奏未指定映射 null。创建后进入访谈，可回读已有旅行。
- **首页/访谈**：同一个 trip_id 多轮发送；一轮展示一条 assistant_message。form/input autocomplete=off。状态由 API 恢复，不补造聊天历史。
- **规划展示**：系统 ready 后显示“开始规划”，POST /api/trips/{trip_id}/planning；显示每天活动与适配理由及固定非实时事实提示。成功后同页按钮禁用，失败可重试，无自动重试。

src/api.ts 管理 DTO/请求/关键响应校验，src/App.tsx 管理页面与编辑草稿。模型 Key 不进入浏览器，输入系统 ID 不由用户生成。视觉与业务数据分离，不默认 seed Alex/Bella 或开发测试人物，不按姓名隐藏真实记录。

## 持久化与限制

人物、关系、Trip/TripContext、InterviewState、本人绑定保存到 SQLite；未保存草稿、聊天记录和生成行程仅在内存，刷新后不恢复。当前无登录/用户隔离/删除/主体换绑/行程修改/部署。

性别、MBTI、关系不是兴趣或体力的确定性依据。伴侣关系可以引导可拒绝的适度征询，明确回答优先。默认V0行程仅用模型知识；amap模式使用真实高德候选、条件营业周规则和有限游客路线。两种模式都不保证未来事实、价格或完整可执行性。

离线 UI 联调使用独立临时库和端口8001，不能替换正式8000；测试 fixture 不进入用户库。最新功能构建通过；全项目状态与已知质量问题见 [CURRENT_STATUS](../docs/CURRENT_STATUS.md)。

V1.2行程活动新增可选opening_status/opening_note；原样式显示后端计算的“按周规则的可用窗口”或“营业未知/需核实”。不是未来营业已验证，也不改变其他页面。V0无该信息时不显示，重启后端后配合既有amap模式使用。

V1已基本完成并收尾，真实浏览器已展示北京4天工具辅助行程。前端保持现有视觉，route_note/完整Observation由API返回，当前未新增交通面板；聊天与行程仍不持久化，V2尚未开始。
