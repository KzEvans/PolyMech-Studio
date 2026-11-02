# PolyMech Studio — 聚合物弹性体力学数据分析平台

面向课题组日常使用的本地科研软件：导入力学试验仪器数据，用确定性的物理公式完成单轴拉伸、循环拉伸、纯剪切断裂韧性与循环纯剪切疲劳分析，保存可追溯的分析版本，生成期刊风格图表，并通过 Parallels 虚拟机中的真实 Origin 生成可编辑的 OPJU 工程。

> 原则：**科学正确性优先；可复现；AI 只做辅助，不做数值权威；真实接入 Origin，不模拟成功。**
> 需求：`docs/SPEC.md`；进度：`docs/PROJECT_STATUS.md`。
>
> 本仓库是课程“人工智能在化工科研中的应用”期末大作业的代码快照（2026-11-02，对应开发分支 `windows-build`，含 macOS 与 Windows 两种桌面构建）。为保护未公开数据，快照不包含真实实验数据、两篇学位论文的文献数值记录及基于它们的评测结果，详见 `literature/README.md`；仓库中的测试数据均为程序生成并标注 SYNTHETIC 的合成数据。

## 当前状态（2026-11-02）

| 功能（SPEC §0.2 Must） | 状态 |
|---|---|
| 数据导入、列映射（规则 + AI）、单位规范化、元数据、质量检查 | 已实现并测试 |
| 单轴拉伸 / 循环拉伸 / 纯剪切断裂韧性 / 循环纯剪切疲劳（含检测限与删失观测） | 已实现，解析基准测试通过 |
| 真实 Origin 链路（工作表 + 图页 → OPJU + PNG/PDF/SVG → 重新打开核验） | §6.7 十步验收已通过（导出图带 Origin “demo” 水印，需确认授权） |
| SQLite 实验存储与分析版本管理 | 已实现并测试 |
| AI 列映射与质量提示（Codex CLI / Claude CLI / API，可关闭） | 已实现，真实调用评测完成 |
| 界面（概览、实验、导入、分析、绘图工作室、报告、设置） | 已实现，WebKit + Chromium E2E 通过 |
| 课程期末报告 | 单独提交（不含在公开仓库中） |

Should 项中 DMA、文献库、可比性检查、AI 文献对标、多面板与完整绘图编辑器、Origin 模板库已实现；剥离分析暂未实现。已知限制见 `docs/KNOWN_LIMITATIONS.md`。

## 快速开始（macOS）

需要：[uv](https://docs.astral.sh/uv/)、Node.js ≥ 22、pnpm。

```bash
make sync
```

```bash
POLYMECH_DATA_DIR=~/PolyMechData make api
```

另开一个终端：

```bash
make web
```

浏览器打开 http://127.0.0.1:5173 。数据目录默认为 `~/Library/Application Support/PolyMechStudio`（可用 `POLYMECH_DATA_DIR` 指定），其中：`polymech.sqlite`（元数据）、`raw/`（只读原始文件归档，SHA-256 命名）、`curves/`（Parquet 曲线）、`origin/`（Origin 输出）、`backups/`（迁移前备份）。

## Windows Origin Bridge（Parallels 虚拟机）

前提：VM 使用 Shared 网络，用户已登录 Windows，Origin 能正常启动（用户文件夹 UFF 必须是本地可访问路径）。

```bash
scripts/vm/deploy_bridge.sh
```

以下两步会修改 VM 的系统/安全配置，执行前需由使用者确认（可用对应脚本撤销）：

```bash
scripts/vm/run_ps.sh bridge/windows-origin/firewall_rule.ps1 "MacIp=$(ifconfig bridge100 | awk '/inet /{print $2}')"
```

```bash
scripts/vm/run_ps.sh bridge/windows-origin/install_autostart.ps1 'Root=%BRIDGE%' 'User=<Windows 用户名>'
```

然后在应用“设置 → Origin Bridge”中点击“从虚拟机自动配对”（Token 存入 macOS 钥匙串）。详细说明与验证记录：`docs/ORIGIN_BRIDGE.md`。

## 测试

```bash
make check
```

```bash
make e2e
```

`make check`：Ruff、mypy（strict）、207 个 pytest（含 Hypothesis 性质测试、计算引擎覆盖率 ≥ 90% 门槛）、前端类型检查与 Vitest。`make e2e`：Playwright（WebKit + Chromium）主流程与 axe WCAG 2 AA 扫描。真实 Origin 验收：`scripts/acceptance_origin_e2e.py`；AI 评测：`scripts/eval_ai_mapping.py`。详见 `docs/TESTING.md`。

## 目录

```
packages/mechanics   纯计算引擎（numpy/scipy/pint，不依赖 IO、数据库、AI、Origin）
packages/dataio      文件读取、列映射、单位规范化、质量检查、元数据
packages/plotting    PlotSpec、14 个模板、Matplotlib 导出
packages/database    SQLAlchemy 模型、Alembic 迁移、归档与版本
packages/ai          LLM Provider 与结构化输出
apps/api             FastAPI 编排层
apps/web             React + TypeScript + Vite + shadcn/ui 界面
bridge/windows-origin Windows 端 Origin Bridge
fixtures/            合成测试数据（均标注 SYNTHETIC）与 AI 录制响应
scripts/             VM 运维、验收与评测脚本
reports/             课程报告与真实测试数据
docs/                设计、方法、接口、测试、使用说明与决策记录
```

## 文档

`docs/ARCHITECTURE.md` · `docs/SCIENTIFIC_METHODS.md` · `docs/ORIGIN_BRIDGE.md` · `docs/DATABASE_SCHEMA.md` · `docs/TESTING.md` · `docs/USER_GUIDE.md` · `docs/DESIGN_SYSTEM.md` · `docs/DECISIONS.md` · `docs/KNOWN_LIMITATIONS.md` · `docs/PROJECT_STATUS.md`

本仓库不包含任何真实实验数据或论文中的数值；论文 PDF 仅作方法核对，未复制进仓库。
