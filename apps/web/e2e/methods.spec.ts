/** Analysis pages beyond uniaxial (cyclic, pure shear, fatigue, DMA) and data corrections.
 * Experiments are created through the API from SYNTHETIC fixtures; every analysis step is driven
 * through the UI. Each browser project uses its own material so the shared database stays clean. */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

const FIX = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../../fixtures/import");
type Mapping = { column_index: number; quantity: string; unit: string };

async function axe(page: Page, where: string) {
  await page.waitForTimeout(400);
  const res = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
  const bad = res.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(bad.flatMap((v) => v.nodes.map((n) => `${where}: ${v.id} ${n.target.join(" ")}`))).toEqual([]);
}

async function experiment(request: APIRequestContext, file: string | { name: string; text: string }, mappings: Mapping[], meta: Record<string, unknown>): Promise<number> {
  const name = typeof file === "string" ? file : file.name;
  const buffer = typeof file === "string" ? fs.readFileSync(path.join(FIX, file)) : Buffer.from(file.text);
  const up = await request.post("/api/imports", { multipart: { files: { name, mimeType: "text/csv", buffer } } });
  expect(up.ok()).toBeTruthy();
  const raw = (await up.json()).files[0].raw_file_id;
  const res = await request.post("/api/experiments", { data: { raw_file_id: raw, table_index: 0, mappings, ...meta } });
  expect(res.ok(), await res.text()).toBeTruthy();
  return (await res.json()).id;
}

async function calculate(page: Page) {
  await page.getByRole("button", { name: "计算", exact: true }).click();
  await expect(page.getByRole("button", { name: /^v1 ·/ })).toBeVisible();
}

const m = (column_index: number, quantity: string, unit: string): Mapping => ({ column_index, quantity, unit });

test.describe("其他分析页面（SYNTHETIC 数据）", () => {
  test("循环拉伸：分割循环、逐循环表、滞后能曲线", async ({ page, request }, info) => {
    const id = await experiment(request, "SYNTH_cyclic_steps.csv", [m(0, "cycle_number", "dimensionless"), m(1, "stretch", "dimensionless"), m(2, "nominal_stress", "MPa")], {
      material_name: `SYN-CYC-${info.project.name}`, specimen_label: "CYC-1", test_type: "cyclic",
    });
    await page.goto(`/analysis/${id}`);
    await calculate(page);
    await expect(page.getByRole("table").filter({ hasText: "滞后能" })).toBeVisible();
    await page.getByRole("tab", { name: "滞后能" }).click();
    await expect(page.getByRole("figure", { name: "滞后能随循环次数变化" })).toBeVisible();
    await axe(page, "循环拉伸");
  });

  test("纯剪切：选择无裂纹样品、人工确认 λc、得到 Gc", async ({ page, request }, info) => {
    const mat = `SYN-PS-${info.project.name}`;
    const geom = { height_m: 0.01, width_m: 0.06, thickness_m: 0.001, notch_length_m: 0.015 };
    await experiment(request, "SYNTH_pure_shear_unnotched.csv", [m(0, "displacement", "mm"), m(1, "force", "N")], {
      material_name: mat, specimen_label: "PS-U", test_type: "pure_shear_unnotched", ...geom,
    });
    const notched = await experiment(request, "SYNTH_pure_shear_notched.csv", [m(0, "time", "s"), m(1, "displacement", "mm"), m(2, "force", "N")], {
      material_name: mat, specimen_label: "PS-N", test_type: "pure_shear_notched", ...geom,
    });
    await page.goto(`/analysis/${notched}`);
    await expect(page.getByLabel("无裂纹样品（同一材料）")).toContainText("PS-U"); // same material, preselected
    await page.getByLabel("λc", { exact: true }).fill("2.5");
    await page.getByRole("checkbox", { name: /已确认 λc/ }).click();
    await calculate(page);
    const gc = page.getByText("断裂韧性 Gc = H0·W(λc)").locator("..");
    await expect(gc).toContainText("J/m²");
    await expect(gc).not.toContainText("临时");
    await axe(page, "纯剪切");
  });

  test("疲劳：稳态能量 → 裂纹扩展速率", async ({ page, request }, info) => {
    const mat = `SYN-FAT-${info.project.name}`;
    // 30 identical cycles to λ = 1.5 with Mullins-like softening that settles (SYNTHETIC)
    const rows = ["Stretch,Nominal stress (MPa)"];
    for (let k = 0; k < 30; k++) {
      const f = 1 - 0.2 * Math.exp(-k / 3);
      for (let i = k === 0 ? 0 : 1; i < 60; i++) {
        const lam = 1 + (0.5 * i) / 59;
        rows.push(`${lam.toFixed(6)},${((f * 0.4 * (lam - lam ** -3)) ).toPrecision(6)}`);
      }
      for (let i = 1; i < 60; i++) {
        const lam = 1.5 - (0.5 * i) / 59;
        rows.push(`${lam.toFixed(6)},${((0.7 * f * 0.4 * (lam - lam ** -3)) ).toPrecision(6)}`);
      }
    }
    const steady = await experiment(request, { name: `steady_${info.project.name}.csv`, text: rows.join("\n") + "\n" }, [m(0, "stretch", "dimensionless"), m(1, "nominal_stress", "MPa")], {
      material_name: mat, specimen_label: "F-U", test_type: "fatigue_unnotched_cyclic", height_m: 0.01, width_m: 0.06, thickness_m: 0.001,
    });
    await page.goto(`/analysis/${steady}`);
    await calculate(page);
    await expect(page.getByText(/^已稳定/)).toBeVisible();
    await expect(page.getByText("G = H0·W", { exact: true })).toBeVisible();

    const crack = await experiment(request, "SYNTH_fatigue_crack_growth.csv", [m(0, "cycle_number", "dimensionless"), m(1, "crack_length", "mm")], {
      material_name: mat, specimen_label: "F-N", test_type: "fatigue_crack_growth", crack_resolution_m: 2e-5,
    });
    await page.goto(`/analysis/${crack}`);
    await expect(page.getByLabel("加载条件（无裂纹样品稳态分析）")).toContainText("F-U v1");
    await expect(page.getByLabel("裂纹位置测量分辨率")).toHaveValue("20");
    await calculate(page);
    await expect(page.getByText("dc/dN = Δc/ΔN", { exact: true })).toBeVisible();
    await expect(page.getByText(/可测扩展|低于检测限/)).toBeVisible();
    await axe(page, "疲劳裂纹扩展");
  });

  test("DMA：Tg 按定义列出、tan δ 曲线", async ({ page, request }, info) => {
    const id = await experiment(request, "SYNTH_dma.csv", [m(0, "temperature", "°C"), m(1, "storage_modulus", "MPa"), m(2, "loss_modulus", "MPa"), m(3, "loss_factor", "dimensionless")], {
      material_name: `SYN-DMA-${info.project.name}`, specimen_label: "D-1", test_type: "dma",
    });
    await page.goto(`/analysis/${id}`);
    await calculate(page);
    const tg = page.getByRole("table").filter({ hasText: "tan δ 峰" });
    await expect(tg.getByRole("row", { name: /tan δ 峰/ })).toContainText("-15 °C"); // fixture peak
    await expect(tg.getByRole("row", { name: /损耗模量峰/ })).toBeVisible();
    await page.getByRole("tab", { name: "tan δ" }).click();
    await expect(page.getByRole("figure", { name: /tan δ–温度曲线/ })).toBeVisible();
    await axe(page, "DMA");
  });

  test("数据修正：预览、保存、作用于新版本、停用", async ({ page, request }, info) => {
    const id = await experiment(request, "SYNTH_uniaxial_gbk_chinese.csv", [m(0, "time", "s"), m(1, "force", "N"), m(2, "displacement", "mm")], {
      material_name: `SYN-COR-${info.project.name}`, specimen_label: "COR-1", test_type: "uniaxial", thickness_m: 0.001, width_m: 0.002, gauge_length_m: 0.02,
    });
    await page.goto(`/analysis/${id}`);
    const panel = page.getByRole("region", { name: "数据修正" });
    await expect(panel.getByText("未使用修正")).toBeVisible();
    await panel.getByRole("button", { name: /添加修正/ }).click();
    const dialog = page.getByRole("dialog", { name: "添加数据修正" });
    await expect(dialog.getByRole("figure", { name: "修正前后对比" })).toBeVisible(); // default: zero offset of force, 10 points
    await axe(page, "数据修正对话框");
    await dialog.getByRole("button", { name: "保存修正" }).click();
    await expect(panel.getByText("零点校正 · 力")).toBeVisible();
    await calculate(page);
    await expect(page.getByText(/^零点校正（force，前 10 点均值/)).toBeVisible(); // provenance of v1
    await panel.getByRole("button", { name: "停用修正 1" }).click();
    await expect(panel.getByText("已停用 1 条")).toBeVisible();
  });
});
