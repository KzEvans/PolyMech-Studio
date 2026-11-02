# Windows x64 构建验收记录

运行日期：2026-10-28。打包源码：`1c6b97f17e214b5b72c93edec6e58d7fcb56b05a`（功能代码 `70637b9`，追加 Python 运行时许可），分支 `windows-build`。原有命名与审查修复已在 `main` 的 `cfaff93`。用户要求 Mac 版不用动后，没有再构建、自测或替换 Mac 应用；既有 Mac 数据库的只读 SHA-256 与开始时一致，见 `macos-preservation.json`。

## 产物

Windows 11 ARM64 虚拟机内以 x64 Python、x64 Rust/MSVC 构建，安装包为 0.1.0 x64 NSIS。`artifacts.json` 记录安装包、源码归档和三个可执行程序的 SHA-256；安装后的后端与 Bridge 与构建产物逐字节一致。外壳仅有 Tauri 的 `__TAURI_BUNDLE_TYPE_VAR_UNK` → `..._NSS` 三字节打包标记变化，其余全部字节一致，交付组件哈希按已安装的 NSIS 载荷记录。

安装包在 Mac 的 `build/windows/artifacts/`，在 VM 的 `C:\PolyMechBuild\src\apps\desktop\src-tauri\target\x86_64-pc-windows-msvc\release\bundle\nsis\`。程序已在 VM 用户目录重新安装，验收窗口已关闭。

## 已通过

| 项目 | 结果与证据 |
| --- | --- |
| Python、格式与类型检查 | 311 通过、1 项 macOS 登录 shell 测试跳过；Ruff、格式检查与 mypy 通过。`windows-final-python-checks.log` |
| 前端 | Vitest 9；Windows Chromium E2E 13/13，包含命名、版本、数据修正、删除、绘图、报告及材料数据库。亮暗主题 axe 无严重/关键问题。`windows-quality.log`、`windows-chromium-e2e.log` |
| 冻结程序 | 中文数据路径；单轴、DMA、文献、报告与 PNG/SVG/PDF 导出。默认 PNG 3216 × 2280。`frozen-acceptance/` |
| 本机 Origin | 两条实际导出接口生成 OPJU，并重新打开核验通过。`frozen-acceptance/analysis/`、`frozen-acceptance/plot-studio/` |
| 数值对照 | 同一输入哈希和参数；42 项数值均在量纲容差内。读取此前 Mac 合成结果，没有重新运行 Mac 应用。`numeric-comparison.json` |
| 凭据 | Windows 凭据管理器临时写入、读取、删除通过；没有输出凭据值。`native-windows.json` |
| 桌面自测 | 实际安装后启动、链接/blob 下载、重名追加编号、哨兵不覆盖、单实例及正常退出回收通过。`installed-desktop.log`、`desktop-final-2/` |
| 生命周期 | 对自建 Origin 注入崩溃后可重连，运行中取消成功；硬结束外壳后回收 API、Bridge 与 Origin，重启提示导出中断。`lifecycle.json`、`lifecycle-final-3/` |
| 覆盖安装与卸载 | 同版本更新、卸载、重装均通过；18 个合成文件（含实验库、曲线、原始数据、配置和哨兵）哈希保留。`installer.json` |
| 真正断网 | 唯一 net0 临时断开，活动网卡为 0 且宿主 TCP 不可达；冻结程序分析、报告和三种普通导出通过；随后恢复网络。`offline-network.json`、`SYNTHETIC-offline-1/` |
| 原生窗口 | 最终安装版 WebView2 亮/暗截图、系统标题栏与菜单。`native-final-*-app.png`、`native-final-*-desktop.png` |

测试开始时其他 Origin 实例为空；结束后仍为空。PID 重用拒绝清理另有单元测试，不能把空集合的保持检查视为真实用户实例并存测试。

## 尚未验收及限制

- 125%/150% 实际系统缩放、原生窗口的完整键盘主流程仍待人工确认。界面控制能读取画面，操作虚拟机窗口坐标时返回无可用窗口；没有用浏览器缩放代替系统缩放。
- 已测中文数据目录；没有创建中文用户名的新 Windows 账户。尚未在实体 x64 Windows 或 Windows 10 验证。
- 安装包未签名；Origin demo 水印仍按既有决定保留。无 Origin 的降级使用模拟检测测试，未卸载用户的 Origin。
- 升级验证是同版本不同构建的覆盖安装，未验证任意历史版本迁移。

## 验收中修复的问题

Windows 原始归档文件的只读属性阻止显式删除；PowerShell 5.1 将原生 stderr 进度误作失败；仿真环境的页面刷新超过默认等待；WebView2 的多次自动下载权限影响自测。相关修复和测试均在源码中，下载自测每次窗口验证一种下载，没有放宽 WebView2 权限。

真实故障注入还发现 `originpro 1.1.15` 在 COM Exit 失败后保留失效共享代理，导致后续任务无法重连。`70637b9` 修复代理释放，并通过单元测试和真实崩溃→重连→取消链验证。测试最初以未注册模板作为失败样例，但既有模板系统会正确回退；已改为终止经 PID、创建时间和 `-Embedding` 验证的自建实例。

Python 运行时 `LICENSE.txt` 已纳入安装包与许可归档。许可重打包保持三个程序的可执行代码不变，安装、卸载与数据保留检查已对最终包重新验证。

临时源码下载、官方依赖中转和产物接收服务均已关闭；VM 网络恢复，原远程 Bridge 健康检查通过，应用及本次 Origin 进程均已退出。
