# PolyMech Studio 开发计划（v1，2026-10-25，待用户确认）

> 需求来源：`docs/SPEC.md`。范围以 §0.2 Must 为交付底线，截止 2026-11-04。
> 本计划只描述“将要做什么”，不代表已完成；进度见 `docs/PROJECT_STATUS.md`。

## 1. 仓库结构与模块边界

```
polymech/                        uv workspace 根（Python 3.12，macOS arm64）
├─ packages/
│  ├─ mechanics/   polymech_mechanics   纯计算：numpy/scipy/pint，无 IO、无 DB、无 AI、无 Origin
│  ├─ dataio/      polymech_dataio      读文件、编码/分隔符/表头探测、列映射规则、单位规范化、质量检查
│  ├─ plotting/    polymech_plotting    PlotSpec（Pydantic，可序列化）、模板注册表、Matplotlib 导出
│  ├─ database/    polymech_database    SQLAlchemy 模型 + Alembic 迁移 + 仓储层 + Parquet 曲线存储 + 原始文件归档
│  └─ ai/          polymech_ai          Provider 接口（Codex CLI / Claude CLI / API）、Schema 校验、回退
├─ apps/
│  ├─ api/         polymech_api         FastAPI：编排上述包，HTTP API，Bridge 客户端
│  └─ web/                              React + TS + Vite + Tailwind + shadcn/ui + Motion + Plotly + TanStack Query
├─ bridge/windows-origin/              独立 Python 应用（VM 内 x64 CPython 3.12，originpro）；共享 PlotSpec 的 JSON Schema
├─ templates/  (plot + origin)   fixtures/ (合成数据+解析基准)   tests/   docs/   reports/   scripts/
```

依赖方向（用测试强制，禁止反向导入）：

```
mechanics ← dataio ← database ← api → web(HTTP)
mechanics ← plotting ← api            ai ← api            api → bridge(HTTP)
```

`mechanics` 只依赖 numpy/scipy/pint；每个分析方法 = `输入数据类 + 参数数据类 → 结果数据类`，带明确单位约定（内部 SI：Pa、m、N、s、J/m³、J/m²；展示层换算）和专用异常（`MissingGeometryError`、`UnitDimensionError`、`CycleSegmentationError`、`InsufficientDataError` 等）。

## 2. 核心数据模型（初版）

**计算层（Pydantic / dataclass）**
- `Curve`：列名 → `pint.Quantity` 数组 + 采样元信息；原始与修正曲线并存，修正记录 `{algorithm, params, operator, timestamp}`。
- `SpecimenGeometry`：厚度、宽度、标距 L0、纯剪切高度 H0、初始裂纹长度 c0；缺失即拒绝计算对应指标。
- 各模块 `*Params` / `*Result`：结果含数值、单位、拟合区间、R²、残差、有效点数、不确定度、`warnings[]`、`conventions{}`（如 `G_definition = "G_max"`、`Tg_definition = "tan_delta_peak"`）。
- 疲劳观测 `CrackGrowthObservation`：`dc_dN`、`status ∈ {measured, below_detection_limit, no_growth_observed}`、`detection_limit`，删失点不进入普通线性拟合。

**数据库层（SQLite，SQLAlchemy + Alembic）**
`Material`、`MaterialComponent`（含 PolymerBlock 信息）、`SampleBatch`、`Specimen`、`Experiment`（测试类型、条件）、`ExperimentProtocol`、`RawDataFile`（归档路径、SHA-256、大小、编码、原名）、`ColumnMapping` / `ImportProfile`（仪器可复用规则）、`AnalysisRun`（版本号、方法、参数 JSON、软件版本、输入哈希、结果哈希、状态；**只追加不覆盖**）、`MechanicalProperty`（量、值、单位、条件、来源 → AnalysisRun 或 LiteratureMeasurement）、`PlotConfiguration`（PlotSpec JSON + 版本）、`LiteratureSource`、`LiteratureMeasurement`（提取方式：报告值/数字化估计值）、`OriginJob`。
数值曲线存 Parquet（按 AnalysisRun/RawDataFile 分文件），数据库存路径+哈希；文件写入采用临时文件 + 原子替换。

## 3. 里程碑（按依赖排序，每个都有验收标准）

| M | 日期 | 内容 | 验收（必须真实执行） |
|---|---|---|---|
| **M0** 环境与骨架 | 10-25～26 | Phase 0 复核（已完成大部分）；**Origin 最小链路**（待 UFF 决策）；Git、uv workspace、Ruff/mypy/pytest/Hypothesis、pnpm + Vite 骨架、Vitest、Playwright（WebKit+Chromium）、`make check` 一键脚本；阅读两篇论文方法章节，写 `SCIENTIFIC_METHODS.md` 初稿（公式+页码出处） | `make check` 全绿；Origin smoke test 输出 OPJU+PNG 并经新实例重开核验（或如实记录阻塞） |
| **M1** 导入与规范化 | 10-27 | CSV/TSV/TXT/XLSX/多表 Excel/批量；编码（UTF-8 BOM/GBK）、分隔符、说明行、多层表头探测；规则映射（中英文同义词 + 单位行解析 + 置信度 + 依据）；Pint 单位规范化与维度校验；元数据模型；质量检查（§3.5 全部条目，只标注不删除） | 合成“怪格式”fixtures（GBK、BOM、多表头、百分数应变、mN/kN、μm）全部正确解析；单位/维度测试 |
| **M2** 单轴拉伸 | 10-28 | §4.1 全部 14 项：λ、ε、σ_nom、σ_true、指定区间模量拟合（拟合线/R²/残差/点数）、σ_max、断裂点识别、W(λ) 梯形/累积积分、微分模量、应变硬化、重复样品统计（均值/SD/95% CI）、屈服/颈缩/滑移警告 | 解析基准：线性材料模量、neo-Hookean W(λ) 闭式解、积分误差 < 1e-4 相对；Hypothesis 性质测试；覆盖率 ≥ 90% |
| **M3** 循环拉伸 | 10-29 | 循环自动分割（λ 极值 + 滞回判据，可手动修正）、加载/卸载识别、W_load/W_unload/W_hys、闭合性判据（未闭合给出警告并分开报告）、峰值应力、模量变化、残余应变、逐循环与累积耗散、多幅度比较 | 构造闭合椭圆滞回（解析面积）、不闭合循环、逐步增幅循环；分割失败报错测试 |
| **M4** 纯剪切断裂 | 10-30 | 有/无裂纹样品配对；H0、c0 记录；W(λc) 来自无裂纹样品；λc 人工/时间戳/帧号输入；Gc=H0·W(λc)；量纲检查（J/m²）；多样品统计；几何/黏弹性适用性警告 | 已知 λc 的合成配对数据 → Gc 解析值；缺 H0 时拒绝计算 |
| **M5** 循环纯剪切疲劳 | 10-30～31 | 稳态循环识别、稳态 W(λ) → G（保留 λmin/λmax、载荷比、G_max/ΔG 约定，不同约定拒绝合并）；c–N 导入与 Δc/ΔN；检测限 = 分辨率/间隔；删失观测标记；阈值：指定区间线性外推 + bootstrap CI + 可辨识性检查（点数、R²、残差非线性）不满足则拒绝报告；长周期无扩展 → 阈值区间/下界（措辞不宣称“永不疲劳”） | 已知 dc/dN=k(G−G0) 合成数据回收 G0；含删失点、不可辨识数据的拒绝测试 |
| **M6** 数据库与版本 | 10-31 | Alembic 初始迁移；导入→归档（SHA-256、只读权限）→Experiment→AnalysisRun（追加式版本）→结果/图表；重跑分析、版本对比；事务 | 集成测试：导入→分析→保存→换参数重跑→两个版本并存且可对比；迁移 up/down |
| **M7** Origin 集成 | 10-31～11-01 | Bridge（VM 内）：FastAPI + 单 COM 工作线程串行队列、Token 认证、请求大小限制、任务目录隔离、路径白名单、只管理自建 PID、显式 `op.exit()`；API 见 SPEC §6.4；方式 B 程序化绘图（Raw/Processed/Summary/Metadata/Graph）+ 至少 1 个原生 `.otpu` 模板；规范文件名；Mac 端客户端、地址探测（prlctl）与降级 | **SPEC §6.7 十步真实端到端**：Mac 上传单轴文件 → … → Mac 收到 OPJU/PNG → 新实例重开核验；Bridge 断开时其余功能正常 |
| **M8** AI | 11-01 | Provider 接口 + Codex CLI（默认）/Claude CLI/API；CLI 参数以本机 `--help` 为准并记入 DECISIONS；子进程、无 shell、超时、空临时目录、只读/无工具模式；发送前预览（默认仅表头+单位行+少量样例）；Pydantic 校验、一次重试、回退规则系统；AI 质量提示（只建议）；关闭 AI 模式 | 录制响应契约测试；真实调用评测映射正确率/误报/漏报（记录 Provider 与模型版本） |
| **M9** 界面 | 11-01～02 | 先 WebFetch 阅读 HIG 并写 `DESIGN_SYSTEM.md`；（经确认）安装 motion-design-skill；页面：Dashboard、Experiments（导入/映射表/元数据/质量）、Analysis（三栏，四个 Must 模块，参数改动即重算）、Plot Studio（模板+预览+系列+导出，Must 范围内）、Reports（基础）、Settings（AI Provider 状态、Bridge 地址/Token/测试/日志、单位、存储位置、减少透明度开关）；亮/暗色、键盘可达、reduced-motion | Playwright（WebKit+Chromium）覆盖“导入→识别→补尺寸→预览→计算→模板→导出”主流程，无失效按钮；axe 可访问性检查 |
| **M10** 报告与收尾 | 11-02～04 | 单次分析报告（HTML/JSON，PDF 视时间）；`reports/` 课程报告（基于真实测试数据：导入耗时对比、映射正确率、手算 vs 程序误差、Origin 步骤数、批量耗时、AI 误报漏报、失败案例）；全部 docs；最终核验 | 报告中每个数字可追溯到 `reports/data/` 中的真实运行记录 |

Should 项（DMA、剥离、完整 Plot Studio、文献库、可比性检查、AI 文献对标、多面板、模板库）在对应 Must 完成后插入：计算核心（DMA/剥离）预计可在 M5 后穿插完成，其余在 M9 后视余量推进；**11-02 起冻结新功能**。

## 4. 测试方法

- **科学正确性**：每个公式有解析基准测试（SPEC §11.1 全部 9 类），显式容差；Hypothesis 测单位换算可逆性、积分可加性、对称性等性质；`mechanics` 覆盖率门槛 90%（CI 强制）。
- **手算对照**：选 2–3 条合成曲线用独立实现（scipy 直接积分 / 解析式）对照，结果写入课程报告。
- **集成**：导入→DB、分析→图表、PlotSpec 保存/恢复、AI 关闭、Bridge 断开降级、迁移。
- **Origin 实机**：`bridge/windows-origin` 下的实机测试脚本 + 结果 JSON 存档于 `reports/data/origin/`，不以文件存在作为通过标准。
- **前端**：Vitest（组件/状态）、Playwright WebKit + Chromium（主流程、键盘、暗色）。
- **静态检查**：Ruff、mypy（strict 用于 mechanics/dataio）、ESLint、tsc。

## 5. 关键技术决策（详细理由写入 DECISIONS.md）

1. Bridge 使用 VM 内 **x64 CPython 3.12 + 外部 originpro（COM）**，单工作线程（`CoInitialize` 在该线程）串行队列；内嵌 Python 作为实测后的备选。
2. Mac↔VM 走 Shared 网络 HTTP；Bridge 只绑定 VM 的 Shared 网卡地址，防火墙仅放行宿主地址的单一端口；地址运行时经 `prlctl list -i` 探测并可在 Settings 覆盖。
3. 部署/诊断用 `prlctl exec --current-user`；Bridge 常驻进程由用户会话启动（登录时计划任务或桌面快捷方式，二选一由用户决定）。
4. 内部单位 SI + Pint；展示层 MPa、kJ/m² 等。
5. 曲线 Parquet、元数据 SQLite、原始文件内容寻址归档（SHA-256 命名，只读）。

## 6. 需要用户决策/操作的事项

见 `docs/PROJECT_STATUS.md` “待用户决策”。
