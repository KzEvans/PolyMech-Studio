# macOS 桌面版（Tauri 2）

SPEC §2.1 的“桌面封装”（Could 项，“桌面安装包”），2026-10-26 经用户同意实现；Rust 工具链经用户同意安装。

## 1. 结构

```
PolyMech Studio.app
├─ Contents/MacOS/polymech-studio      Tauri 2 外壳（Rust，系统 WKWebView）
└─ Contents/Resources/
   ├─ backend/polymech-backend/        PyInstaller onedir：FastAPI 后端 + 计算引擎 + Matplotlib
   └─ web/                             前端构建产物（pnpm build）
```

- 启动：外壳显示内置启动页 → 启动后端子进程 `polymech-backend --static Resources/web`（只监听 127.0.0.1 的随机空闲端口）→ 后端打印 `POLYMECH_PORT=<端口>` → 窗口导航到 `http://127.0.0.1:<端口>/`。启动失败或 240 s 超时时，启动页显示原因与日志路径。
- 退出：外壳退出时结束后端；外壳异常消失时，后端检测到父进程变化后在 1 s 内自行退出（`polymech_api.desktop.watch_parent`）。
- 界面与网页版是同一份前端；后端在桌面模式下同时提供 `/api/*` 与界面文件（客户端路由回退到 `index.html`，不提供界面目录之外的文件）。
- 界面页面没有 Tauri IPC 权限（capabilities 为空）；原生菜单通过 `webview.eval` 派发 `polymech:menu` DOM 事件，由页面处理。

## 2. 与网页版的差异

| 项 | 桌面版做法 |
|---|---|
| 菜单与快捷键 | 原生中文菜单：设置 ⌘,、导入 ⌘O、概览…报告 ⌘1–⌘6、侧边栏 ⌘⌥S、重新计算 ⌘R、重新载入 ⌘⇧R、在 Finder 中显示数据文件夹/日志、编辑（拷贝/粘贴等）、窗口 |
| 下载（CSV、图片、报告、配置） | WebKit 下载由外壳接管，保存到 `~/Downloads`，重名时加 “(n)”，不覆盖；完成后页面提示文件名 |
| 拖放 | 关闭外壳的文件拖放拦截，页面照常接收 HTML5 拖放（导入、绘图工作室） |
| 命令行工具 | 从 Finder 启动的 App 只有系统最小 PATH；后端启动时读取登录 shell 的 PATH 并补充 `/opt/homebrew/bin`、`/usr/local/bin`、`~/.local/bin` 等，以找到 `prlctl`、`codex`、`claude` |
| 数据目录 | 默认 `~/Library/Application Support/PolyMechStudio`（可用 `POLYMECH_DATA_DIR` 覆盖）；日志 `~/Library/Logs/cn.edu.zju.polymech.studio/backend.log` |
| 单实例、窗口位置 | `tauri-plugin-single-instance`（再次打开时聚焦已有窗口）、`tauri-plugin-window-state` |
| Matplotlib 字体缓存 | PyInstaller 的运行时钩子每次启动都把缓存放到新临时目录（每次重建约 30–60 s）；入口脚本改为 `~/Library/Caches/PolyMechStudio/matplotlib`，只在第一次启动时建立 |

## 3. 构建与自测

```bash
make desktop            # scripts/desktop/build.sh：前端 → PyInstaller 后端 → tauri build（.app + .dmg）
make desktop-selftest   # scripts/desktop/selftest.sh
```

- 依赖：Rust stable（rustup 安装在 `~/.cargo`，未改动 shell 配置文件；脚本自行加入 PATH）、`@tauri-apps/cli` 2.12.4（`apps/desktop/package.json`）、PyInstaller（uv dev 依赖）。
- 产物：`apps/desktop/src-tauri/target/release/bundle/macos/PolyMech Studio.app`、`.../dmg/PolyMech Studio_0.1.0_aarch64.dmg`。
- 自测在类似 Finder 的最小环境中启动打包后的 App（临时数据目录、临时下载目录）：后端烟雾测试（`scripts/desktop/smoke.py`：全新数据库迁移、导入、单轴计算、PNG/SVG 导出、文献导入、DMA、报告、命令行工具检测）、两类下载（链接与 JavaScript Blob）、退出后无残留后端进程。

## 4. 实测（2026-10-26，本机 macOS 27.2 arm64）

| 项 | 结果 |
|---|---|
| 构建耗时（首次，含 Rust 依赖编译） | 3 min 23 s |
| `.app` / `.dmg` 体积 | 365 MB / 132 MB |
| 后端启动（首次，建立字体缓存） | 约 67 s |
| 后端启动（之后） | 1.6–3 s |
| `make desktop-selftest` | 通过：烟雾测试、两类下载、退出后后端结束 |
| 人工检查 | 原生窗口与中文菜单正常；“显示”菜单导航正常；设置页检测到 Codex/Claude CLI 与 Parallels 虚拟机；报告页在窗口内显示 |

## 5. 已知限制

- **未签名、未公证**：本机没有 Apple Developer ID，使用 ad-hoc 签名。本机自用没有问题；拷到其他 Mac 时首次需右键 →“打开”。分发需付费开发者账号签名与公证（`tauri.conf.json` 的 `signingIdentity` 与公证环境变量）。
- **只构建了 Apple Silicon（aarch64）**；Intel Mac 需另行构建（或 universal）。
- **体积**：Tauri 复制资源时把 PyInstaller 目录中的 29 个符号链接展开成文件（251 MB → 357 MB）。可在打包后用保留链接的方式替换并重新签名，暂未做。
- 首次启动约 1 分钟（字体缓存），启动页有提示。
- 桌面版本身没有 Playwright E2E（界面与网页版相同，由网页版 E2E 覆盖）；外壳行为由 `make desktop-selftest` 与人工检查覆盖。
