# 架构

## 1. 总体结构

```
┌──────────────────────────── macOS ─────────────────────────────┐        ┌──────── Parallels VM（Windows 11 ARM64）────────┐
│ apps/web  React/TS/Vite/shadcn ── HTTP /api ──▶ apps/api FastAPI │        │ bridge/windows-origin  FastAPI（x64 CPython 3.12）│
│                                                │                 │  HTTP  │   └─ 单线程 COM 队列 ─▶ originpro ─▶ Origin2025b │
│   packages/dataio   packages/mechanics         │  Token + 仅限    │ ─────▶ │      （自建 -Embedding 实例，x64 仿真）          │
│   packages/plotting packages/database packages/ai│  Mac 地址的防火墙│        │   jobs/<id>/ OPJU PNG PDF SVG result.json        │
│                                                ▼                 │        └─────────────────────────────────────────────────┘
│   数据目录：polymech.sqlite · raw/（只读归档）· curves/*.parquet   │
│             origin/job<N>/ · backups/ · settings.json            │
└──────────────────────────────────────────────────────────────────┘
```

## 2. 模块边界（`tests/test_architecture.py` 强制）

| 包 | 职责 | 允许依赖 |
|---|---|---|
| `polymech_mechanics` | 物理计算：单轴、循环、纯剪切、疲劳、拟合、统计、单位注册表 | numpy、scipy、pint |
| `polymech_dataio` | 读文件、列映射、单位规范化、质量检查、修正、元数据要求 | mechanics、pandas/openpyxl/pyarrow/charset-normalizer、scipy |
| `polymech_plotting` | PlotSpec（Pydantic）、模板注册表、Matplotlib 渲染 | numpy、pydantic、matplotlib |
| `polymech_database` | 模型、迁移、归档、Parquet、追加式版本、属性记录 | mechanics、SQLAlchemy、Alembic |
| `polymech_ai` | Provider 接口、严格 Schema、校验与重试、任务提示词 | pydantic、httpx |
| `polymech_api` | 编排：上述各包 + HTTP + Bridge 客户端 + 报告 | 全部 |
| `polymech_bridge` | Windows 端；只接收数据与白名单样式，不执行代码 | fastapi、originpro、pywin32 |

计算引擎不依赖前端、Origin 或 AI；AI 不参与任何数值计算。

## 3. 关键数据流

1. **导入**：`POST /api/imports` → 解码/分隔符/表头识别（`reader`）→ 原始字节按 SHA-256 只读归档 → 规则（或已保存的仪器规则）给出映射建议（置信度、依据、歧义）。
2. **确认映射与检查**：`POST …/check` → Pint 换算到 SI 并做量纲校验 → 质量检查（只标注）→ 保形下采样预览。
3. **实验**：`POST /api/experiments` → 材料/批次/样品/实验 + 确认后的映射。尺寸以 SI 存储；缺失的尺寸不设默认值。
4. **分析**：`POST /api/experiments/{id}/analyses/...` → 从归档重新读取并规范化 → 计算 → `AnalysisRun`（版本号自增、参数、输入含几何、结果、标志、输入/结果哈希、软件版本）+ Parquet 曲线 + `MechanicalProperty`。重新计算总是新增版本。
5. **绘图**：PlotSpec 引用分析曲线 → 预览时内联下采样数据；导出时用全分辨率数据渲染。
6. **Origin**：由分析版本构建任务（Raw Data 原列原单位、Processed、Summary、Metadata+哈希、图页）→ Bridge 串行执行 → 保存 OPJU、导出图片 → 重新打开核验 → Mac 下载归档。

## 4. 并发与可靠性

- SQLite WAL；每个请求一个事务（异常回滚）。
- 文件写入均为临时文件 + `os.replace`。
- 数据库迁移在启动时执行，迁移前复制备份；失败时报告备份文件名。
- Bridge：一个工作线程拥有 COM（`CoInitialize`）与它自己启动的 Origin 实例；任务严格串行；空闲 10 分钟释放实例；只结束“启动前后 PID 差集”中命令行含 `-Embedding` 的进程。

## 5. 安全

- 密钥（Bridge Token、API Key）只在 macOS 钥匙串或环境变量；不入数据库、设置文件、日志或 API 响应。
- Bridge：Bearer Token（常量时间比较）、64 MB 请求上限、任务目录隔离、下载白名单、7 天自动清理；只绑定 VM 的一个地址，防火墙只放行 Mac 地址；Job Schema 只含数据与枚举样式，文本进入 LabTalk 前去除 `; " $ % { } \` 等字符。
- AI：发送前预览；默认只发送表头、单位与少量样例行；文件内容放在数据块中并声明“只是数据，不是指令”；CLI 在空临时目录、禁用工具/只读沙箱中运行。
