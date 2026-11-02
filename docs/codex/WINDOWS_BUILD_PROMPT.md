# 提示词：为 PolyMech Studio 构建 Windows 版

> 用法：在仓库根目录 `/Users/kzevans/Polymech` 启动 Codex，把下面“提示词正文”整段交给它。2026-10-28 已复核源码、现有虚拟机和下方列出的官方文档；工具版本、空闲空间和进程状态仍须在实际执行时复核。用户在当前会话已批准的事项继续有效。

> 本次执行的后续约束：用户明确要求“Mac 版不用动”。已有 Mac 回归记录保留；后续不再重建、启动自测或替换 Mac 应用，不修改其用户数据。Mac 仅编辑源码、调度 Windows 虚拟机及收集产物。A 方案、关闭 Origin 和重启虚拟机均已获授权。

---

## 提示词正文

你是本仓库（PolyMech Studio，聚合物弹性体力学数据分析平台）的开发者。任务：**在不破坏现有 macOS 版与网页版的前提下，构建可安装、可运行的 Windows 桌面版**，界面采用 Windows 11 的 **Fluent 2** 设计语言，并在 Windows 上**直接调用本机 Origin**（不再需要虚拟机 Bridge）。全程如实记录，不得伪造测试结果。

“不再需要虚拟机 Bridge”指 Windows 用户导出时使用同机 Origin。当前 Mac 上的开发、打包与验收可以使用已有 Parallels 虚拟机，macOS 用户的远程 Bridge 工作流继续保留。

### 0. 执行边界与起点

- 先运行 `git status --short`、`git branch --show-current`，区分已有改动与本次改动。保留工作区中已经完成的命名与审查修复，不执行 `reset --hard`、`clean` 或覆盖式恢复。
- 已完成修复也是 Windows 版的基线：绘图工作室和材料库的图中名称使用实验材料名称；删除源分析后已保存曲线保留；未稳定疲劳输入不得生成正式阈值；迁移备份包含 WAL；历史参数与报告使用各自保存的信息。
- 不改写 `docs/SPEC.md`。本任务对 Windows 外观、本机 Origin 和构建方式的补充写入 `docs/DECISIONS.md`。
- 验证使用明确标为 SYNTHETIC 的数据和独立的 `POLYMECH_DATA_DIR`。不把真实实验数据、现有设置、密钥、`.venv`、`node_modules`、macOS 二进制或已有构建缓存复制进 Windows 源码包。
- 需要安装许可时，只等待依赖该安装的步骤。继续完成提示词、盘点、跨平台代码、构建脚本和 macOS 回归，不把整个任务停在安装提问上。

### 1. 开始前必须阅读

按顺序阅读，并结合当前会话和父目录中适用的 `AGENTS.md` 指令执行（仓库本级未发现 `AGENTS.md`，项目规则另见 `CLAUDE.md`）：

1. `CLAUDE.md`（项目规则、科学正确性红线、常用命令）
2. `docs/PROJECT_STATUS.md`、`docs/DECISIONS.md`（已做的决定，尤其 2026-10-26 桌面版、2026-10-27 默认绘图风格、2026-10-28 Origin 导出）
3. `docs/DESKTOP.md`（macOS 桌面版结构：Tauri 2 外壳 + PyInstaller 后端）
4. `docs/DESIGN_SYSTEM.md`（现行 HIG 设计令牌；Windows 版在此基础上增加一套 Fluent 2 取值）
5. `docs/ORIGIN_BRIDGE.md`（Origin 自动化的全部实测结论，第 2、5、6 节必读）
6. `docs/SPEC.md` 中与桌面封装（§2.1）、Origin（§6）、界面（§9）相关的章节

### 2. 硬性约束

- **不改变科学计算**：`packages/mechanics`、`packages/dataio` 的算法与结果不因平台而变；Windows 上跑同一套测试必须得到相同结果。
- **不破坏 macOS 版**：`make check`、`make e2e`、`make desktop`、`make desktop-selftest` 在 macOS 上必须继续通过。平台差异用运行时判断或条件编译隔离，不复制整份代码。
- **界面文字中文，代码/变量/API 英文**；新增界面文案与现有风格一致。
- **Origin 安全规则不变**：只操作自己启动的 Origin 实例（命令行含 `-Embedding` 才能结束，见 `bridge/windows-origin/polymech_bridge/worker.py` 的 `is_automation_instance`）；**不得附着、修改或关闭用户自己打开的 Origin**；不得修改用户已有的 Origin 工程。
- **虚拟机**：不得重置、回滚或清理 VM；不得使用 `prlctl exec --current-user`（会在用户桌面留下终端窗口），用 `scripts/vm/run_user.sh`（用户会话中隐藏执行）和 `scripts/vm/vm_lib.sh`（SYSTEM 会话）。
- **安装软件前先征得用户同意**：在 VM 或 Mac 上安装任何工具链（Rust、Visual Studio Build Tools、Node、pnpm、uv、Python、NSIS/WiX 等）之前，先列出清单（名称、版本、来源、大小、安装位置）请用户确认。
- **安装清单具体化**：区分下载大小、解压安装空间与编译缓存；估算标明“估算”。使用官方来源并记录校验值。已有 Python 和 WebView2 优先复用；新建项目自己的构建环境，不升级或重装正在服务 macOS 的 `%LOCALAPPDATA%\PolyMechBridge\venv`。不擅自扩容、重启 VM、关闭防护或卸载其他软件。
- **如实记录**：无法执行的测试写明原因；不得把模拟输出当作真实结果；任何“通过”都要有可复现的命令和输出。
- **Git**：在新分支 `windows-build` 上工作，小步提交（提交信息英文，说明为什么）；不推送、不合并到 `main`，除非用户明确要求。
- **提交范围**：先保存已有差异清单。已完成的前序修复可以单独形成基线提交；Windows 适配和提示词另行提交。不要把其他用户文件一并提交；若 `windows-build` 已存在，先检查用途，不覆盖该分支。

### 3. 已核实的现状（动手前复核）

**构建链（macOS）**：`scripts/desktop/build.sh` 三步——`pnpm -C apps/web build` → `uv run pyinstaller apps/desktop/backend.spec`（onedir，产出 `build/desktop/backend/polymech-backend/`）→ `pnpm tauri build`（`apps/desktop/src-tauri`）。Tauri 配置 `apps/desktop/src-tauri/tauri.conf.json`：`bundle.targets = ["app","dmg"]`，`resources` 把后端与 `apps/web/dist` 打进包；插件 `tauri-plugin-single-instance`、`tauri-plugin-window-state`；`@tauri-apps/cli` 2.12.4。

**需要按平台处理的地方**（逐一确认，可能还有更多）：

| 位置 | macOS 现状 | Windows 需要 |
|---|---|---|
| `apps/desktop/src-tauri/src/main.rs` | 应用菜单含 About/Services/Hide 等 macOS 项；“在 Finder 中显示…”用 `open`；后端可执行文件 `backend/polymech-backend`；下载目录 `~/Downloads` | 菜单改为窗口内菜单栏（文件/编辑/显示/帮助），快捷键 `CmdOrCtrl`；用 `explorer` 打开文件夹；可执行文件带 `.exe`；下载目录取系统“下载”已知文件夹 |
| `apps/api/src/polymech_api/settings.py` | 数据目录 `~/Library/Application Support/PolyMechStudio` | `%APPDATA%\PolyMechStudio`（数据），日志与缓存放 `%LOCALAPPDATA%\PolyMechStudio\` |
| `apps/desktop/backend_entry.py` | Matplotlib 缓存 `~/Library/Caches/...` | `%LOCALAPPDATA%\PolyMechStudio\matplotlib` |
| `apps/api/src/polymech_api/desktop.py` 的 `watch_parent` | 以 `os.getppid()` 改变判断父进程消失 | Windows 需检查父进程句柄或用 Job Object；正常退出和外壳异常终止都要回收本次后端、Bridge 及其自建 Origin |
| `packages/ai/src/polymech_ai/providers.py` | 命令查找、POSIX 子进程启动 | 识别 Windows 的 `.exe`、`.cmd`，参数作为参数传递；取消、超时后不留下 CLI 子进程，不弹控制台 |
| `apps/api/src/polymech_api/secrets_store.py` | 只支持 macOS 钥匙串（`/usr/bin/security`），否则只能用环境变量 | Windows 凭据管理器（例如 `keyring` 库的 Windows 后端；先评估再选），环境变量仍优先 |
| `apps/api/src/polymech_api/desktop.py` | 从登录 shell 读取 `PATH` 和代理变量（Finder 启动的 App 缺少它们） | Windows 进程继承用户环境变量；代理常配置在系统设置里而非环境变量——AI 调用的代理应从系统读取（如 `urllib.request.getproxies()` 在 Windows 读注册表），仍只用于 AI 调用，不影响本机 Origin 连接 |
| `apps/api/src/polymech_api/services/origin.py` | 通过 Parallels `prlctl` 列出 VM、配对 VM 中的 Bridge | Windows 上没有 prlctl：VM 状态显示“不适用”；改为本机 Origin 模式（见 §5） |
| 前端快捷键（`AppShell.tsx`、`Analysis.tsx`、`PlotStudio.tsx`、`Experiments.tsx`、`Help.tsx` 中的 `metaKey` 与“⌘”文案） | ⌘ | Ctrl；文案与提示按平台显示（Ctrl+O 等）；注意 WebView2 默认 Ctrl+R/F5 会刷新页面，需拦截为“重新计算”或改用其他组合 |
| `apps/web/src/index.css` | 字体 `-apple-system, "PingFang SC"…`，HIG 令牌 | Fluent 2 令牌（§4） |
| `packages/plotting`（`render.py` 的中文回退字体） | 已含 `Microsoft YaHei`；论文图样式用 Times New Roman | 确认 Windows 上 Times New Roman、微软雅黑可被 Matplotlib 找到；导出图与 macOS 像素尺寸一致（3216 × 2280 px） |
| `scripts/desktop/selftest.sh`、`Makefile` | bash | 提供 PowerShell 等价脚本（`scripts/desktop/build.ps1`、`selftest.ps1`），Makefile 不必在 Windows 上运行 |

**Origin 已知结论**（`docs/ORIGIN_BRIDGE.md`）：OriginPro 2025b x64；外部 Python 用 `originpro`（Bridge 现用 CPython 3.12 x64 + originpro 1.1.15）；`op.set_show(False)` 首次调用会启动**新的**隐藏实例；COM 与 Origin 必须运行在用户登录的交互会话中；Origin 2025b 的模板字体在重新加载时会回到首选项默认，需建图后重设；图例加粗需 `%%(n)` 与 `%(CRLF)`；“demo”水印属授权问题，暂时忽略。

**构建环境**：本仓库没有 Git 远端和 CI，只能在本机的 Parallels VM（名称 `Windows 11`，ARM64，x64 仿真，已登录用户，已装 OriginPro 2025b 与 Bridge 的 x64 Python 3.12）或用户另行提供的 Windows 电脑上构建。VM 中目前没有 Rust、MSVC、Node、pnpm 工具链（复核）。

2026-10-28 只读盘点：Windows 版本 `10.0.26300`，Bridge Python 为 `3.12.15` AMD64、`originpro 1.1.15`，WebView2 为 `155.0.4283.62`。C 盘约有 27 GiB 可用空间；未发现 Rust、MSVC、Node、pnpm、uv 或 Git。系统另有 Python 3.13，不能把 PATH 中的 WindowsApps 启动别名当成已核实的构建解释器。已有三个非 `-Embedding` 的 Origin 进程；本任务不得关闭它们。

#### 3.1 构建放在哪里

- 默认采用 **Mac 调度、Windows VM 打包**：源码编辑、前端开发与 macOS 回归在 Mac 上进行；将明确列出的源码与锁文件送到 VM 的短路径专用构建目录，在 VM 内生成 x64 后端、Bridge、Tauri 外壳和 NSIS 安装包，再把产物与验收记录取回 Mac。不需要额外的 Windows 电脑，也不需要新增 CI 或 Git 远端。
- 若用户选择尽量在 Mac 构建，可以在 Mac 交叉编译 Tauri 外壳与 NSIS 安装包。官方路径使用 NSIS、LLVM、`x86_64-pc-windows-msvc` 目标与 `cargo-xwin`；这条路径验证较少，要先做最小外壳构建验证，再决定是否采用。安装这些工具仍需列单确认。
- **Python 部分两条路径都必须在 Windows 上用 PyInstaller 冻结**。macOS 的 PyInstaller 产物不能改后缀当成 Windows 程序。交叉构建成功也不能代替 Windows 上的安装、WebView2、凭据和 Origin 实测。
- Windows 构建使用独立输出目录。若同一 Mac 源码目录做交叉构建，用显式 Tauri 配置覆盖引用 Windows 资源，不能把现有 macOS 后端目录替换成 Windows 文件。

#### 3.2 源码和构建产物约定

- 使用 `uv.lock` 与各前端目录的锁文件固定依赖。记录 Node、pnpm、Rust、MSVC、SDK、Python、PyInstaller 的实际版本及目标架构。不要为构建顺手升级现有 macOS 依赖。
- 基础 Tauri 配置保留 macOS 行为。Windows 覆盖放在 `apps/desktop/src-tauri/tauri.windows.conf.json`，至少设置 `bundle.targets`、`.ico`、Windows 资源路径和 NSIS 选项。最终合并配置须通过本仓库 CLI 的配置校验。
- 在 Windows 逐一验证冻结后的程序：`polymech-backend.exe` 启动与迁移，Matplotlib PNG/SVG/PDF 导出，`polymech-bridge.exe` 启动、模板校验、真实 Origin 调用。不能仅以 PyInstaller 返回 0 判断成功。
- `build.ps1`、`selftest.ps1` 对每个外部程序检查 `$LASTEXITCODE` 或 `Process.ExitCode`，失败立即返回非零。PowerShell 的 `$ErrorActionPreference = 'Stop'` 本身不能捕获所有外部程序失败。源码和日志使用 UTF-8，路径作为独立参数传递，不拼进命令字符串。
- 交付包括安装包、SHA-256、版本与目标架构、构建命令、源码提交、依赖清单和第三方许可。依赖下载可联网，安装和本地分析应能在离线环境完成。

### 4. 设计语言：Fluent 2（Windows 11）

做法：**同一份 React 前端**，在首次渲染前确定平台并在根元素加 `data-platform="windows"`（桌面端以受控的平台信息为准，网页版回退到 UA），在 `index.css` 中为该平台提供另一套 CSS 变量取值。快捷键判断与展示共用同一个平台模块。**不引入 `@fluentui/react-components`**（与现有 shadcn/Radix 组件体系冲突），在现有组件上换令牌。参考 Fluent 2 官方设计规范（fluent2.microsoft.design）核对数值，不凭记忆。

| 项 | Windows 取值（实现前对照官方规范核对） |
|---|---|
| 字体 | `"Segoe UI Variable", "Segoe UI", "Microsoft YaHei UI", sans-serif`；数字用 `tabular-nums` |
| 字号阶梯 | Caption 12/16、Body 14/20、Body Strong 14/20 半粗、Subtitle 20/28、Title 28/36（按页面层级映射现有 `--text-*`） |
| 控件 | 标准高度 32 px，紧凑 24 px（科研界面的密度选择）；常规矩形圆角 4 px，较小控件 2 px，大型容器按 8/12 px 的官方令牌映射并注明选择 |
| 颜色 | 中性色层级与描边按 Fluent 2；强调色跟随系统强调色（外壳读取后注入；读不到时用 Fluent 默认蓝）；亮/暗主题都满足 WCAG AA |
| 材质 | 窗口背景 Windows 11 用 Mica（Tauri 窗口效果，查当前 Tauri 2 文档中的配置名），Windows 10 或“减少透明度”时用纯色；内容区不透明 |
| 标题栏 | 系统标准标题栏（最小化/最大化/关闭在右）；如自绘，必须保留系统按钮行为、贴靠布局（Snap Layouts）与拖动区域 |
| 菜单与命令 | 窗口内菜单栏（文件/编辑/显示/帮助）；页面工具栏沿用现有分组，主操作强调色 |
| 对话框 | 主操作按钮在左、取消在右（与 macOS 相反）；`components/confirm.tsx`、各对话框按平台调整顺序 |
| 焦点 | Fluent 双层焦点框（外 2 px 深色 + 内 1 px 浅色），键盘可完成全部操作 |
| 滚动条 | 细滚动条，悬停加粗 |
| 动效 | 短促、可取消，尊重系统“动画效果”关闭 |

把最终取值和与 HIG 的差异写进 `docs/DESIGN_SYSTEM.md` 新增的“Windows（Fluent 2）”一节，并说明哪些是规范原值、哪些是折中。

系统强调色不能直接假设白字可读；文字色与按钮填充须分别满足对比度。Mica 只用于窗口背景或边框可见部分，图表和内容面板保持纯色；无法获得系统能力或关闭透明效果时直接使用实色，并记录降级。系统标题栏和原生窗口菜单优先，保留最小化、最大化、关闭及 Snap 行为。不要为传递平台和颜色向本地 HTTP 页面授予广泛文件、Shell 或 Tauri IPC 权限。

### 5. 本机 Origin 模式（Windows 版的核心价值）

目标：Windows 版装在已安装 Origin 的电脑上时，“导出到 Origin…”直接使用本机 Origin，结果与现在经 VM Bridge 的完全一致（同一 `PlotJob` 协议、同一模板与核验）。

推荐方案（如有更好方案，先写出取舍再实施）：

- 复用 `bridge/windows-origin/polymech_bridge`（`server.py` / `worker.py` / `origin_build.py` / `templates.py`），把它打包为第二个可执行程序 `polymech-bridge.exe`（x64，含 `originpro`），随安装包分发，模板放在其资源目录并保留注册表 SHA-256 校验。
- 由外壳（或后端）按需启动：只监听 `127.0.0.1` 随机端口，每次启动生成随机 Token，经进程间传递给后端（不写入日志或设置文件）；后端的 `BridgeClient` 指向它。macOS 仍走 VM Bridge，设置页按平台显示对应选项。
- 检测 Origin：从注册表或安装路径确认 `Origin64.exe` 存在并给出版本；没有 Origin 时功能清楚降级，其余功能照常。
- 行为保持：只结束自己启动的 `-Embedding` 实例；保存前激活第一张图页；保存后重新打开核验；PNG 宽 3216 px。
- 架构：用户电脑多为 x64；后端与 Bridge 都按 **x64** 构建（与 x64 Origin 一致）。在 ARM64 VM 上用 x64 Python（仿真）运行 PyInstaller，Rust 目标 `x86_64-pc-windows-msvc`。

实现时还必须满足：

- 保持 `PlotJob`、模板注册表与建图算法共用。本机模式增加独立启动入口，不直接复用会创建 `%LOCALAPPDATA%\PolyMechBridge\token.txt` 和固定 8766 端口的旧 `__main__.py`；现有远程 Bridge 的配置、自启任务与文件全部保留。
- Token 通过匿名管道或受控子进程环境传入，禁止放在命令行、URL、stdout、日志、数据库或长期配置中。向后端返回端口与就绪状态的握手不含 Token；客户端对本机 Bridge 明确禁用 HTTP 代理。
- 按需启动只创建一个本次应用拥有的 Bridge；并发点击导出不能启动多个 Bridge。创建 Origin 的前后都记录 PID、启动时间与 `-Embedding` 归属，仅清理已确认属于本次任务的实例。
- 退出时先请求 Bridge 正常停止，让工作线程关闭自建 Origin；超时后也只能处理已确认归属的进程树。测试取消、失败、正常退出及外壳异常终止。不得用进程名批量结束 Origin。
- 未安装 Origin、COM 注册缺失、许可不可用或模板缺失时，分别给出可理解的状态。Origin 的检测不触发启动用户实例。普通分析和 Matplotlib 导出始终可用。
- 用户目录中的路径通过参数和文件系统 API 传递；不把任意本地路径放进 LabTalk。只在本次任务目录生成文件，保留完整分辨率数据、科学单位与用户的系列名称。

### 6. 安装包

- Tauri Windows 目标：NSIS 安装程序（必要时再加 MSI）；**按用户安装**（`%LOCALAPPDATA%\Programs`，不需要管理员权限）；WebView2 运行时随安装包处理（离线可用的方式，查当前 Tauri 2 文档中的配置名）；生成 `icon.ico`（`pnpm tauri icon`）。
- 未签名会触发 SmartScreen 提示：如实写进文档，并说明用户如何放行；不要尝试绕过。
- 处理含中文用户名的路径、长路径（PyInstaller onedir 目录深度）、杀毒软件误报（记录，不规避检测）。
- NSIS 配置明确使用 `installMode: "currentUser"`。WebView2 用官方 `webviewInstallMode: {"type":"offlineInstaller"}`；核对冻结后端所需 VC 运行库，不能以构建机上已有运行库推断用户电脑也有。
- 升级、修复安装及卸载只管理程序安装目录，保留 `%APPDATA%\PolyMechStudio` 的实验、原始文件、配置与导出结果。用独立测试数据验证升级前后哈希，不通过卸载来清空测试数据。
- 未签名产物如实标记。遇到 SmartScreen、安全警告或权限界面需用户接管时交给用户，不自动绕过。不要为验收卸载系统共享的 WebView2 或 VC 运行库。

### 7. 分阶段执行（每阶段完成后验证并在 `docs/WINDOWS.md` 记录）

1. **盘点**：列出全部平台相关代码（不止 §3 表格），给出改动清单与风险；记录现有工作区、Python 架构、Origin 实例与磁盘余量。根据用户选择的构建路径列出所需工具，**请用户确认后**再安装。
2. **跨平台基础**（在 macOS 上完成并保持全部测试通过）：数据/日志/缓存路径、凭据存储、代理读取、下载目录、快捷键与文案的平台抽象；为新逻辑写单元测试（用 `monkeypatch` 模拟平台）。
3. **Fluent 2 主题**：令牌、对话框按钮顺序、焦点样式；在浏览器中用 `data-platform="windows"` 预览亮/暗两种主题并截图；axe 无严重问题。
4. **Windows 构建**：`scripts/desktop/build.ps1` 在 VM 中产出安装包；记录每一步命令、耗时、产物大小。
5. **本机 Origin 模式**：在 VM 中用真实 Origin 跑通——分析页导出与绘图工作室导出各一次，OPJU 重新打开核验通过，图页样式与 macOS 经 Bridge 生成的一致（对比 PNG），自建实例全部退出、未触碰用户实例。
6. **Windows 自测**：`scripts/desktop/selftest.ps1`（启动、后端就绪、下载到“下载”文件夹不覆盖、单实例、退出时后端结束）；Windows 上运行 Python 测试与前端测试；E2E 至少跑 Chromium 项目（WebView2 基于 Chromium）。
7. **文档**：`docs/WINDOWS.md`（结构、构建、安装、与 macOS 差异、已知限制）、`docs/DESIGN_SYSTEM.md` 的 Fluent 2 一节、`docs/DECISIONS.md` 新条目、`docs/PROJECT_STATUS.md` 进度、应用内“使用说明”（`apps/web/src/pages/Help.tsx`）中平台相关的说明与快捷键。

阶段证据集中到 `reports/data/windows/<运行标识>/`：环境盘点、脱敏构建日志、产物清单、数值对比 JSON、Origin `result.json`、安装与卸载结果、亮暗主题截图。测试证明失败时先修复并重跑受影响项；没有新增改动或失败原因时，不反复重跑已经通过的全部检查。

### 8. 验收标准

- macOS：`make check`、`make e2e`、`make desktop`、`make desktop-selftest` 全部通过（附输出摘要）。
- Windows（VM）：安装包可安装、启动、导入 `fixtures/import` 中的合成数据并完成单轴拉伸分析；导出图片 3216 × 2280 px；下载、单实例、退出正常；卸载后不残留进程。
- 同一合成数据在 macOS 与 Windows 上的分析结果数值一致（列出对比）。
- 本机 Origin 模式：真实 OPJU 生成、重新打开核验通过；有截图（`prlctl capture "Windows 11"`）与 `result.json`；不在 Origin 中留下自建实例。
- 界面：Fluent 2 主题在亮/暗模式、125%/150% 系统缩放下布局正常，键盘可完成主流程。
- 凭据：在 Windows 凭据管理器真实写入、读取和删除本任务临时凭据，API 响应仅返回是否设置；无权限时清楚报错，不能回退为明文存储。
- 生命周期：正常关闭和异常结束外壳均无本次孤儿进程；测试前已有的 Origin 实例仍在。缺少 Origin、没有外网和代理启用三种情况下，独立分析及普通导出可用。
- 视觉验证分开记录浏览器的 CSS 预览、实际 WebView2 窗口、Windows 系统缩放和原生标题栏效果。浏览器修改 `data-platform` 的截图不能冒充 Windows 原生验收。
- 跨平台数值比较使用同一版本的合成输入及参数，按量纲给出误差与合理容差；不要求 OPJU、字体栅格、PNG 字节或计算时间完全相同。默认导出尺寸按实际 `PlotSpec` 验证，默认论文图为 3216 × 2280 px，用户自定义尺寸另算。

### 9. 汇报方式

每个阶段结束时用中文简要汇报：做了什么、验证命令与结果、未完成或未验证的部分及原因、需要用户决定的事项（附推荐）。最终汇报列出分支上的提交、产物路径、全部已知限制。遇到安装软件、改变既有决定、签名证书或是否合并等事项时，提出具体选项并等待相应授权；授权到达前继续不依赖该决定的工作。不得把“源码适配完成”写成“Windows 安装包已验收”。

### 10. 常见陷阱

- PyInstaller 不能跨平台打包：Windows 后端必须在 Windows（x64 Python）上构建。
- `prlctl exec` 的会话不是用户图形会话：Origin、WebView2 自测必须经 `scripts/vm/run_user.sh` 在用户会话中运行；`prlctl exec` 输出为 GBK 编码。
- WebView2 的 Ctrl+R、F5、Ctrl+P、Ctrl+F 等默认快捷键会与应用冲突，需逐一决定拦截或保留。
- 隐藏的 Origin 实例中读到的窗口状态全是“隐藏”，判断工程打开效果必须用可见实例（见 `docs/ORIGIN_BRIDGE.md` §6.1）。
- LabTalk `exist()` 识别不了图形文字对象；字符串赋值中的 `%(n)` 会被立即替换。
- 不要把 Bridge Token、API Key 写进日志、设置文件或数据库。
- Rust 的调试字符串不是通用 JSON 编码，Windows 路径和中文内容传给 JavaScript 时用 JSON 序列化。
- Windows 的父 PID 不会像 POSIX 那样在父进程退出后自动变化；只移植 `os.getppid()` 监视逻辑会留下后端。
- Tauri 的基础配置仍以 macOS 资源为默认值；交叉编译时必须检查合并后的资源和安装目标，不能把 ARM64 macOS 后端装入 x64 Windows 包。

### 11. 官方资料入口（2026-10-28 已查阅）

- [Tauri Windows 安装包与 macOS 交叉构建](https://v2.tauri.app/distribute/windows-installer/)：NSIS、离线 WebView2、交叉构建限制。
- [Tauri 配置](https://v2.tauri.app/reference/config/)：平台覆盖文件、NSIS 安装模式和窗口效果；以仓库安装的 CLI Schema 为最终校验依据。
- [PyInstaller 手册](https://pyinstaller.org/en/stable/)：Python 应用须在目标系统冻结，不能跨操作系统构建。
- [Fluent 字体](https://fluent2.microsoft.design/typography)、[形状与圆角](https://fluent2.microsoft.design/shapes/)：区分 Windows 与 Web 的字号表，记录本项目的密度取舍。
- [Rust Windows MSVC 目标](https://doc.rust-lang.org/rustc/platform-support/windows-msvc.html)、[Microsoft C++ 构建工具](https://learn.microsoft.com/en-us/cpp/overview/acquire-msvc)：核对目标、宿主和所需 SDK 组件。
