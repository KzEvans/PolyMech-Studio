# 项目状态

最后更新：2026-10-28

## 当前阶段

**Must 项全部有可运行实现与真实验证记录**；课程报告初稿完成（报告单独提交，未包含在公开快照中）。下一阶段：Should 项与报告完善。

## 已完成（`make check` + `make e2e` 通过）

| Must | 状态 | 证据 |
|---|---|---|
| 1 导入、映射（规则+AI）、单位、元数据、质量检查 | 完成 | `packages/dataio`（52 测试）；质量注入评测 `reports/data/eval/` |
| 2 单轴拉伸 | 完成 | `packages/mechanics`（90 测试，覆盖率 93%） |
| 3 循环拉伸 | 完成 | 同上 |
| 4 纯剪切断裂韧性 | 完成 | 同上 |
| 5 循环纯剪切疲劳（检测限、删失） | 完成 | 同上；API 疲劳阈值链测试 |
| 6 真实 Origin 最小链路 | **§6.7 十步验收通过** | `reports/data/origin/e2e_20261026/`；`docs/ORIGIN_BRIDGE.md` §4 |
| 7 SQLite 存储与版本 | 完成 | `packages/database`（10 测试） |
| 8 AI 列映射与质量提示 | 完成 | 真实评测 `reports/data/ai_eval/mapping_eval_20261026.json` |
| 9 界面 | 完成（单轴、循环、纯剪切、疲劳、DMA、数据修正均有界面 E2E） | `apps/web`；Playwright WebKit+Chromium 22/22，axe AA |
| 10 课程报告 | 已完成 | 单独提交 |

## Should 项进度

| 项 | 状态 |
|---|---|
| DMA 分析 | 完成：引擎（`packages/mechanics/.../dma.py`，17 个解析基准测试）、API（分析、重新计算、`/api/dma/compare`）、界面（曲线、Tg 候选表、异常点、多样品比较）、报告与 Origin 模板 |
| 两篇论文的文献库记录 | 完成：42 条文献报告值、11 种材料（`literature/`，`docs/LITERATURE.md`）；导入校验与幂等；材料数据库页面显示来源、页码、原文写法 |
| 可比性检查 | 完成：规则引擎（12 类检查、四级结论）、`/api/comparability`、材料数据库页“可比性…” |
| AI 文献对标 | 完成：规则候选 + AI 推荐（只能引用候选记录，返回后二次校验）、默认不发送本实验数值；真实评测 `reports/data/ai_eval/benchmark_eval_20261026.json` |
| 多面板排版与完整编辑器 | 完成：多面板版面、拖拽添加/排序系列、线型/符号/误差棒、面板级恢复默认、自定义模板（保存/套用）、图中数据 CSV 导出、材料库对比散点；E2E 覆盖多面板流程 |
| Origin 模板库扩展 | 完成：8 个真实 `.otpu`（期刊与论文图风格各 4 个，论文图为默认）+ 注册表；方式 A/B 自动切换并报告；真实 Origin 自测与 §6.7 验收重跑通过（`reports/data/origin/templates_20261026/`、`templates_thesis_20261028/`、`e2e_20261026_run2/`）；绘图工作室当前图可导出为可编辑 Origin 图页（`plotstudio_20261028/`） |
| 剥离分析 | 用户决定暂不做 |
| （Could）macOS 桌面版 | 完成：Tauri 2 外壳 + PyInstaller 后端，`.app`/`.dmg`；`make desktop-selftest` 通过（`docs/DESKTOP.md`） |

## 2026-10-28 审查修复

- 已保存图在删除源分析后保留完整曲线；未稳定疲劳输入不能生成正式阈值；迁移备份包含 WAL 中已提交的数据。
- 修复历史分析参数恢复、人工断裂点在回程记录中的定位、历史报告条件及预览图例控制，见 `docs/DECISIONS.md`。
- 补齐材料数据库性能对比图的实验点命名，使用材料名称与版本号，避免来源文件同名时无法区分。

## 测试（2026-10-28）

Python 300；计算引擎 109 测试、覆盖率 93.09%；Vitest 5；Playwright 11 场景 × 2 浏览器。审查修复后完整 E2E 通过；补齐材料点命名后，`make check`、主流程 E2E 12/12 与新构建的 `make desktop-selftest` 再验证通过。修复版已更新到本机应用，原版已备份，实验数据库校验值未变；桌面实测切换历史版本可恢复各自的拟合参数。

## Origin 环境验证

OriginPro 2025b（x64，Windows 11 ARM64 仿真）；Bridge x64 CPython 3.12 + originpro 1.1.15；防火墙仅放行 Mac 地址，登录自启已安装（用户批准）。详见 `docs/ORIGIN_BRIDGE.md`。

## 待用户决策

（无。2026-10-26：用户确认安装 motion-design-skill；demo 水印按用户指示暂时忽略；剥离分析暂不做。）

## 待完成（按优先级）

- Should：全部完成（剥离分析按用户指示暂不做）。
- 报告：使用者实测的人工 vs 软件耗时（目前未测量）。

## 后续执行入口

- 桌面版：`make desktop`（构建）、`make desktop-selftest`（自测）。
- 网页版启动：`POLYMECH_DATA_DIR=<目录> make api` + `make web`；Bridge 已在 VM 登录时自启，`scripts/vm/restart_bridge.sh` 可优雅重启。
- 验收数据目录：`data/acceptance/`（git 忽略）。

## 已知问题

见 `docs/KNOWN_LIMITATIONS.md`。


## Windows 桌面适配（2026-10-28）

Windows 工作保存在 `windows-build`，已提交 `1af10c3`、`19ef5d9`、`2e6e872`、`70637b9`、`1c6b97f`；`main` 保留先前命名与审查修复 `cfaff93`。用户明确要求 Mac 版不用动，此后没有重建、自测或替换 Mac 应用，也没有修改其数据。

Windows x64 后端、同机 Origin Bridge 和 NSIS 已构建。最终源码的 Windows Python 311 通过、1 项 POSIX 测试跳过；Vitest 9、Chromium E2E 13/13、Ruff 与 mypy 通过。真实 Origin 两种导出入口均重新打开 OPJU 核验通过，PNG 3216 × 2280；42 项数值与此前 Mac 合成结果符合量纲容差。

安装、覆盖更新、卸载保留数据、断网分析及真实 Origin 故障/取消/外壳崩溃回收通过；系统 125%/150% 缩放与完整原生键盘流程待人工验收。完整状态见 [Windows 验证记录](WINDOWS.md)，证据位于 `reports/data/windows/20261028-x64/`；未记录通过的项目仍待验收。
