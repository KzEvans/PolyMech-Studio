# PolyMech Studio — 项目 CLAUDE.md

> 详细需求见 `docs/SPEC.md`（唯一权威来源，不得改写；需求变更/解释写入 `docs/DECISIONS.md`）。
> 当前进度见 `docs/PROJECT_STATUS.md`。
> 上下文压缩或新会话开始后：先读 `CLAUDE.md` → `docs/PROJECT_STATUS.md` → `docs/SPEC.md` 相关章节，再继续。

## 核心执行要求（SPEC §0）

1. 先检查工作目录、现有项目、开发环境、依赖工具及虚拟机环境；不假设路径、版本或依赖存在。
2. 目录已有代码时先判断是否属于本项目，避免破坏用户已有成果。
3. 编码前形成可执行计划，按依赖分解任务后持续实施，不停留在计划阶段。
4. 优先实现可运行、可测试的完整科研工作流，再逐步扩展。
5. 科学计算必须基于明确物理公式和确定性算法；AI 不替代核心数值计算。
6. 必须真实接入 Parallels 虚拟机中的 Origin/OriginPro，不得将模拟输出冒充真实 Origin 工程。
7. 无法执行的外部集成测试如实记录，不得伪造通过结果。
8. 主动验证、排错、迭代；非根本性问题自行决策，不必每步询问。
9. 不得删除已有实验数据、修改用户已有 Origin 工程、重置虚拟机或清理不属于本项目的文件。
10. 清晰可维护的设计，提供完整复现方法。

界面、使用说明、课程报告用中文；代码、变量、API、数据库字段用规范英文。

## 环境事实（SPEC §0.1，2026-10-25 已核实）

- macOS 27.2，Apple Silicon arm64；Xcode 27.1。
- Parallels Desktop 27.0.0，`/usr/local/bin/prlctl`；VM 名 `Windows 11`，Shared Networking（`net0 type=shared`），未开 Host Shared Folders，已开 Shared Profile。
- `prlctl exec "Windows 11" <cmd>` 可执行命令；输出 GBK 编码（按 GBK 解码或先 `chcp 65001`）。
- `prlctl exec` 的账户/会话可能不是用户图形会话：只用于诊断、部署、启动辅助。Origin COM 与 Bridge 必须运行在用户登录的交互会话中。
- 本机有 `codex`（Codex CLI）与 `claude`（Claude Code CLI），用法见 SPEC §8.5。
- 论文 PDF（只读，不得移动、修改或复制进 Git）：
  - 刘博涵：`/Users/kzevans/Downloads/博士毕业论文终稿-刘博涵.pdf`
  - 陈哲琪：`/Users/kzevans/Downloads/多尺度结构设计增强弹性体力学性能-图书馆提交版.pdf`
  - PDF 各约 20MB：先提取目录定位章节，再按章节读取。
- Phase 0 复核结果（VM 内 Origin/Windows/Python 探测）记录在 `docs/ORIGIN_BRIDGE.md` 与 `docs/PROJECT_STATUS.md`。

## 范围优先级（SPEC §0.2）

截止日期 **2026-11-04**。不得为扩展性推迟 Must 项。

**Must**
1. 数据导入、列映射（规则 + AI）、单位规范化、元数据录入、基础质量检查。
2. 单轴拉伸分析（§4.1）。
3. 循环拉伸分析（§4.2）。
4. 纯剪切断裂韧性（§4.3）。
5. 循环纯剪切疲劳（§4.4），含检测限与删失观测处理。
6. 真实 Origin 最小链路：单轴拉伸数据 → 工作表 + 图页 → OPJU + PNG → 重新打开核验（§6.7）。
7. SQLite 实验存储与分析版本管理（§7.2）。
8. AI 列映射与质量提示，含 Provider 切换及无 AI 模式（§8）。
9. 上述功能涉及页面的完整界面（§9）。
10. 课程期末报告（§12），基于真实测试结果。

**Should**：DMA、界面剥离、Plot Studio 完整编辑器、两篇论文文献库记录、可比性检查、AI 文献对标、多面板排版、Origin 模板库扩展。

**Could**：桌面安装包、视频帧辅助裂纹萌生判定、批量分析性能优化、报告 PDF 美化。

11-02 仍有 Must 未完成 → 冻结新功能。任何 Must 有延期风险尽早告知用户。

## 明确排除

不开发 Network Recovery Analysis（网络恢复动力学分析）模块，不开发端链脱出—重连动力学拟合、恢复时间谱模型或其专用界面。普通循环拉伸、残余应变、应力恢复指标保留。

## 科学正确性红线

- 应变能密度 `W(λ)=∫₁^λ σ_nominal dλ`；**不得**对真实应力积分当作参考体积应变能密度。
- 区分名义应力 `F/A0` 与真实应力 `≈ λ·σ_nominal`（仅近似不可压缩、均匀变形）。
- 循环未闭合时，不得未经说明把积分解释为完整热耗散。
- 纯剪切 `Gc = H0·W(λc)`：严格区分有/无预切裂纹样品；W 来自无裂纹样品。
- 疲劳：保留载荷比、λmin/λmax 及 `G_max`/`ΔG` 等约定，不同定义不得合并。低于检测限的观测标记为未检出/删失，不得填 0，不得未经说明进入普通线性拟合。数据不足/不可辨识时拒绝报告阈值；有限循环未扩展不等于永不疲劳。
- 剥离：T 型 `2F/w`（陈）与裤型 `2F/t`（刘）不同；按几何与裂纹面积确认公式，用户可检查确认。
- DMA Tg 必须注明定义（E″ 峰 / tan δ 峰 / E′ 变化等），不同定义不直接比较。
- 样品尺寸缺失 → 停止相应计算并提示补充，不假设默认值。
- 单位用 Pint 并做维度校验，不靠字符串替换。
- 异常检查只标注，不删除原始数据；修正保留前后曲线及算法、参数、操作者。
- 无原始数据时不得用论文插图推测值冒充实验结果；测试用明确标记的合成数据与解析基准。
- 文献值：原文明确给出 = “文献报告值”；图片数字化 = “图形数字化估计值”；缺失留空。AI 不得凭记忆生成论文、DOI 或数值。
- 新分析不覆盖旧结果，增加新版本；每次计算保留输入、参数、输出、软件版本与哈希。
- AI 输出必须 Schema 校验；未经授权不上传未公开原始数据（CLI Provider 也是云端模型）。

## 常用命令

```bash
make sync                                  # uv sync + pnpm install
make check                                 # ruff + mypy strict + pytest（含覆盖率门槛）+ 前端 tsc/vitest
make e2e                                   # Playwright（WebKit+Chromium，独立端口与临时数据目录）
POLYMECH_DATA_DIR=<dir> make api           # 后端 http://127.0.0.1:8765
make web                                   # 前端 http://127.0.0.1:5173
uv run python scripts/make_fixtures.py     # 重新生成 SYNTHETIC fixtures
uv run python scripts/acceptance_origin_e2e.py <dir>   # 真实 Origin 十步验收（需 API 运行且已配对）
uv run python scripts/eval_ai_mapping.py codex claude  # 真实 AI 评测（会调用云端模型）
scripts/vm/deploy_bridge.sh && scripts/vm/restart_bridge.sh   # 部署/重启 VM 中的 Bridge
make desktop && make desktop-selftest     # macOS 桌面版（Tauri 2 + PyInstaller 后端），见 docs/DESKTOP.md
```

VM 运维：`scripts/vm/vm_lib.sh`（SYSTEM 执行，无窗口）、`run_user.sh`（用户会话隐藏执行）、`push_file.sh`/`pull_file.sh`。不要使用 `prlctl exec --current-user`（会在用户桌面留下终端窗口）。
