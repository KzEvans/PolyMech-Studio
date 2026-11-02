/** In-app usage guide (static content; docs/USER_GUIDE.md is the short version). */
import { useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Search } from "lucide-react";
import { Toolbar } from "@/components/shell/AppShell";
import { StatusLine } from "@/components/common";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { getPlatform, shortcut } from "@/lib/platform";

type Section = { id: string; title: string; body: ReactNode };

const F = ({ children }: { children: ReactNode }) => <code className="rounded bg-hover px-1 py-px whitespace-nowrap">{children}</code>;
const Note = ({ children }: { children: ReactNode }) => <StatusLine severity="info" className="rounded-md border bg-content px-3 py-2">{children}</StatusLine>;
const Warn = ({ children }: { children: ReactNode }) => <StatusLine severity="warning" className="rounded-md border bg-content px-3 py-2">{children}</StatusLine>;
const Steps = ({ children }: { children: ReactNode }) => <ol className="list-decimal space-y-1.5 pl-5">{children}</ol>;
const Bullets = ({ children }: { children: ReactNode }) => <ul className="list-disc space-y-1.5 pl-5">{children}</ul>;

const SECTIONS: Section[] = [
  {
    id: "start",
    title: "快速开始",
    body: (
      <>
        <p>一次完整分析分五步，全部在本软件内完成：</p>
        <Steps>
          <li><b>导入</b>：侧边栏“实验”→“导入数据…”（{shortcut("O")}），把仪器导出的文件拖进窗口。</li>
          <li><b>核对列映射与单位</b>：确认每一列是什么物理量、用什么单位；黄色提示必须处理。</li>
          <li><b>检查数据并填写元数据</b>：选择测试类型，点“检查数据”，填写材料名与必需的样品尺寸。</li>
          <li><b>计算</b>：在“分析”页右栏设置参数，点“计算”（{shortcut("R")}）。每次计算保存为新版本。</li>
          <li><b>出图与报告</b>：“绘图工作室”导出 PNG/SVG/PDF，或“导出到 Origin…”；“报告”页生成 HTML/PDF。</li>
        </Steps>
        <Note>所有数值计算都由确定性的公式完成，AI 只用于列映射建议和文献对标解释；关闭 AI 不影响任何计算。</Note>
      </>
    ),
  },
  {
    id: "files",
    title: "支持的数据文件",
    body: (
      <>
        <Bullets>
          <li>文本：CSV、TSV、TXT、DAT、ASC。自动识别编码（UTF-8、GBK 等）、分隔符和小数逗号。</li>
          <li>Excel：XLSX、XLSM，以及旧版 XLS（Excel 97–2003、WPS 导出）。每个有数据的工作表是一张表格，空工作表自动跳过。</li>
          <li>表头可以带单位，例如 <F>Force (N)</F>、<F>应力/MPa</F>、<F>位移（mm）</F>；也可以有单独的单位行。表头上方的说明文字会作为前言保留。</li>
          <li>列名带样品编号也能识别，例如 <F>时间4</F>、<F>力4</F>、<F>应变4</F>。</li>
        </Bullets>
        <Warn>
          旧版 XLS 每个工作表最多 65,536 行。如果文件正好停在 65,535 个数据行，很可能是仪器导出时被截断了（常见于 0.01 s 采样），断裂段会丢失。请从试验机重新导出为 CSV 或 XLSX。
        </Warn>
        <p>原始文件导入后只读归档并记录 SHA-256，软件不会修改它；修正和计算都基于副本。</p>
      </>
    ),
  },
  {
    id: "mapping",
    title: "列映射与单位",
    body: (
      <>
        <p>每一列给出推荐的物理量、单位、置信度和依据（列名规则、单位量纲、数值特征）。</p>
        <Bullets>
          <li><b>黄色提示</b>的列必须修改或勾选“已确认”，例如“列名像应变但起始值约为 1（可能是拉伸比）”“未说明是名义应力还是真实应力”“未给出单位”。</li>
          <li><b>没有单位的有量纲列不能继续</b>：软件不会猜测力、位移、应力的单位。请按仪器设置选择（如 N、mm、MPa）。</li>
          <li><b>应变是小数还是百分数</b>：没有单位时，数值最大值超过 5 会被推测为百分数，弹性体可能拉到 500% 以上，请务必核对。简便方法：最终应变 ÷ 试验时间 应等于设定的应变速率（例如 30%/min = 0.005 /s）。</li>
          <li><b>AI 识别列…</b>（可选）：先显示将要发送的内容（表头、单位、默认 5 行样例），确认后才发送。AI 与规则不一致的列一律需要人工确认。注意 Codex CLI、Claude CLI 也是云端模型。</li>
          <li><b>保存为仪器导入规则…</b>：同一台仪器、同样表头的文件以后自动套用映射。</li>
        </Bullets>
        <Note>单位换算使用 Pint 做量纲校验，不靠字符串替换；所有数据内部统一为 SI 单位。</Note>
      </>
    ),
  },
  {
    id: "quality",
    title: "质量检查",
    body: (
      <>
        <p>选择测试类型后点“检查数据”。质量检查<b>只标注、不删除</b>原始数据，检查项包括：缺失值、时间倒退、信号突变、量程截断或传感器饱和、零点偏移、疑似夹具打滑、无法确定断裂点等。</p>
        <Note>采样很密（如 0.01 s）而力很小时，噪声会让“疑似打滑”“饱和”出现较多次数。请对照曲线判断，需要时用“数据修正”中的平滑处理，而不是删除数据。</Note>
      </>
    ),
  },
  {
    id: "metadata",
    title: "元数据与样品尺寸",
    body: (
      <>
        <p>带 * 的字段是当前测试类型、当前列组合计算所必需的。尺寸以 mm 输入，内部换算为 m。</p>
        <Bullets>
          <li>单轴/循环拉伸：有名义应力和应变（或拉伸比）列时只需材料名；只有力和位移时需要厚度、宽度、标距。</li>
          <li>纯剪切与疲劳：始终需要可拉伸高度 H0（<F>G = H0·W</F>），有预切裂纹样品还需要裂纹长度。</li>
          <li>裂纹扩展：需要裂纹位置测量分辨率（用于检测限）。</li>
        </Bullets>
        <Warn>缺少必需尺寸时，相应计算会被拒绝并提示补充，软件不会使用默认值。如果仪器导出的应力列与力列数值完全相同，通常说明试验机里没有输入截面积（按 1 mm² 计算），这时应力列不可用，请填写真实尺寸并改用力列计算。</Warn>
      </>
    ),
  },
  {
    id: "uniaxial",
    title: "单轴拉伸",
    body: (
      <>
        <p>主要公式：</p>
        <Bullets>
          <li>拉伸比 <F>λ = 1 + ε</F>（ε 为工程应变，小数）。</li>
          <li>名义应力 <F>σ = F / A0</F>；真实应力 <F>σ_true ≈ λ·σ</F>（仅在近似不可压缩、均匀变形时成立）。</li>
          <li>应变能密度 <F>W(λ) = ∫₁^λ σ dλ</F>，对名义应力积分；断裂功 W_f 为积分到断裂点的值，并给出数值积分误差。</li>
          <li>初始模量 E：在 λ 区间（默认 1–1.05；塑料常用 1–1.02）对 σ–λ 线性拟合，给出标准误差、R² 与残差图。</li>
        </Bullets>
        <p>断裂点：最后一个应力峰之后，应力在 5 个点内降到峰值的一半以下且不再回升，即判为断裂。也可以在右栏“断裂拉伸比（人工指定）”输入。</p>
        <Warn>没有检测到断裂时结果标为“临时”，表中的“断裂”数值其实是最后一个数据点，不进入材料性能统计。常见原因是文件被截断（见“支持的数据文件”）。</Warn>
        <p>“微分模量”标签页显示 dσ/dλ，可选 Savitzky–Golay 平滑窗口（奇数，≥ 5）；若出现明显的应变硬化，会给出硬化起点。</p>
      </>
    ),
  },
  {
    id: "cyclic",
    title: "循环拉伸",
    body: (
      <>
        <p>测试类型选“循环拉伸”，映射拉伸比（或应变/位移）与应力（或力）。循环按拉伸比的峰谷自动分割，逐圈给出峰值应力、加载功、卸载功、滞后能、滞后比和残余应变。</p>
        <Bullets>
          <li>残余应变在卸载应力降到设定阈值处读取。</li>
          <li>未闭合的循环会注明“滞后能 ≠ 完整耗散”，不会被当作完整的热耗散。</li>
        </Bullets>
      </>
    ),
  },
  {
    id: "pure-shear",
    title: "纯剪切断裂韧性",
    body: (
      <>
        <Steps>
          <li>分别导入<b>无裂纹</b>（“纯剪切（无预切裂纹）”）与<b>有裂纹</b>（“纯剪切（有预切裂纹）”）样品，两者属于同一材料，填写 H0、宽度、厚度、预切裂纹长度。</li>
          <li>打开有裂纹样品的分析页，选择对应的无裂纹样品，给出临界拉伸比 λc：人工输入（照片/视频帧判读后勾选“已确认”）、按同步时间，或力峰值候选（仅供参考，结果为临时值）。</li>
          <li>选择 λc 的定义（裂纹开始增长 / 开始稳态扩展），计算 <F>Gc = H0·W(λc)</F>，其中 W 来自无裂纹样品。</li>
        </Steps>
        <Note>λc 超出无裂纹样品断裂前的范围时拒绝外推。</Note>
      </>
    ),
  },
  {
    id: "fatigue",
    title: "循环纯剪切疲劳",
    body: (
      <>
        <Steps>
          <li>每个拉伸幅度的无裂纹样品导入为“疲劳：无裂纹样品循环”，计算“稳态能量”，得到 <F>G = H0·W</F>（会检查加载功是否已稳定）。</li>
          <li>裂纹长度–循环次数数据导入为“疲劳：裂纹长度–循环次数”，填写裂纹位置分辨率，选择对应的稳态结果计算 dc/dN。</li>
          <li>在任一裂纹扩展实验中选择“疲劳阈值”，勾选参与的结果，可限定拟合的 G 区间。</li>
        </Steps>
        <Bullets>
          <li>Δc 小于分辨率时记为“低于检测限”（删失观测），不会记为 0，也不进入普通线性拟合。</li>
          <li>线性外推给出 G0、标准误差和 bootstrap 置信区间；数据不足、斜率非正、明显非线性或 G0 ≤ 0 时拒绝报告。</li>
          <li>同时给出“未检出的最高 G – 检出的最低 G”实验区间。有限循环内未扩展不等于永不疲劳。</li>
          <li>载荷比、λmin/λmax 与 G 的定义（G_max、ΔG）会随结果保留，不同定义不合并。</li>
        </Bullets>
      </>
    ),
  },
  {
    id: "dma",
    title: "DMA",
    body: (
      <>
        <Steps>
          <li>导入温度扫描数据，测试类型选“动态力学分析（DMA）”，映射温度、储能模量，以及损耗模量和/或 tan δ；有频率列时按频率分组。</li>
          <li>右栏选择形变模式（拉伸 E′/E″ 或剪切 G′/G″），点“计算”。</li>
          <li>Tg 候选按定义分别列出：tan δ 峰、损耗模量峰、储能模量下降起始，并注明频率。出现多个显著峰时不自动选定，请填写搜索区间后重新计算。</li>
          <li>“多样品比较”叠加 tan δ 曲线；Tg 按定义、频率与形变模式分组，不同组之间不比较。</li>
        </Steps>
      </>
    ),
  },
  {
    id: "corrections",
    title: "数据修正",
    body: (
      <>
        <p>“分析”页右栏“数据修正 → 添加修正…”，可用的修正：零点校正、位移按接触点归零、线性基线扣除、Savitzky–Golay 平滑、滑动平均平滑。对话框会显示修正前后的曲线。</p>
        <Bullets>
          <li>修正保存算法、参数、操作者与时间，只作用于之后的计算（点“按当前参数新建版本”）；已有版本不变。</li>
          <li>“停用”后不再使用，但保留记录；原始文件始终不变。</li>
          <li>分析结果的“溯源”中列出该版本用到的修正。</li>
        </Bullets>
      </>
    ),
  },
  {
    id: "versions",
    title: "版本与溯源",
    body: (
      <Bullets>
        <li>每次计算都保存为新版本（v1、v2…），旧结果不会被覆盖。左栏切换版本，“比较版本…”查看参数与结果差异。</li>
        <li>“溯源”记录软件版本、输入哈希、结果哈希、原始文件 SHA-256、数据修正和计算时间，可完整复现。</li>
        <li><b>删除</b>：分析页版本列表中每个版本右侧的垃圾桶删除该版本；“删除实验…”（分析页左栏或“实验”页每行右侧）删除整个实验及其全部版本、列映射、数据修正和归档的原始文件。删除前会确认，且不能撤销；其他分析仍在使用的结果（如疲劳裂纹扩展用到的稳态结果）不能删除。已导出的 Origin 工程和已保存的图不受影响。</li>
        <li>状态为“临时”的结果（未检出断裂、λc 未确认等）不进入材料性能统计。</li>
      </Bullets>
    ),
  },
  {
    id: "plots",
    title: "绘图工作室",
    body: (
      <>
        <Bullets>
          <li>左栏：模板列表、分析结果（拖到面板或点 + 添加）、已保存的图、自定义模板。“材料库”对比模板直接用材料数据库中的性能数值作图。</li>
          <li>中间：多面板实时预览，点面板切换编辑对象。</li>
          <li>右栏：版面（行列、尺寸、面板标号）、坐标轴（标题、单位、对数、范围）、图例、系列（顺序、颜色、线型、线宽、符号、右轴、误差棒）。</li>
          <li>“恢复默认”只恢复当前面板；“保存为模板”保存版式与样式；“保存配置”保存整张图；“导出数据与配置”导出图中数据（CSV）与配置 JSON。</li>
        </Bullets>
        <p>默认样式与毕业论文图一致：Times New Roman 加粗，刻度数字 20 pt、坐标轴标题 28 pt，坐标轴 2.2 pt、曲线 3 pt，下/左刻度朝外、上/右刻度朝内；坐标轴标题默认英文（如 Stretch ratio λ、Nominal stress σ (MPa)，可在右栏修改）；颜色按曲线条数自动选择红蓝配色；页面 272 × 193 mm，PNG 默认 300 dpi。以前保存的图保持原来的样式。</p>
      </>
    ),
  },
  {
    id: "origin",
    title: "导出到 Origin",
    body: (
      <>
        <Bullets>
          <li><b>分析页“导出到 Origin…”</b>：选择模板与导出格式。Origin 在 Parallels 虚拟机中生成工作簿（原始数据、处理数据、汇总、元数据）和图页，保存 OPJU 后重新打开核验。</li>
          <li><b>绘图工作室“导出到 Origin…”</b>：把当前这张图原样生成 Origin 图页，每个面板一张；曲线、颜色、线宽、线型、符号、坐标轴标题与范围、对数轴、图例都和预览一致。每条曲线的数据以完整分辨率写入工作簿，图中曲线直接引用这些列，打开工程即可在 Origin 中继续编辑（双击曲线、坐标轴修改，改数据图会跟着变）。</li>
          <li>默认使用与论文图一致的 Origin 模板（Times New Roman 加粗、坐标轴 2.2 pt、下/左刻度朝外、上/右朝内）；导出的 PNG 为 3216 × 2280 px（300 dpi）。</li>
          <li>文件下载到本机“下载”文件夹；打开 OPJU 时第一张图在最前，工作簿在其后。</li>
        </Bullets>
        <Note>侧边栏底部显示 Origin 连接状态。需要虚拟机已开机并登录 Windows（Bridge 随登录自启）；未连接时其他功能照常使用。连接设置在“设置 → Origin Bridge”。</Note>
      </>
    ),
  },
  {
    id: "materials",
    title: "材料数据库与文献",
    body: (
      <Bullets>
        <li>“材料数据库”→“按条目查看”：选择材料后，每次分析（每个版本）和每条文献记录是一个单独的条目，显示样品、方法、版本、时间和模量拟合区间等参数；点条目查看它的全部性能数值，“打开分析”跳到对应版本。文献条目显示来源（作者、年份、页码、图表号）、提取方式（文献报告值 / 图形数字化估计值）和原文写法。</li>
        <li>“性能对比图”：任选两项性能作横纵轴（可对数），每个条目一个点（圆点为本软件分析结果，三角为文献记录），点旁标注样品与版本。“同一条目配对”只用同一样品、同一次分析的数值；“同一材料配对”允许横纵坐标来自同一材料的不同实验（会注明）。默认每个实验只用最新版本，临时结果不计入。</li>
        <li>每条数值的“可比性…”列出同类数值的可比性结论与逐项理由（测试方法、速率、温度、定义等）。</li>
        <li>分析页“文献对标…”：先列出规则检索到的文献记录；可选请求 AI 推荐与解释，AI 只能引用列表中的记录，默认不发送本实验数值。</li>
      </Bullets>
    ),
  },
  {
    id: "reports",
    title: "报告",
    body: <p>侧边栏“报告”选择分析版本，可下载 HTML/JSON，或“打印 / 存为 PDF…”。报告包含材料与样品信息、方法、公式、参数、结果、质量警告、原始数据来源、软件版本与哈希，只包含确定性结果，不含 AI 生成的解释。</p>,
  },
  {
    id: "settings",
    title: "设置与 AI",
    body: (
      <Bullets>
        <li>外观：跟随系统 / 浅色 / 深色；减少透明度。</li>
        <li>操作者：写入数据修正与分析记录。</li>
        <li>AI：开关、Provider（默认 Codex CLI）、模型、推理强度；API 方式的 Key 保存在系统凭据存储中（macOS 钥匙串或 Windows 凭据管理器）。</li>
        <li>Origin：{getPlatform() === "windows" ? "使用已安装的本机 Origin，无需设置虚拟机地址。" : "Bridge 地址、Token、自动配对、测试连接与诊断信息；Token 保存在钥匙串。"}</li>
        <li>应力显示单位：界面中应力的显示单位（不影响存储与计算）。</li>
      </Bullets>
    ),
  },
  {
    id: "shortcuts",
    title: "快捷键",
    body: <p><F>{shortcut("O")}</F> 导入 · <F>{shortcut("R")}</F> 重新计算（分析页）· <F>{shortcut(",")}</F> 设置 · <F>{shortcut("S", { alt: true })}</F> 显示/隐藏侧边栏 · <F>Esc</F> 关闭对话框。全部功能都可以用键盘完成。</p>,
  },
  {
    id: "faq",
    title: "常见问题",
    body: (
      <dl className="space-y-3">
        <div><dt className="font-medium">模量、应力比预期小（或大）1000 倍？</dt><dd className="text-fg-2">多半是列映射时应力单位选错了（kPa 与 MPa）。请在仪器设置中确认单位，重新导入并选择正确单位；已有结果不会被改动。</dd></div>
        <div><dt className="font-medium">结果显示“未检测到断裂”，状态为临时？</dt><dd className="text-fg-2">检查曲线末端是否有断裂下降。若文件正好 65,535 行，是 XLS 截断；否则可在右栏人工指定断裂拉伸比。</dd></div>
        <div><dt className="font-medium">应力列和力列一模一样？</dt><dd className="text-fg-2">试验机里没有输入截面积。不要用这一应力列，填写厚度和宽度并只映射力列，由软件计算 F/A0。</dd></div>
        <div><dt className="font-medium">导入时提示“必须指定单位”？</dt><dd className="text-fg-2">该列表头没有写单位。在映射表中选择单位后才能继续，软件不会自行假设。</dd></div>
        <div><dt className="font-medium">Origin 显示“未连接”？</dt><dd className="text-fg-2">{getPlatform() === "windows" ? "确认电脑已安装并可正常使用 Origin，在“设置 → Origin”查看本机连接诊断。" : "启动 Parallels 中的 Windows 11 并登录，稍等 Bridge 自启；仍未连接时到“设置 → Origin Bridge → 测试连接”查看诊断信息。"}</dd></div>
        <div><dt className="font-medium">数据保存在哪里，如何备份？</dt><dd className="text-fg-2">桌面版数据在 <F>{getPlatform() === "windows" ? "%APPDATA%\\PolyMechStudio" : "~/Library/Application Support/PolyMechStudio"}</F>（菜单“文件 → {getPlatform() === "windows" ? "打开数据文件夹" : "在 Finder 中显示数据文件夹"}”）。备份时先退出应用，再复制整个文件夹；下载的图和报告在系统“下载”文件夹。</dd></div>
      </dl>
    ),
  },
];

/** Usage guide: table of contents on the left, sections on the right, filter by keyword. */
export default function Help() {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(SECTIONS[0].id);
  const refs = useRef<Record<string, HTMLElement | null>>({});
  const [texts, setTexts] = useState<Record<string, string>>({});

  // plain text of each rendered section, for the keyword filter
  useLayoutEffect(() => {
    setTexts(Object.fromEntries(SECTIONS.map((s) => [s.id, (refs.current[s.id]?.textContent ?? "").toLowerCase()])));
  }, []);

  const q = query.trim().toLowerCase();
  const visible = useMemo(() => new Set(SECTIONS.filter((s) => !q || (texts[s.id] ?? s.title).includes(q)).map((s) => s.id)), [q, texts]);

  const go = (id: string) => {
    setActive(id);
    refs.current[id]?.scrollIntoView({ block: "start" });
  };

  return (
    <>
      <Toolbar title="使用说明" />
      <div className="flex min-h-0 flex-1">
        <nav aria-label="使用说明目录" className="w-56 shrink-0 space-y-2 overflow-auto border-r bg-inspector p-2">
          <div className="relative">
            <Search aria-hidden className="pointer-events-none absolute top-1/2 left-2 size-3.5 -translate-y-1/2 text-fg-2" />
            <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="搜索说明…" aria-label="搜索使用说明" className="h-7 pl-7" />
          </div>
          <ul className="space-y-0.5">
            {SECTIONS.filter((s) => visible.has(s.id)).map((s) => (
              <li key={s.id}>
                <button type="button" onClick={() => go(s.id)} aria-current={s.id === active}
                  className={cn("w-full rounded-md px-2 py-1 text-left hover:bg-hover", s.id === active && "bg-hover font-medium")}>
                  {s.title}
                </button>
              </li>
            ))}
          </ul>
          {visible.size === 0 && <p className="px-2 text-fg-2">没有找到“{query}”。</p>}
        </nav>
        {/* focusable so the scrolling text can be read with the keyboard */}
        <main tabIndex={0} aria-label="使用说明内容" className="min-w-0 flex-1 overflow-auto bg-content">
          <article className="mx-auto max-w-3xl space-y-8 px-6 py-5 leading-relaxed">
            {SECTIONS.map((s) => (
              <section key={s.id} id={`help-${s.id}`} ref={(el) => { refs.current[s.id] = el; }} hidden={!visible.has(s.id)} className="scroll-mt-4 space-y-3">
                <h2 className="text-title3 font-semibold">{s.title}</h2>
                {s.body}
              </section>
            ))}
          </article>
        </main>
      </div>
    </>
  );
}
