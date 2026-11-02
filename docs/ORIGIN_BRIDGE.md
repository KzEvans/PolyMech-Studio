# Origin Bridge

> 状态：**SPEC §6.7 十步端到端验收已在真实 Origin 中通过（2026-10-26，见 §4）**。未解决问题：
> ① 自动化实例导出的图带 “demo” 水印（许可状态，需用户确认，见 §2.2）；② `op.exit()` 不能使实例自行退出，Bridge 在工程保存核验后只结束自建 `-Embedding` PID（见 §2.3）。
> 本文件只记录已实际执行的验证；未完成项明确标注。

## 1. 实测环境（2026-10-25）

| 项目 | 实测结果 | 方法 |
|---|---|---|
| macOS | 27.2 (26B5101f)，arm64 | `sw_vers`, `uname -m` |
| Parallels Desktop | 27.0.0 (58628)，`/usr/local/bin/prlctl` | `prlctl --version` |
| VM | `Windows 11`，running，Guest Tools 27.0.0 已安装 | `prlctl list -i` |
| VM 网络 | Shared，Mac `bridge100`=10.211.55.2，VM=10.211.55.5（**不硬编码，运行时探测**） | `ifconfig`, `prlctl list -i` |
| 共享 | Host Shared Folders 关；Shared Profile 开；`C:\Mac\Home` → `\\psf\Home` 仍可访问 | `dir C:\Mac` |
| Windows | 10.0.26300，**ARM64** | `ver`, `%PROCESSOR_ARCHITECTURE%` |
| Origin | **OriginPro 2025b**（Origin64.exe FileVersion 10.2.5），`C:\Program Files\OriginLab\Origin2025b\` | PE 版本信息 |
| Origin64.exe 架构 | **x64（PE machine 0x8664）**，在 Windows on ARM 上走 x64 仿真 | 读取 PE 头 |
| Origin 内嵌 Python | 3.11.0 (AMD64)，`originpro` 位于 `C:\ProgramData\OriginLab\102b\PyPackage\Py3`（来自用户另一项目留下的探测记录，本项目尚未独立复现） | 只读查看 |
| COM ProgID | `Origin.Application`、`Origin.ApplicationSI` 已注册 | `reg query HKCR` |
| Windows 防火墙 | Domain/Private/Public 均开启；Mac→VM ICMP 不通（默认行为） | `Get-NetFirewallProfile`, `ping` |

### 1.1 `prlctl exec` 执行上下文

- 默认：`NT AUTHORITY\SYSTEM`，session 0，System 完整性级别。**不能**用于 Origin。
- `--current-user`：`P335\kzevans`，**session 1（console）**，Medium 完整性，非提权；登录会话 ID（357508）与 explorer.exe 的（357703/357772）不同。
- 每次 `--current-user` 调用会在用户桌面打开一个控制台窗口且不自动关闭——**已弃用**，见 §2.4。
- 单条命令长度上限约 3–4k 字符；`prlctl exec` 会读取 stdin（循环中需 `</dev/null`）；偶发 `PrlJob_GetResult: Invalid argument`（瞬时，重试即可）。
- 文件传输工具：`scripts/vm/push_file.sh`（分块 base64 + 大小核对）、`scripts/vm/pull_file.sh`；SYSTEM 上下文脚本：`scripts/vm/run_ps.sh`。
- 在用户**真实交互登录令牌**中无窗口运行：`scripts/vm/run_user.sh`（见 §2.4）。

### 1.2 Bridge Python 环境（本项目创建，全部位于 `%LOCALAPPDATA%\PolyMechBridge`）

- `bridge/windows-origin/setup_env.ps1`：uv 0.13.5（x86_64 build）→ CPython **3.12.15 x86_64**（`--no-bin`，不写全局 shim）→ venv。
- 已安装：`originpro 1.1.15`、`OriginExt 1.2.6`、`pywin32 312`、`numpy 2.5.4`。
- 选择 x64 的依据：PyPI 上 `OriginExt 1.2.6` 只有 `win32`/`win_amd64` wheel，**没有 win_arm64**；Origin 本身也是 x64。
- 首次运行时 uv 在 `C:\Users\kzevans\.local\bin` 写了 `python3.12.exe` shim；已删除该 shim 及其（本次新建且为空的）目录，脚本已改为 `--no-bin`。

## 2. 最小链路验证记录

测试脚本：`bridge/windows-origin/phase0_origin_smoke.py`（合成 neo-Hookean 数据，明确标注 SYNTHETIC）。

| # | 尝试 | 结果 |
|---|---|---|
| 1 | 外部 `originpro`（`OriginExt.Application()` 新建实例），prlctl `--current-user` | **失败**：约 120 s 后 `LT_execute` 报“无效指针”；无输出文件；无残留进程 |
| 2 | `win32com DispatchEx("Origin.Application")`（`bridge/windows-origin/com_probe.py`） | **失败**：`0x80080005 CO_E_SERVER_EXEC_FAILURE`（服务器运行失败），120 s |
| 3 | 同 2，监视新进程窗口 | 新 `Origin64.exe -Embedding` 在 ~7 s 弹出模态框：**“The User Files Folder C:\Mac\Home\Desktop\Origin\ is not available currently. The path may be offline.”** |
| 4 | 同 3，但经计划任务在用户真实交互登录令牌中运行 | **相同对话框，相同失败** → 与 prlctl 登录会话无关 |
| 5 | 直接 `CreateProcess` 启动 `Origin64.exe -h -rs "run -pyf ..."`（内嵌 Python 路线，`launch_probe.py`） | **相同对话框**，载荷未执行；240 s 后由启动器终止（仅终止自身创建的 PID） |
| 6 | 同 5，仅对本进程、文字完全匹配的 UFF 提示点“确定” | Origin 随即弹出 **“Select User Files Folder”** 对话框，要求重新指定 UFF（持久配置修改）——**未操作**，进程由启动器终止 |

**结论**：阻塞点不是 ARM/x64 仿真或 COM 本身，而是 Origin 的用户文件夹（UFF，注册表 `HKCU\Software\OriginLab\Origin 10.2b\International\Path` = `C:\Mac\Home\Desktop\Origin\`）在新实例启动时被判定为离线，所有新实例都在启动阶段被模态框阻塞。用户当前已打开的 Origin GUI（PID 1608，10-23 启动）不受影响，但下次重启 Origin 很可能也会遇到同一提示。**需要用户决定处理方式**（见 `docs/PROJECT_STATUS.md` “待用户决策”）。

**处理**：用户于 22:07 将 UFF 改为 `C:\Users\kzevans\origin\`（`Autosave` 等仍指向 `C:\Mac\Home\Desktop\Origin\...`，暂未造成问题）；并授权结束 8 个 10-23 遗留的 `-Embedding` 实例（已按 PID + 命令行 + 创建日期逐一核对后结束）。

| # | 尝试（UFF 修复后） | 结果 |
|---|---|---|
| 7 | `com_probe.py`（DispatchEx） | **成功**：17.8 s 建立连接，`@V = 10.250212`；`Exit()` 后实例不退出 |
| 8 | `phase0_origin_smoke.py`，经计划任务在用户交互会话中**无窗口**运行（`scripts/vm/run_user.sh`） | **通过**：启动 14.5 s；3 个工作簿 + 图页 + PNG(1200×850, 26 KB) + OPJU(56 KB) 共 2.7 s；新实例重开 15.2 s，Raw Data 401 行逐点一致（最大误差 0），图页 1 条曲线。报告：`reports/data/origin/phase0/smoke_report_20261025.json` |
| 9 | 同 8 重复运行，期间 3 次 `prlctl capture` | 通过；用户桌面无任何新窗口出现 |

### 2.2 “demo” 水印（未解决，需用户确认许可）

导出的 PNG 上满布 “demo” 水印 → COM 启动的自动化实例未获得有效许可。许可文件 `C:\ProgramData\OriginLab\License\orglab.lic` 存在（未读取内容）。本项目不会尝试绕过授权。

2026-10-26 用户说明：在其正常启动的 Origin 中把工程保存后再打开一次，水印即消失（即 OPJU 本身可用，水印出现在自动化实例的渲染/导出中）。据此做的实测：

| 尝试 | 结果 |
|---|---|
| 同一自动化实例：保存 OPJU → `op.open` 重新打开 → 再导出图片 | 仍有水印 |
| 新的 COM 实例（隐藏）打开已保存的 OPJU 后导出 | 仍有水印 |
| 新的 COM 实例（可见，`set_show(True)`）打开后导出 | 仍有水印（与隐藏时导出文件字节数相同） |
| 以普通进程启动 `Origin64.exe -h -rs "run -pyf …"` 打开工程并导出 | 180 s 内未完成（疑似被启动对话框阻塞），由脚本结束自建进程 |

结论：经 COM 自动化导出的图片带水印；用户用自己的 Origin 打开 OPJU 后另存/导出可得到无水印图片。按用户指示（2026-10-26）暂时忽略该问题，上述实验代码已撤回，不在当前实现中。

### 2.3 退出行为（未解决）

`op.lt_exec("doc -s;")` + `op.exit()` 后等待 30 s，自建实例仍在。当前策略：工程保存并验证后，仅对“启动前后 PID 差集”中的自建 `-Embedding` 进程 `taskkill /f`。M7 中继续研究优雅退出（如 LabTalk `exit`、释放全部 COM 引用后 `CoUninitialize`）。

### 2.4 无窗口执行

`prlctl exec --current-user` 会在用户桌面打开 Windows Terminal 窗口，且进程结束后窗口不关闭（实测遗留 9 个，已确认均为本项目 22:10–22:12 产生后关闭）。现行方式：
- 文件传输、诊断：`prlctl exec`（SYSTEM，session 0，无窗口）——`scripts/vm/vm_lib.sh`。
- 需要用户会话的任务：SYSTEM 注册一次性计划任务（`LogonType Interactive`）→ `pythonw.exe hidden_run.py`（`CREATE_NO_WINDOW`）→ 结束后删除任务——`scripts/vm/run_user.sh`。

### 2.5 其他发现

- session 1 中有 **8 个** `Origin64.exe -Embedding` 进程（10-23 04:19–04:33 创建，父进程 DcomLaunch），以及用户的 GUI 实例。它们**不是本项目创建的**，本项目不会关闭。推测来源：`originpro` 外部模式在 `atexit` 中只调用 `Detach()`（`Exit(releaseonly=True)`，见 `originpro/config.py`），未显式 `op.exit()` 的脚本会遗留实例。
- 本项目的教训已写入设计：Bridge 必须显式 `op.exit()`，并以“启动前后 PID 差集”核对自己创建的实例，只管理自己的 PID。
- 用户另一项目 `%LOCALAPPDATA%\PolySAXSOrigin` 只读查看过，未修改。

## 3. Bridge 部署（2026-10-26，用户批准后执行）

| 项目 | 内容 | 撤销方式 |
|---|---|---|
| 代码与依赖 | `scripts/vm/deploy_bridge.sh` → `%LOCALAPPDATA%\PolyMechBridge\app` + venv（fastapi/uvicorn/pydantic/originpro） | 删除该目录 |
| 防火墙 | `firewall_rule.ps1`：入站 TCP 8766，**RemoteAddress = 10.211.55.2（Mac）**，规则名 “PolyMech Origin Bridge” | `Remove-NetFirewallRule -DisplayName "PolyMech Origin Bridge"` |
| 自启 | `install_autostart.ps1`：登录时以用户身份隐藏运行 `pythonw -m polymech_bridge`，失败自动重启 3 次 | `uninstall_autostart.ps1` |
| 监听 | 只绑定 VM 的主 IPv4（10.211.55.5:8766），不绑定 0.0.0.0；地址写入 `bridge-endpoint.txt` | — |
| 认证 | 首次启动生成 Token（`token.txt`，用户目录）；Mac 端 `POST /api/origin/pair` 经 prlctl 读取后存入 macOS 钥匙串（服务名 PolyMechStudio）；也可在设置中手动粘贴 | — |
| 重启 | `scripts/vm/restart_bridge.sh`：先 `/v1/shutdown`（Bridge 关闭自建 Origin），等任务退出后再启动 | — |

实测（Mac 侧）：`GET /health` → ok；无 Token 访问 `/v1/capabilities` → 401；配对后 `/api/origin/status` reachable = true，`originpro_importable` = true。

## 4. SPEC §6.7 端到端验收（2026-10-26）

脚本：`scripts/acceptance_origin_e2e.py`（API 运行于 Mac，数据为 SYNTHETIC fixture `SYNTH_uniaxial_gbk_chinese.csv`）。报告与 Origin 原始输出：`reports/data/origin/e2e_20261026/`。

| 步 | 内容 | 结果 |
|---|---|---|
| 1 | macOS 上传单轴拉伸文件 | 405 行；规则识别 time/force/displacement；原始文件 SHA-256 归档 |
| 2 | Python 引擎生成标准化曲线 | run v1，E = 1.1507 MPa（λ∈[1,1.05]），λ_b = 4.0 |
| 3 | 选择模板 | `nominal_stress_stretch` → Origin `line` |
| 4 | 发送任务到 Bridge | HTTP + Token |
| 5 | Bridge 调用真实 Origin | OriginPro 2025b（@V 10.250212），自建实例 |
| 6 | 生成工作簿与图页 | RawData（原始中文列名与原始单位）、Processed、Summary、Metadata（含输入/结果哈希）+ Graph1 |
| 7 | 保存 OPJU | `SYN-E2E_uniaxial_20261026_uniaxial-v1.opju`（文件头 `CPYUA`） |
| 8 | 导出图片 | PNG、PDF、SVG 均成功；Bridge 任务耗时 19.0 s（含首次启动 Origin） |
| 9 | macOS 接收输出 | 下载至 `data/origin/job<N>/`，记录 SHA-256 |
| 10 | 重新打开核验 | ① Bridge 在同一实例 `op.new()` 后只读重开：各表行数、图页曲线数全部一致；② **Mac 收到的文件推回 VM，在全新 Origin 进程中只读打开**（`verify_opju.py`）：4 个工作簿、RawData 405 行 × 3 列（时间/力/位移）、Graph1 含 1 条曲线；核验后无遗留进程 |

总耗时 63.5 s。**结论：通过**（注意导出图带 demo 水印，见 §2.2）。

验收过程中发现并修复的问题：
- `op.new()` 的默认模板会带一个空的 Book1 → 构建前删除默认页面。
- vm 脚本在 UTF-8 locale 下处理 GBK 输出时 `awk`/`tr` 报错 → `vm_lib.sh` 统一 `LC_ALL=C`。
- SQLite 读回的时间不带时区导致文件名日期偏差 → 显式按 UTC 解释再转本地日期。
- 优雅重启时计划任务在旧进程未退出前忽略新启动 → 重启脚本等待任务结束。

## 5. Origin 模板库（SPEC §6.5，2026-10-26）

### 5.1 保存模板命令的确认

`originpro` 只能按路径加载模板（`op.new_graph(template=<path>)`），没有保存模板的函数。在真实 Origin 2025b 中逐一试验（`bridge/windows-origin/probe_template_save.py`）：

| 命令 | 结果 |
|---|---|
| `template_saveas template:="…" path:="…"` | 失败（`lt_exec` 返回 false，无文件；参数名错误） |
| `template_saveas "…\name"` | 失败 |
| `save -t "…\name.otpu"` / `save -t "…\name"` | 失败 |
| `template_saveas pg:=[Graph] template:="name" filepath:="dir"` | **成功**，生成 `name.otpu`，可用 `op.new_graph(template=path)` 重新加载 |

正确的参数名取自 Origin 安装目录 `X-Functions\Utilities\File\template_saveas.OXF` 中的语法说明（`pg`、`category`、`template`、`filepath`、`ftype`、`desc`），未凭记忆假设。

### 5.2 模板与注册表

- 生成：`bridge/windows-origin/make_templates.py` 在自建隐藏实例中由内置模板（line/scatter/linesymb/doubley）新建图页，设置期刊样式（四边闭合框、主次刻度朝内、刻度标签仅下/左、轴标题 Arial、图例无边框；双 Y 右轴层只设刻度朝内，保留其右侧位置），保存为 `.otpu`，再从文件重新加载并逐项读回样式、导出检查图。记录：`reports/data/origin/templates_20261026/`。
- 文件：`templates/origin/pm_line.otpu`、`pm_scatter.otpu`、`pm_linesymb.otpu`、`pm_doubley.otpu`；注册表 `templates/origin/registry.json` 记录 id、名称、文件、SHA-256、版本、基础内置模板、图表类型、最低 Origin 版本（已验证 10.25）、必需数据列、样式元数据、用途。
- 部署：`scripts/vm/deploy_bridge.sh` 把模板与注册表复制到 `%BRIDGE%\app\templates\`。
- 使用：任务只按 id 指定模板（Schema 限定 `^[a-z][a-z0-9_]{0,39}$`，不接受路径）。Bridge 解析：
  - 方式 A（`native`）：注册且文件存在、哈希一致 → 用 `.otpu` 新建图页；
  - 方式 B（`programmatic`）：文件缺失、哈希不符或 id 未注册 → 用对应内置模板并以程序设置同样的期刊样式，结果中 `template_warnings` 给出中文原因（SPEC 失败场景“Origin 模板丢失”）；
  - 内置名（`line` 等）仍可直接使用（`builtin`）。
- `GET /v1/templates` 列出注册模板及其可用状态。

### 5.3 验证

- Bridge 自测（真实 Origin）：`pm_line`、`pm_doubley` 为 native，未注册 id 回退为 programmatic；OPJU 重开核验通过；自建实例全部退出。
- §6.7 十步验收用新模板重跑通过：`reports/data/origin/e2e_20261026_run2/`（`pm_line`，native，全程 63.8 s 级）。
- 中文轴标题在 Origin 中由系统 CJK 字体替代显示（Arial 无中文字形）。

## 6. 论文图风格模板与绘图工作室导出（2026-10-28）

### 6.1 属性确认（真实 Origin 2025b，逐项设置并读回）

属性名取自 OriginLab LabTalk 参考（Layer.Axis、Layer.Axis.Label、Page、图形对象、`win` 命令），在 VM 中用探测脚本确认，不凭记忆假设：

| 探测脚本 | 结论 |
|---|---|
| `bridge/windows-origin/probe_thesis_style.py` | `layer.{x,y,x2,y2}.ticks`（1 主内、2 主外、4 次内、8 次外；上/右轴用 x2/y2）、`thickness`、`tickthickness`、`mticklength`、`ticklength`、`minorTicks`、`label.font/pt/bold`、`xb/yl/legend.font/fsize` 均可设置并读回、保存重开不变。文字对象没有 `.bold`，加粗用 `\b(...)`。Origin 默认图页为 6432 × 4560 点 @600 dpi = 10.72 × 7.6 in，正是用户论文图的尺寸。 |
| `probe_legend_bold.py` | 直接写 `legend.text$="\b(\l(1) %(1))"` 会在赋值时替换 `%(1)`，图例变成固定文字；用 `%%(1)` 保持随数据更新，换行用 `%(CRLF)`（字面 `\n` 无效）。 |
| `probe_visibility.py`、`probe_open_visible.py` | 在隐藏实例中所有窗口（包括工作簿）都读作隐藏，读数无意义；用新的**可见**实例打开 OPJU，Bridge 生成的工作簿和图页均为正常窗口（`page.win = 3`），图页在最前（截图 `reports/data/origin/plotstudio_20261028/origin_gui_open_check.png`）。 |

另外两点只在生成过程中发现：LabTalk `exist()` 识别不了图形文字对象，`if(exist(xb)) {...}` 会被静默跳过（期刊模板的轴标题 Arial 设置也因此从未生效，Origin 默认本来就是 Arial，未改动）；从 `.otpu` 重新加载时刻度标签字体回到“首选项默认”（`label.font = 1`），所以 Bridge 在每次建图后重新设置字体。

### 6.2 论文图模板

- `pm_thesis_line`、`pm_thesis_scatter`、`pm_thesis_linesymb`、`pm_thesis_doubley`：由 `make_templates.py <id…>` 在真实 Origin 中生成，样式定义在 `polymech_bridge/templates.py`（`STYLES["thesis"]`）：Times New Roman 加粗，刻度数字 20 pt、轴标题 28 pt、图例 22 pt；轴线、刻度线 2.2 pt，黑色；下/左刻度朝外、上/右朝内，主刻度 9 pt、次刻度 4 pt，每两主刻度间 1 个次刻度；双 Y 右轴同样黑色、朝外。所有数值属性读回一致、重新加载后不变。记录：`reports/data/origin/templates_thesis_20261028/`。
- 注册表新增 `style_id`（`journal`/`thesis`）；Bridge 按它在建图后设置字体、加粗轴标题与图例，模板文件缺失时（方式 B）以程序设置同一样式。
- 默认：分析页导出与绘图工作室导出都用论文图模板（旧的期刊模板仍可按 id 使用），PNG 宽 3216 px（= 10.72 in × 300 dpi）。保存工程前激活第一张图页，打开工程时图在最前。

### 6.3 绘图工作室导出（`POST /api/origin/plot-jobs`）

- 每个面板一个工作簿（`DataA`、`DataB`…，每条曲线一组 X/Y/误差列，完整分辨率、显示单位）和一张图页（`FigA`、`FigB`…），曲线由这些列绘出，可在 Origin 中继续编辑；`Metadata` 工作簿记录来源分析版本、模板、软件版本与每条曲线的来源。
- 颜色按 `PlotSpec.color_of`（与 Matplotlib 导出、预览一致），线宽、线型（实线/虚线/点线/点划线）、符号、右轴、坐标轴标题/范围/对数、图例开关随图导出；面板按曲线类型选论文图模板（全线→line、全散点→scatter、混合→linesymb、有右轴→doubley）。
- 列不写注释：Origin 自动图例在列有注释时显示注释而不是长名称。
- 真实验证（2026-10-28，PEHA 拉伸数据，两面板三条曲线）：任务完成，OPJU 重新打开核验通过（3 个工作簿行数与 2 张图页曲线数一致），可见 Origin 中图页在最前、曲线链接到 `[DataA]Data!Col(...)[1:13098]`。记录：`reports/data/origin/plotstudio_20261028/`。
