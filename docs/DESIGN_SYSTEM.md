# 设计系统（PolyMech Studio 界面）

> 依据：Apple Human Interface Guidelines（2026-10-26 读取，经 developer.apple.com DocC 数据接口：Layout、Sidebars、Toolbars、Buttons、Color、Dark Mode、Typography、Motion、Accessibility、Materials）与 SPEC §9。
> 实现：React + Tailwind CSS v4 + shadcn/ui（Radix 原语），全部视觉值通过 `apps/web/src/index.css` 中的 CSS 变量（设计令牌）定义，不沿用 shadcn 默认外观。
> 图表配色不在此文件管理，见 `packages/plotting`（默认为用户毕设图风格，DECISIONS 2026-10-27）。

## 1. HIG 要点 → 本项目做法

| HIG 要点（摘要，非原文） | 本项目实现 |
|---|---|
| macOS 默认正文 13 pt，最小 10 pt（Accessibility） | 正文 13 px，最小 11 px（标签/辅助信息），不低于 10 px |
| macOS 文本样式：Large Title 26/32、Title1 22/26、Title2 17/22、Title3 15/20、Headline 13 Bold、Body 13/16、Callout 12/15、Subheadline 11/14、Footnote/Caption 10/13（Typography） | 令牌 `--text-*` 直接采用这些尺寸与行高；数值、表格使用 `tabular-nums` |
| 对比度：≤17 pt 文本 4.5:1；≥18 pt 或粗体 3:1；亮/暗模式都要满足；Increase Contrast 下提供更高对比（Accessibility、Color） | 所有前景/背景令牌组合按 WCAG AA 选取；`prefers-contrast: more` 下加深分隔线与次要文本 |
| macOS 控件默认 28×28 pt，最小 20×20 pt；带边框元素周围约 12 pt 间距（Accessibility） | 常规控件高 28 px，紧凑控件 24 px，图标按钮点击区 ≥ 24×24 px；控件间距 8–12 px |
| 侧边栏不超过两级层级；可隐藏；不要把关键操作放在侧边栏/窗口底部（Sidebars、Layout） | 侧边栏一级导航 + 分组标题；⌘⌥S 隐藏/显示；底部只放连接状态等非关键信息 |
| 工具栏：每个工具栏项也应有菜单/快捷键；只设一个主操作，放在尾部；优先图标，含义不清时用文字；标题简短（<15 字符），不用应用名（Toolbars） | 每页工具栏左侧为页面标题，右侧分组操作，主操作（强调色）在最右；所有工具栏操作提供快捷键并在 tooltip 中显示 |
| 按钮：必须有按下态；用样式而非尺寸区分主次；角色：normal/primary/cancel/destructive；打开新窗口/对话框的按钮标题加省略号（Buttons） | 按钮四种变体：默认、主要（强调色）、无边框、危险（红）；打开对话框的按钮文字以“…”结尾；hover/active/focus/disabled/loading 全部有状态 |
| 不要只用颜色传达信息；同一颜色不表示不同含义；使用语义颜色（Color） | 状态色（成功/警告/错误/信息）总是搭配图标与文字；强调色只用于主操作、选中与焦点 |
| 动效应有目的、简短精确；频繁交互避免额外动效；可取消；尊重 Reduce Motion（Motion、Accessibility） | 见 §4 |
| 全部功能可用键盘完成（Full Keyboard Access）；不覆盖系统快捷键（Accessibility） | Radix 原语保留 ARIA 与键盘行为；焦点环 2 px 强调色；自定义快捷键避开系统组合 |

## 2. 与 HIG 的差异（如实标注）

- **不使用 Liquid Glass**（SPEC §9.1 要求）：HIG 当前版本让侧边栏/工具栏以 Liquid Glass 浮于内容之上；本项目全部使用不透明材质，层级靠明度差、1 px 分隔线与间距表达。
- **侧边栏轻度模糊**：仅侧边栏使用 `backdrop-filter: blur()` + 半透明背景模仿 macOS 11–15 风格；`prefers-reduced-transparency` 或设置中的“减少透明度”开启时改为不透明。
- **字体单位**：Web 中以 CSS px 实现 pt 值（1 pt ≈ 1 CSS px 在 macOS 默认缩放下观感一致），不是精确的点数换算。
- **系统强调色**：浏览器无法读取 macOS 用户选择的强调色；使用固定强调色 `#0A64D6`（亮）/`#3B8BFF`（暗），Settings 中可选几种预设。
- **没有原生菜单栏**：Web 应用无法加入 macOS 菜单栏，HIG“工具栏项也应出现在菜单中”的要求以命令面板（⌘K）与快捷键替代。
- **Dynamic Type 不适用**：macOS 本身不支持 Dynamic Type；浏览器缩放（⌘+）可放大 200%，布局需在 200% 缩放下可用。

## 3. 设计令牌（`apps/web/src/index.css`）

| 令牌 | 亮色 | 暗色 | 用途 |
|---|---|---|---|
| `--bg-window` | `#F5F5F7` | `#1E1E20` | 窗口背景 |
| `--bg-content` | `#FFFFFF` | `#262628` | 内容区、表格、图表画布（纯色） |
| `--bg-sidebar` | `rgba(236,236,238,0.86)` | `rgba(40,40,43,0.86)` | 侧边栏（减少透明度时为不透明 `#ECECEE`/`#28282B`） |
| `--bg-inspector` | `#FAFAFB` | `#232325` | 检查器面板 |
| `--bg-hover` / `--bg-selected` | `rgba(0,0,0,0.05)` / 强调色 14% | `rgba(255,255,255,0.07)` / 强调色 28% | 行悬停/选中 |
| `--separator` | `rgba(0,0,0,0.10)` | `rgba(255,255,255,0.10)` | 1 px 分隔线 |
| `--text-primary` / `--text-secondary` / `--text-tertiary` | `#1D1D1F` / `#5E5E63` / `#68686D` | `#F2F2F4` / `#B4B4BA` / `#98989E` | 文本层级（在四种背景上最低对比 4.70:1，见 §3.1） |
| `--accent`（文字/图标/焦点） | `#0A64D6` | `#4C97FF` | 选中、焦点、链接 |
| `--accent-fill` / `--accent-fg` | `#0A64D6` / `#FFFFFF` | `#2E6BE6` / `#FFFFFF` | 主按钮填充与其文字 |
| `--success` / `--warning` / `--danger` / `--info` | `#1F7A3A` / `#9A5B00` / `#C4241B` / `#0A64D6` | `#4CC26E` / `#F0A830` / `#FF6B5E` / `#5AA2FF` | 状态（必配图标+文字） |
| 字号 | 26/22/17/15/13/12/11/10 px | — | Large Title…Caption（见 §1） |
| 间距 | 4 的倍数，主网格 8 px | — | 8pt 网格 |
| 圆角 | 控件 6 px、面板/卡片 10 px、弹出层 10 px、窗口外框 12 px | — | 内层圆角 ≤ 外层 |
| 阴影 | 仅菜单/Popover/对话框/Toast：`0 8px 24px rgba(0,0,0,.14), 0 0 0 0.5px rgba(0,0,0,.12)` | 暗色加深 | 其余元素无阴影 |
| 动效时长 | 微交互 120 ms、面板展开 200 ms、对话框 220 ms；弹簧 `stiffness 420, damping 36` | — | 见 §4 |

### 3.1 对比度实测（WCAG 2 相对亮度公式，2026-10-26）

初稿中 `#86868B`（亮色三级文本，3.07–3.62:1）、`#8A8A90`（暗色三级文本，侧边栏上 4.28:1）、`#3B8BFF`（暗色强调色文字 4.43:1；其上白字 3.32:1）不达标，已替换。替换后在窗口/内容/侧边栏/检查器四种背景上的最低对比度：

| 令牌 | 亮色 | 暗色 |
|---|---|---|
| 主要文本 | 14.26 | 13.15 |
| 次要文本 | 5.46 | 7.12 |
| 三级文本 | 4.70 | 5.12 |
| 强调色文字 | 4.68 | 5.02 |
| 成功 / 警告 / 危险 | 4.56 / 4.60 / 4.92 | 6.47 / 7.24 / 5.26 |
| 主按钮白字 | 5.52 | 4.81 |
| 暗色主按钮与背景（UI 组件，要求 ≥3:1） | — | 3.05 |

`prefers-contrast: more`：分隔线不透明度 ×2，次要/三级文本改用主要文本色，焦点环 3 px。

## 4. 动效

依据：LottieFiles motion-design-skill（2026-10-26 经用户确认安装于 `.claude/skills/motion-design/`，已通读）。与 HIG、SPEC 冲突处以 HIG/SPEC 为准（见下“取舍”）。

- 库：Motion（motion.dev）+ CSS 过渡；**只动画 `transform`、`opacity`**（SPEC），不动画 width/height/top/left。
- 人格：skill 的 **Corporate**（专业工具）——短、精确、无回弹；弹簧阻尼取接近临界（stiffness 420 / damping 42）。
- 缓动（`src/index.css` 令牌）：进入 `--ease-enter: cubic-bezier(0.2, 0, 0, 1)`（签名缓动，快速减速到位）；退出 `--ease-exit: cubic-bezier(0.3, 0, 1, 1)`（加速离开）。退出比进入短。
- 时长令牌：`--dur-micro` 100 ms（悬停、按下、选中高亮）· `--dur-menu-in/out` 150/100 ms（菜单、Select、Popover、Tooltip）· `--dur-panel` 200 ms（侧边栏、检查器）· `--dur-dialog-in/out` 250/180 ms（对话框与遮罩）。shadcn/Radix 浮层通过 `data-slot` + `data-state` 选择器统一套用这些令牌。
- 侧边栏：`AnimatePresence` 内 translateX + opacity 滑入/滑出；内容区宽度只在面板进入时或离开后**一次性**重排，不做布局动画。
- 用途仅限：侧边栏/检查器、浮层出现与消失、Toast（sonner 默认）、选中与悬停反馈。
- 禁止：分析页面的环境动效、粒子、背景动画；数值滚动计数；装饰性无限循环加载动画。
- 长任务（计算、Origin 绘图）显示确定性进度或明确状态文字（如“正在启动 Origin”“正在重新打开工程核验”）。
- 图表：导出（PNG/PDF/SVG/Origin）时关闭全部过渡；交互预览中数据更新不做中间态插值（Plotly `transition: 0`），避免误导性中间状态。
- `prefers-reduced-motion: reduce`：全部 `--dur-*` 令牌置 0 ms，Motion 组件跟随系统设置（`MotionConfig reducedMotion="user"`）。

**取舍（skill vs HIG/SPEC）**：skill 建议每个界面具备“主要/次要/环境”三层动效并带入场编排（stagger）；本软件是科研分析工具，SPEC 禁止环境动效且要求数据视图稳定，因此只保留“主要”层（状态变化反馈），不做页面入场编排、不做环境层。skill 的检查清单其余部分（缓动一致、退出快于进入、时长分级、可访问性）均已落实。

## 5. 布局

- 三栏：侧边栏（220 px，可隐藏）｜内容区（自适应）｜检查器（300 px，可折叠）；窗口宽 < 1100 px 时检查器自动折叠为覆盖式面板，< 860 px 时侧边栏自动隐藏。
- 顶部工具栏高 44 px：左侧页面标题（< 15 字符），右侧操作分组，主操作在最右。
- 适配 13–16 英寸 MacBook（1280–1728 CSS px 宽）与外接显示器。
- 科研图表画布、数据表格、表单正文始终纯色背景。

## 6. 组件约定

- 图标：lucide（单一线性图标集，风格接近 SF Symbols），只在提高识别效率处使用。
- 表格：可调列宽、排序、筛选、键盘导航（↑↓ 行，Enter 打开），数值列右对齐 + `tabular-nums`。
- 破坏性操作：确认对话框，主按钮为“取消”以外的危险样式；可撤销时提供 Toast 撤销。
- 错误信息：说明原因 + 建议操作（后端错误的中文 `detail` 原样显示）。
- 快捷键：⌘O 导入、⌘E 导出、⌘R 重新计算、⌘K 命令面板、⌘, 设置、⌘⌥S 侧边栏、⌘⌥I 检查器。

## 7. Windows（Fluent 2）

Windows 与 macOS 共用组件；`data-platform="windows"` 覆盖令牌。桌面外壳在首次导航前注入平台，浏览器使用 UA。没有增加 Fluent 组件库或文件、Shell IPC 权限。

| 项目 | Windows 取值与选择 |
| --- | --- |
| 字体 | Segoe UI Variable → Segoe UI → Microsoft YaHei UI → sans-serif；数值保留 `tabular-nums` |
| 字号 / 行高 | 12/16、14/20、18/24、20/28、28/36、40/52；来自 [Fluent Windows 字体阶梯](https://fluent2.microsoft.design/typography) |
| 圆角 | 小型 2、普通控件 4、卡片 8、弹出层 12 px；采用 [Fluent 形状令牌](https://fluent2.microsoft.design/shapes/) 并按现有组件层级映射 |
| 控件高度 | 普通操作 32、密集操作 24 px；科研界面保留紧凑输入框，属于项目密度选择 |
| 窗口 / 内容 | 亮色 `#F3F3F3` / `#FFFFFF`，暗色 `#202020` / `#292929`；图表和内容始终不透明 |
| 文本 | 亮色 `#242424`、`#424242`、`#616161`；暗色 `#FAFAFA`、`#D6D6D6`、`#BDBDBD` |
| 强调色 | 外壳读取 DWM `ColorizationColor`；按钮文字选择黑/白，链接颜色另按背景调整到 4.5:1；无法读取时用 Fluent 蓝 |
| 焦点 | 外层 2 px 文本色与内层 1 px 背景色；保留 Radix 键盘与 ARIA 行为 |
| 对话框 | 主操作在左、取消在右；危险确认始终先聚焦取消 |
| 菜单和标题栏 | 系统标题栏和窗口内文件/编辑/显示/帮助菜单；Ctrl 快捷键，macOS 继续用 ⌘ |
| 材质 | 系统开启透明效果且应用未开启“减少透明度”时尝试 Mica；不支持则保留实色。原生窗口材质在下次启动时读取应用设置 |
| 动效 | 沿用短促的现有动效，`prefers-reduced-motion` 关闭动画；细滚动条 |

Windows 原生 WebView2、系统缩放和屏幕截图的验收记录见 `docs/WINDOWS.md`；CSS 预览不代表原生验收。

2026-10-28：最终 Windows 安装版 WebView2 的亮/暗主题、系统标题栏和窗口内菜单已有原生截图，Chromium 亮暗 axe 与 Ctrl 快捷键通过。实际 125%/150% 系统缩放及原生完整键盘流程仍待人工确认，详见 Windows 验证记录。
