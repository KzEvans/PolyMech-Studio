# Windows 桌面版构建与验证

更新：2026-10-28。Windows x64 安装包已构建并安装验收，双入口 Origin 导出、故障恢复、断网与卸载保留数据检查通过；125%/150% 系统缩放及原生完整键盘主流程待人工验收。完整证据在 `reports/data/windows/20261028-x64/`。

执行约定见 [Windows 构建提示词](codex/WINDOWS_BUILD_PROMPT.md)。已经验证的修复保存在 `main` 的 `cfaff93`；Windows 工作在 `windows-build`，提示词提交为 `6d1a30e`。

## 初始盘点（安装构建工具前）

| 项目 | 2026-10-28 只读检查结果 |
| --- | --- |
| 构建发起端 | Apple Silicon Mac，已有 Rust、Node、pnpm、uv，Rust 仅安装 `aarch64-apple-darwin` 目标 |
| Windows | 已运行的 Parallels `Windows 11`，ARM64，`10.0.26300` |
| x64 Python | 现有 Bridge 的 CPython `3.12.15` AMD64，`originpro 1.1.15` |
| Origin | OriginPro 2025b `10.25.212`；盘点时有三个用户实例，均非 `-Embedding`；用户随后明确授权关闭并重启，三个实例已按 PID 结束 |
| WebView2 | 已安装 `155.0.4283.62` |
| Windows 构建工具 | 未找到 Rust、MSVC、Node、pnpm、uv、Git 或 NSIS |
| macOS 交叉构建工具 | 未找到 NSIS、LLVM 的 `llvm-rc`、LLD 或 `cargo-xwin` |
| 可用空间 | Mac 和虚拟机各报告约 27 GiB；VM 磁盘依赖宿主磁盘，不能把这两项相加作为可用空间 |

盘点通过现有 `scripts/vm/run_user.sh` 在登录用户会话中隐藏执行，未安装工具，未关闭 Origin，未读取密钥。

## 构建路径与已授权的安装清单

用户已在当前会话批准 A 方案。MSVC 安装器为 `17.14.37824.6`，SHA-256 为 `4aad1082e180f558598c346eb105b465b4908148cb9f7f0511aa1105620e0c30`。安装返回 3010。用户随后授权关闭 Origin 并重启；已重启，MSVC 编译、链接和运行最小 C 程序通过。B 方案仅作为已说明的备选，没有获得安装授权。

两条路径都复用已有 x64 Python，在新建的项目构建环境中安装锁定依赖，使用 PyInstaller 冻结后端和本机 Bridge。原 Bridge 的环境、任务与配置继续保留。Windows 上的实际安装、WebView2 和 Origin 验收也不可省略。[PyInstaller 的目标系统要求](https://pyinstaller.org/en/stable/)

### A. Mac 调度 Windows 虚拟机构建

这条路径优先使用 Tauri 的 Windows 原生构建流程。Mac 负责源码、界面开发和调度，Windows 负责 x64 打包。[Tauri Windows 构建](https://v2.tauri.app/distribute/windows-installer/)

| 工具 | 拟用版本与来源 | 下载和空间预算 | 安装位置 |
| --- | --- | --- | --- |
| Visual Studio Build Tools | 2022 17.14 稳定系列，MSVC v143、Windows SDK 10.0.26100；[Microsoft 官方](https://aka.ms/vs/17/release/vs_buildtools.exe) | 引导程序 4.47 MB；选定 C++ 组件约 3–5 GiB 下载、6–9 GiB 安装，均为估算；安装前记录引导程序与组件清单 | `C:\PolyMechBuild\BuildTools`；安装器共享组件采用 Microsoft 默认目录 |
| Rust | `1.99.1`，`x86_64-pc-windows-msvc`；[Rust 官方](https://www.rust-lang.org/tools/install) | 约 0.5–0.8 GiB 下载、1.5–2.5 GiB 安装，估算 | 用户的 `%LOCALAPPDATA%\PolyMechBuild\tools\rust` |
| Node | `24.22.1` LTS x64 ZIP；[Node 官方](https://nodejs.org/dist/v24.22.1/) | 37,748,064 字节下载，解压约 0.1 GiB | 用户的 `%LOCALAPPDATA%\PolyMechBuild\tools\node` |
| pnpm | `12.14.0`，与 Mac 已用版本一致；[npm 官方注册表](https://registry.npmjs.org/pnpm/12.14.0) | 包解压约 4.2 MB；项目依赖另计 | 用户的 `%LOCALAPPDATA%\PolyMechBuild\tools\pnpm` |
| uv | `0.13.6` x64；[Astral 官方发布](https://github.com/astral-sh/uv/releases/tag/0.13.6) | 15,239,500 字节 ZIP；解压约 0.05 GiB | 用户的 `%LOCALAPPDATA%\PolyMechBuild\tools\uv` |
| 构建与测试依赖 | `uv.lock`、前端锁文件及现有 Bridge requirements 中的版本；PyInstaller、Tauri 管理的 NSIS 和离线 WebView2 安装文件 | 环境、下载缓存、Rust 编译输出合计另预留约 4–6 GiB，估算 | 独立构建目录 `C:\PolyMechBuild\src` 及工具各自的项目缓存 |

不安装完整 Visual Studio IDE，不安装新的系统 Python，不新增 Git 远端或 CI。构建目录与环境变量只用于本次项目，不改写全局 PATH。预算上限接近当前空间余量，安装前再次检查，空间不足则调整构建路径或请求用户决定。

### B. Mac 交叉编译外壳和 NSIS

可减少虚拟机中的编译工具，但官方说明这条路径验证较少，需要先证明最小外壳能构建。[Tauri 交叉构建说明](https://v2.tauri.app/distribute/windows-installer/#build-windows-apps-on-linux-and-macos)

| 工具 | 拟用版本与来源 | 下载和空间预算 | 安装位置 |
| --- | --- | --- | --- |
| LLVM 与 LLD | LLVM `23.1.4`；[Homebrew 官方公式](https://formulae.brew.sh/formula/llvm) | 约 0.5–1 GiB 下载、2–4 GiB 安装，估算 | `/opt/homebrew/Cellar/llvm` |
| NSIS | `3.12`，Homebrew 公式名 `makensis`；[官方公式](https://formulae.brew.sh/formula/makensis) | 约数 MB 下载、数十 MB 安装，估算 | `/opt/homebrew/Cellar/makensis` |
| Rust Windows 目标 | 为现有 Rust 增加 `x86_64-pc-windows-msvc` | 约数十 MB 下载、0.1–0.2 GiB 安装，估算 | 当前用户的 rustup 工具链 |
| cargo-xwin | `0.23.1`；[项目](https://github.com/rust-cross/cargo-xwin) | 工具及编译缓存约 0.3–1 GiB，估算 | 当前用户 `.cargo/bin` |
| Windows SDK 与 CRT | `cargo-xwin` 从 Microsoft 下载并提取，编译前记录所选版本和许可要求 | 约 1–3 GiB 缓存，估算；Tauri 输出和测试依赖另计 | `build/windows/xwin-cache` |

这条路径仍需 Windows 项目虚拟环境和冻结工具。当前没有执行上述任一安装，也未默认接受 SDK 许可。

## 实施顺序

1. 统一数据、缓存、路径和启动环境，补齐 Windows 凭据存储与父进程监视。
2. 统一前端平台判断、快捷键和 Fluent 2 令牌，保持 macOS 外观与数据契约。
3. 实现可复现的 Windows 构建、自测和本机 Origin 启动入口。
4. 获得对应工具清单许可后构建，完成实际安装与 Origin 验收。
5. 记录最终产物、校验值和限制。用户后续要求 Mac 版不用动，沿用此前 Mac 回归结果，不再重建、自测或替换 Mac 应用。

## 运行结构与目录

- 用户数据：`%APPDATA%\PolyMechStudio`。原始文件只读归档；实验与分析版本使用同一 SQLite 契约。
- 日志、Matplotlib 缓存与本机 Origin 临时任务：`%LOCALAPPDATA%\PolyMechStudio`。
- 程序：`%LOCALAPPDATA%\Programs\PolyMech Studio`。安装包按用户安装，附带离线 WebView2 安装程序和 VC 运行库。
- Windows 凭据保存在系统凭据管理器；API 只报告是否设置。环境变量仍有优先权。
- Origin 从 32/64 位注册表视图检测。后端按需启动独立 Bridge，随机 loopback 端口、每次随机令牌；令牌只在子进程环境中传递。本机连接不使用代理。旧远程 Bridge 环境与自启配置保留。
- Origin 取消和退出仅清理本次记录的 `-Embedding` PID 与创建时间。普通分析及 Matplotlib 导出不依赖 Origin。

## 复现构建与测试

源码放在 `C:\PolyMechBuild\src`，包含锁文件和 `.gitignore`；项目 Python 环境位于相邻 `venv`。不要复制 Mac 的 `.venv`、`node_modules`、用户数据库或后端产物。

```powershell
# 已按批准清单安装工具后，在登录用户会话执行：
powershell -NoProfile -File scripts\desktop\build.ps1
powershell -NoProfile -File scripts\desktop\selftest.ps1 `
  -Exe "$env:LOCALAPPDATA\Programs\PolyMech Studio\polymech-studio.exe"
C:\PolyMechBuild\venv\Scripts\python.exe scripts\desktop\windows_acceptance.py `
  --backend build\desktop\backend\polymech-backend\polymech-backend.exe `
  --bridge build\desktop\bridge\polymech-bridge\polymech-bridge.exe `
  --work C:\PolyMechBuild\acceptance\SYNTHETIC-fresh --origin
C:\PolyMechBuild\venv\Scripts\python.exe scripts\desktop\windows_lifecycle.py `
  --exe "$env:LOCALAPPDATA\Programs\PolyMech Studio\polymech-studio.exe" `
  --work C:\PolyMechBuild\acceptance\lifecycle-fresh
```

`build.ps1` 从 `vcvars64.bat` 导入局部编译环境，明确选择 x64 Rust 与 `win-amd64` Python，使用锁文件安装依赖，再生成后端、Bridge、许可清单和 NSIS。`-SkipChecks` 仅供同一源码已另行通过检查时使用。不要用 Windows ARM64 的 `platform.machine()` 判断 x64 Python 架构；以 `sysconfig.get_platform()` 和指针宽度验证。

Windows PowerShell 5.1 会把重定向的原生 stderr 包装为错误记录，构建脚本按原生退出码判断。含中文字符串的临时 PowerShell 脚本使用 UTF-8 BOM，读取日志显式使用 UTF-8。`run_user.sh` 经独立隐藏任务运行，避免在用户桌面弹控制台。

下载自测将链接与 blob 分别放在新的 WebView2 会话中，验证重名文件追加 `(1)` 且不覆盖哨兵文件。多个无用户手势的自动下载受 WebView2 权限限制；未放宽运行时权限。[Microsoft 权限枚举](https://learn.microsoft.com/en-us/dotnet/api/microsoft.web.webview2.core.corewebview2permissionkind)

## 验证记录（持续更新）

| 项目 | 实际结果 |
| --- | --- |
| Mac 此前回归 | Python 306、力学 109（覆盖率 93.09%）、Vitest 9；WebKit/Chromium 22；桌面构建与自测通过。用户要求后不再执行 Mac 应用构建或自测，已安装 Mac 应用保持 `cfaff93` |
| Windows 代码检查 | Ruff、格式检查、mypy 71 个源码、Vitest 9 通过 |
| Windows Python | 最终完整套件 311 通过、1 项 POSIX 专用测试跳过；包含本机错误提示与重启任务恢复测试 |
| Windows Chromium | 13/13，通过导入、分析、版本比较、数据修正、绘图与材料数据库流程，亮暗主题 axe 无严重或关键问题 |
| 原生凭据 | 临时凭据真实写入、读取、删除；父进程句柄等待通过 |
| 冻结程序 | 迁移、中文路径合成数据、单轴拉伸/DMA、报告、PNG/SVG/PDF 通过；PNG 3216 × 2280 |
| 本机 Origin | 分析页与绘图工作室两条导出接口均生成真实 OPJU，并重新打开核验通过；正常关闭后自建 Origin 无残留。测试开始时没有其他 Origin 实例 |
| 数值比较 | 与此前 Mac 合成输入及参数完全一致；42 项数值均满足记录的量纲容差，见 `numeric-comparison.json` |
| 生命周期 | 真实 Origin 崩溃后恢复、运行中取消、外壳硬结束时回收和重启中断任务提示均通过；`origin_before` 与 `origin_after` 均为空 |
| 安装 | 最终 NSIS 按用户安装；链接/blob 下载不覆盖、单实例和正常退出回收通过。同版本覆盖安装、卸载与重装保留 18 个合成文件的全部哈希，重装后组件哈希一致 |
| 断网 | 临时断开唯一网卡 net0，活动网卡数为 0、无法连接宿主 TCP；冻结程序独立分析、报告及 PNG/SVG/PDF 通过；已恢复网卡并复核原 Bridge 健康状态 |
| 原生界面 | 最终安装版 WebView2 亮/暗截图、系统标题栏与窗口内菜单已观察；系统 125%/150% 缩放和完整原生键盘流程尚未验收。虚拟机仅提供代理辅助功能树，坐标输入报无可用窗口，未使用其他界面自动化方式 |

Windows 官方下载遇到 DNS 失败时，构建临时使用绑定 Parallels 共享接口且限制 VM 与官方依赖站点的 CONNECT 中转。只设置构建进程代理，不修改系统代理、DNS 或防火墙，结束后已关闭中转、源码下载与产物接收服务（18766–18769），并恢复 VM 原网络连接。

## 实际工具链

Python 3.12.15 `win-amd64`、PyInstaller 6.22.3、Rust 1.99.1 `x86_64-pc-windows-msvc`、MSVC 14.44.35207、SDK 10.0.26100、Node 24.22.1、pnpm 12.14.0、uv 0.13.6、NSIS 3.13。依赖版本及许可清单随安装包分发，完整环境在 `environment.json`。

## 产物与源码归属

构建源码提交：`1c6b97f17e214b5b72c93edec6e58d7fcb56b05a`。源码归档 `polymech-1c6b97f.zip` 的 SHA-256 为 `8e104c6e79b21d683d7245a827b0fb8a018bf65a1d5ded14e559e0ed41dcdb5f`。外壳与后端代码沿用 `2e6e872`，本次追加修复本机 Origin 崩溃后的连接释放；Bridge 已重新冻结；`1c6b97f` 补齐 Python 运行时许可，最终安装包重新打包。安装包校验值与三个可执行程序的校验值记录在证据目录的 `artifacts.json`。

最终文件 `build/windows/artifacts/PolyMech-Studio-0.1.0-windows-x64-setup.exe`，319,342,308 字节，SHA-256 为 `d827f6965370946337b3fe50c0acba7a3bff6e5e12f9ee19755f4d5154bd89a8`。安装目录为 `%LOCALAPPDATA%\Programs\PolyMech Studio`。

组件检查按已安装的 NSIS 载荷记录：Tauri 在外壳写入 `UNK → NSS` 三字节包类型标记；核对这个固定标记后，其余所有字节一致。后端与 Bridge 无差异。未打包外壳哈希另存在 `build_components`，见 `installed-components.json` 与 `component-verification.json`。

Windows 本机故障注入发现 `originpro 1.1.15` 在 COM Exit 抛错时保留失效的 `APP._app`。Bridge 先尝试抑制保存提示和退出，再释放这个共享代理；即使首次启动阶段失败也进入同一清理流程。依赖版本固定，单元测试与真实故障注入验证后续任务能重新创建实例。没有修改旧远程 Bridge 的安装环境。

## 限制

- 安装包未签名，未通过 SmartScreen 信誉认证。Windows 上运行安装器前先核对本页 SHA-256；若显示 SmartScreen，由用户核实来源并决定是否通过“更多信息”继续。系统安全确认由用户处理，验收没有关闭 Defender、修改安全策略或绕过警告。
- 125%/150% 实际系统缩放及原生完整键盘流程待人工验收；已测中文数据目录，未创建中文用户名账户。
- 真实运行平台为 Windows 11 ARM64 的 x64 仿真；尚未在实体 x64 Windows 电脑或 Windows 10 验证。
- Origin 的 demo 水印仍按已有决定暂时忽略；需用户自己的有效 Origin 许可。
- 当前产品版本为 0.1.0；覆盖安装验收使用同版本的新构建，不能代表任意历史版本迁移。
