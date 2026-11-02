import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

const FIX = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../../fixtures/import");

async function axe(page: Page, where: string) {
  // measure the steady state: let enable/disable transitions (≤ 200 ms) finish first
  await page.waitForTimeout(400);
  const res = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
  const bad = res.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  const detail = bad.flatMap((v) => v.nodes.map((n) => `${where}: ${v.id} ${n.target.join(" ")} ${n.failureSummary?.split("\n").slice(1, 2).join("") ?? ""}`));
  expect(detail).toEqual([]);
}

test.describe.serial("单轴拉伸主流程（SYNTHETIC 数据）", () => {
  let analysisUrl = "";
  let materialName = "";

  test("导入 → 映射 → 检查 → 元数据 → 创建实验", async ({ page }) => {
    await page.goto("/experiments/import");
    await page.getByLabel("选择数据文件").setInputFiles(path.join(FIX, "SYNTH_uniaxial_gbk_chinese.csv"));
    await expect(page.getByLabel("时间 的物理量")).toContainText("时间");
    await expect(page.getByLabel("力 的物理量")).toContainText("力");
    await expect(page.getByLabel("位移 的单位")).toHaveValue("mm");
    await axe(page, "导入");

    await page.getByRole("button", { name: "检查数据" }).click();
    await expect(page.getByText("没有发现数据质量问题")).toBeVisible();
    await expect(page.getByRole("figure", { name: /预览曲线/ })).toBeVisible();

    const create = page.getByRole("button", { name: "创建实验" });
    await expect(create).toBeDisabled(); // dimensions are required, never defaulted
    materialName = `SYN-E2E-UI-${test.info().project.name}`;
    await page.getByLabel(/材料名称/).fill(materialName);
    await page.getByLabel(/样品编号/).fill(`UI-${test.info().project.name}`);
    await page.getByLabel(/样品厚度/).fill("1");
    await page.getByLabel(/样品宽度/).fill("2");
    await page.getByLabel(/初始标距/).fill("20");
    await expect(create).toBeEnabled();
    await create.click();
    await expect(page).toHaveURL(/\/analysis\/\d+$/);
    analysisUrl = page.url();
  });

  test("计算 → 新版本 → 比较版本", async ({ page }) => {
    await page.goto(analysisUrl);
    await page.getByRole("button", { name: /^计算/ }).click();
    await expect(page.getByText("初始模量 E")).toBeVisible();
    await expect(page.getByRole("button", { name: /^v1/ })).toBeVisible();
    await axe(page, "分析");

    // layout regressions: the window itself never scrolls (no blank area under the app), and
    // charts keep their height after the window grows (full screen) instead of collapsing to 0
    const docOverflow = () => page.evaluate(() => document.documentElement.scrollHeight - document.documentElement.clientHeight);
    const plots = () => page.locator(".js-plotly-plot").evaluateAll((els) =>
      els.map((e) => ({ h: e.getBoundingClientRect().height, w: (e as unknown as { _fullLayout: { width: number } })._fullLayout.width, cw: e.getBoundingClientRect().width })));
    const size = page.viewportSize()!;
    // open in a small window (results below the fold), then go "full screen"
    await page.setViewportSize({ width: 1000, height: 670 });
    await page.reload();
    await expect(page.getByText("初始模量 E")).toBeVisible();
    await page.waitForTimeout(300);
    expect(await docOverflow()).toBeLessThanOrEqual(0);
    await page.setViewportSize({ width: 1600, height: 1000 });
    await expect.poll(async () => (await plots()).every((p) => Math.abs(p.w - p.cw) < 2)).toBe(true); // Plotly re-laid out
    for (const p of await plots()) expect(p.h).toBeGreaterThan(100);
    expect(await docOverflow()).toBeLessThanOrEqual(0);
    await page.setViewportSize(size);

    await page.getByLabel("λ 上限").fill("1.02");
    await page.getByRole("button", { name: "按当前参数新建版本" }).click();
    await expect(page.getByRole("button", { name: /^v2/ })).toBeVisible();
    await expect(page.getByRole("button", { name: /^v1/ })).toBeVisible(); // old version kept

    await page.getByRole("button", { name: /比较版本/ }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByText("两个版本使用同一份原始数据。")).toBeVisible();
    await expect(dialog.getByText("modulus_stretch_range")).toBeVisible();
    await dialog.getByRole("button", { name: "完成" }).click();

    await page.reload();
    await expect(page.getByLabel("λ 上限")).toHaveValue("1.02");
    await page.getByRole("button", { name: /^v1 ·/ }).click();
    await expect(page.getByLabel("λ 上限")).toHaveValue("1.05");
    await page.getByRole("button", { name: /^v2 ·/ }).click();
    await expect(page.getByLabel("λ 上限")).toHaveValue("1.02");
  });

  test("绘图工作室 → 导出 PNG；报告页", async ({ page }) => {
    await page.goto(analysisUrl);
    await page.getByRole("button", { name: /绘图工作室/ }).click();
    await expect(page).toHaveURL(/\/plots\?run=\d+/);
    await expect(page.locator(".js-plotly-plot .scatterlayer path.js-line").first()).toBeVisible();
    const sources = page.getByRole("navigation", { name: "模板与数据" });
    await expect(sources.getByText(`${materialName} · 单轴拉伸 v2`, { exact: true })).toBeVisible();
    await expect(sources.getByText(`UI-${test.info().project.name} · 单轴拉伸 v2`, { exact: true })).toHaveCount(0);
    await expect(page.getByLabel("系列名称（图例）")).toHaveValue(`${materialName} v2`);
    await sources.getByRole("button", { name: `把 ${materialName} v1 添加到面板 (a)`, exact: true }).click();
    await expect(page.locator(".js-plotly-plot .legendtext")).toHaveText([`${materialName} v2`, `${materialName} v1`]);
    await page.getByRole("switch", { name: "显示图例", exact: true }).uncheck();
    await expect(page.locator(".js-plotly-plot .legendtext")).toHaveCount(0);
    await page.getByRole("switch", { name: "显示图例", exact: true }).check();
    await expect(page.locator(".js-plotly-plot .legendtext")).toHaveText([`${materialName} v2`, `${materialName} v1`]);
    await page.getByLabel("名称", { exact: true }).fill(`SYN saved ${test.info().project.name}`);
    await page.getByRole("button", { name: "保存配置", exact: true }).click();
    await expect(sources.getByRole("button", { name: `SYN saved ${test.info().project.name}`, exact: true })).toBeVisible();
    await axe(page, "绘图工作室");
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: /导出图片/ }).click();
    await page.getByRole("menuitem", { name: /PNG/ }).click();
    const file = await download;
    expect(file.suggestedFilename()).toMatch(/\.png$/);

    // multi-panel: add panel (b), put the other version in it via the keyboard-accessible "+"
    await page.getByRole("button", { name: "添加面板" }).click();
    await expect(page.getByText("把分析结果拖到这个面板")).toBeVisible();
    await page.getByRole("button", { name: `把 ${materialName} v1 添加到面板 (b)`, exact: true }).click();
    await expect(page.locator(".js-plotly-plot")).toHaveCount(2);
    await page.getByRole("button", { name: "真实应力–拉伸比" }).click();
    await expect(page.getByRole("region", { name: "面板 (b)" }).getByText("真实应力–拉伸比")).toBeVisible();
    const csv = page.waitForEvent("download");
    await page.getByRole("button", { name: /导出数据与配置/ }).click();
    await page.getByRole("menuitem", { name: /图中数据/ }).click();
    expect((await csv).suggestedFilename()).toBe("plot_data.csv");
    await page.getByRole("button", { name: /保存为模板/ }).click();
    await expect(page.getByRole("button", { name: /删除自定义模板/ })).toHaveCount(1);
    await page.waitForTimeout(400);
    await axe(page, "绘图工作室（多面板）");

    // deleting a panel shrinks the grid: no empty cell left in preview or export
    await page.getByRole("button", { name: "删除面板 (b)" }).click();
    await expect(page.locator(".js-plotly-plot")).toHaveCount(1);
    await expect(page.getByText(/1×1 版面/)).toBeVisible();

    await page.goto("/reports");
    await page.getByRole("button", { name: /UI-.*单轴拉伸 v2/ }).first().click();
    const frame = page.frameLocator("iframe[title='分析报告']");
    await expect(frame.getByRole("heading", { name: "单轴拉伸分析报告" })).toBeVisible();
    await expect(frame.getByText("不包含 AI 生成的解释")).toBeVisible();

    // “分析” reopens the experiment last viewed instead of an empty page
    await page.getByRole("link", { name: "分析", exact: true }).click();
    await expect(page).toHaveURL(/\/analysis\/\d+$/);
    await expect(page.getByText("初始模量 E")).toBeVisible();
  });

  test("使用说明：目录、搜索", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("link", { name: "使用说明" }).click();
    await expect(page.getByRole("heading", { name: "快速开始" })).toBeVisible();
    await axe(page, "使用说明");
    await page.getByLabel("搜索使用说明").fill("65,535");
    const toc = page.getByRole("navigation", { name: "使用说明目录" });
    await expect(toc.getByRole("button", { name: "支持的数据文件" })).toBeVisible();
    await expect(toc.getByRole("button", { name: "DMA" })).toHaveCount(0);
    await toc.getByRole("button", { name: "常见问题" }).click();
    await expect(page.getByRole("heading", { name: "常见问题" })).toBeInViewport();
  });

  test("设置：外观切换；键盘隐藏侧边栏；Origin 未连接时清楚降级", async ({ page, request }) => {
    await page.goto("/settings");
    await axe(page, "设置");
    await page.getByLabel("外观", { exact: true }).click();
    await page.getByRole("option", { name: "深色" }).click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await page.getByLabel("外观", { exact: true }).click();
    await page.getByRole("option", { name: "浅色" }).click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    const origin = await (await request.get("/api/origin/status")).json();
    const unavailable = origin.mode === "local"
      ? /本机 Origin 组件缺失/
      : /尚未设置 Windows Bridge 地址/;
    await expect(page.getByText(unavailable)).toBeVisible(); // e2e backend has no bundled bridge

    const nav = page.getByRole("complementary", { name: "主导航" });
    const primary = await page.locator("html").getAttribute("data-platform") === "macos" ? "Meta" : "Control";
    await page.keyboard.press(`${primary}+Alt+KeyS`);
    await expect(nav).toHaveCount(0);
    await page.keyboard.press(`${primary}+Alt+KeyS`);
    await expect(nav).toBeVisible();
  });

  test("材料数据库：每次分析一个条目、性能对比图；删除分析版本", async ({ page }) => {
    const specimen = `UI-${test.info().project.name}`;
    await page.goto("/materials");
    await page.getByRole("button", { name: new RegExp(materialName) }).click();
    const entries = page.getByRole("list", { name: "条目" });
    await expect(entries.getByRole("button", { name: new RegExp(`${specimen} · 单轴拉伸 v2`) })).toBeVisible();
    await entries.getByRole("button", { name: new RegExp(`${specimen} · 单轴拉伸 v1`) }).click();
    await expect(page.getByText(/分析 #\d+ · .* · 模量拟合 λ 1–1.05/).last()).toBeVisible();
    await page.getByRole("tab", { name: "性能对比图" }).click();
    const comparison = page.getByRole("figure", { name: /性能对比图/ });
    await expect(comparison).toBeVisible();
    await expect(comparison.locator(".textpoint text")).toContainText([`${materialName} v2`]);
    await expect(comparison.getByText(`${specimen} v2`, { exact: true })).toHaveCount(0);
    await axe(page, "材料数据库（性能对比图）");

    // deleting a version asks first, removes only that version, and the database follows
    await page.goto(analysisUrl);
    await page.getByRole("button", { name: "删除分析版本 v1" }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByText("此操作不能撤销。")).toBeVisible();
    await dialog.getByRole("button", { name: "删除", exact: true }).click();
    await expect(page.getByRole("button", { name: /^v1 ·/ })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /^v2 ·/ })).toBeVisible();
    await page.goto("/materials");
    await page.getByRole("button", { name: new RegExp(materialName) }).click();
    await expect(page.getByRole("list", { name: "条目" }).getByRole("button", { name: new RegExp(`${specimen} · 单轴拉伸 v1`) })).toHaveCount(0);

    await page.goto(analysisUrl);
    await page.getByRole("button", { name: "按当前参数新建版本" }).click();
    await expect(page.getByRole("button", { name: /^v3 ·/ })).toBeVisible();
    await page.goto("/plots");
    await page.locator("section").filter({ has: page.getByRole("heading", { name: "已保存的图", exact: true }) }).getByRole("button", { name: `SYN saved ${test.info().project.name}`, exact: true }).click();
    await expect(page.locator(".js-plotly-plot .legendtext")).toHaveText([`${materialName} v2`, `${materialName} v1`]);
    await expect(page.getByRole("button", { name: "恢复默认", exact: true })).toBeDisabled();
    await page.getByRole("button", { name: `把 ${materialName} v3 添加到面板 (a)`, exact: true }).click();
    await expect(page.locator(".js-plotly-plot .legendtext")).toHaveText([`${materialName} v2`, `${materialName} v1`, `${materialName} v3`]);
  });
});
