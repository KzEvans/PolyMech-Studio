/** Method-specific charts and result tables. All values arrive in SI and are shown in display units. */
import { Chart, PALETTE, type Series } from "@/components/Chart";
import { KeyValue, Panel } from "@/components/common";
import type { Run } from "@/lib/api";
import { fmt, show } from "@/lib/units";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

const num = (a: (number | null)[] | undefined, f = 1) => (a ?? []).map((v) => (v === null ? null : v * f));

export function UniaxialView({ run }: { run: Run }) {
  const r = run.result;
  const c = run.curves;
  const fit = r.modulus_fit;
  const breakLam = r.break_stretch as number;
  return (
    <div className="space-y-3">
      <Panel>
        <Tabs defaultValue="nominal">
          <TabsList>
            <TabsTrigger value="nominal">名义应力</TabsTrigger>
            <TabsTrigger value="true">真实应力</TabsTrigger>
            <TabsTrigger value="w">应变能密度</TabsTrigger>
            <TabsTrigger value="dmod">微分模量</TabsTrigger>
          </TabsList>
          <TabsContent value="nominal">
            <Chart
              ariaLabel="名义应力–拉伸比曲线，含模量拟合区间与断裂点"
              series={[
                { name: "名义应力", x: c.stretch, y: num(c.nominal_stress_pa, 1e-6) },
                { name: "模量拟合", x: [fit.x_min, fit.x_max], y: [(fit.intercept + fit.slope * fit.x_min) * 1e-6, (fit.intercept + fit.slope * fit.x_max) * 1e-6], dash: "dash", color: PALETTE[5] },
              ]}
              xTitle="拉伸比 λ"
              yTitle="名义应力 σ (MPa)"
              vspan={[fit.x_min, fit.x_max]}
              vlines={[{ x: breakLam, label: r.break_detected ? "断裂" : "末点（未检出断裂）" }]}
            />
          </TabsContent>
          <TabsContent value="true">
            <Chart ariaLabel="真实应力–拉伸比曲线" series={[{ name: "真实应力 ≈ λσ", x: c.stretch, y: num(c.true_stress_pa, 1e-6) }]} xTitle="拉伸比 λ" yTitle="真实应力 (MPa)" />
          </TabsContent>
          <TabsContent value="w">
            <Chart ariaLabel="应变能密度–拉伸比曲线" series={[{ name: "W(λ) = ∫σ_nom dλ", x: c.stretch, y: num(c.strain_energy_density_j_m3, 1e-6) }]} xTitle="拉伸比 λ" yTitle="应变能密度 W (MJ/m³)" />
          </TabsContent>
          <TabsContent value="dmod">
            <Chart ariaLabel="微分模量–拉伸比曲线" series={[{ name: "dσ/dλ", x: c.stretch, y: num(c.differential_modulus_pa, 1e-6) }]} xTitle="拉伸比 λ" yTitle="微分模量 (MPa)"
              vlines={r.hardening?.present ? [{ x: r.hardening.stretch_at_min_modulus, label: "硬化起点" }] : []} />
          </TabsContent>
        </Tabs>
      </Panel>
      <div className="grid gap-3 lg:grid-cols-2">
        <Panel title="结果">
          <KeyValue items={[
            ["初始模量 E", `${show(fit.slope, "Pa")} ± ${show(fit.slope_stderr, "Pa", 2)}`],
            ["拟合区间 / 点数", `λ ∈ [${fmt(fit.x_min)}, ${fmt(fit.x_max)}] · ${fit.n_points} 点`],
            ["R²", fmt(fit.r_squared, 6)],
            ["最大应力", `${show(r.max_stress_pa, "Pa")}（λ = ${fmt(r.stretch_at_max_stress)}）`],
            ["断裂应力", show(r.break_stress_pa, "Pa")],
            ["断裂拉伸比 λ_b", fmt(r.break_stretch)],
            ["断裂伸长率", `${fmt(r.elongation_at_break_percent)} %`],
            ["断裂功 W_f", `${show(r.work_of_fracture_j_m3, "J/m^3")}（数值积分误差 ${show(r.work_of_fracture_numerical_error_j_m3, "J/m^3", 2)}）`],
            ["应变硬化", r.hardening ? (r.hardening.present ? `有，起点 λ ≈ ${fmt(r.hardening.stretch_at_min_modulus)}，末/最小微分模量 ${fmt(r.hardening.ratio_final_to_min)}` : "未见明显硬化") : "数据不足"],
          ]} />
        </Panel>
        <Panel title="拟合残差">
          <Chart ariaLabel="模量拟合残差" height={220} series={[{ name: "残差", x: fit.residuals.map((_: number, i: number) => i + 1), y: fit.residuals.map((v: number) => v * 1e-3), mode: "markers" }]} xTitle="拟合点序号" yTitle="残差 (kPa)" />
        </Panel>
      </div>
    </div>
  );
}

export function CyclicView({ run }: { run: Run }) {
  const c = run.curves;
  const cycles = run.result.cycles as Record<string, any>[]; // eslint-disable-line @typescript-eslint/no-explicit-any
  const overlay: Series[] = cycles.map((cy, i) => {
    const xs: (number | null)[] = [];
    const ys: (number | null)[] = [];
    (c.point_cycle ?? []).forEach((pc, j) => {
      if (pc === cy.index) {
        xs.push(c.stretch[j]);
        ys.push((c.nominal_stress_pa[j] ?? 0) * 1e-6);
      }
    });
    return { name: `第 ${cy.index} 圈（λmax ${fmt(cy.stretch_max, 3)}）`, x: xs, y: ys, color: PALETTE[i % PALETTE.length] };
  });
  const n = cycles.map((cy) => cy.index);
  return (
    <div className="space-y-3">
      <Panel>
        <Tabs defaultValue="overlay">
          <TabsList>
            <TabsTrigger value="overlay">循环曲线叠加</TabsTrigger>
            <TabsTrigger value="hys">滞后能</TabsTrigger>
            <TabsTrigger value="res">残余应变</TabsTrigger>
            <TabsTrigger value="peak">峰值应力</TabsTrigger>
          </TabsList>
          <TabsContent value="overlay"><Chart ariaLabel="循环滞后曲线叠加" series={overlay} xTitle="拉伸比 λ" yTitle="名义应力 σ (MPa)" /></TabsContent>
          <TabsContent value="hys"><Chart ariaLabel="滞后能随循环次数变化" series={[{ name: "W_hys", x: n, y: cycles.map((cy) => (cy.hysteresis_j_m3 ?? null) && cy.hysteresis_j_m3 * 1e-3), mode: "lines+markers" }]} xTitle="循环次数 N" yTitle="滞后能 (kJ/m³)" /></TabsContent>
          <TabsContent value="res"><Chart ariaLabel="残余应变随循环次数变化" series={[{ name: "残余应变", x: n, y: cycles.map((cy) => (cy.residual_strain === null ? null : cy.residual_strain * 100)), mode: "lines+markers", marker: "square" }]} xTitle="循环次数 N" yTitle="残余应变 (%)" /></TabsContent>
          <TabsContent value="peak"><Chart ariaLabel="峰值应力随循环次数变化" series={[{ name: "峰值应力", x: n, y: cycles.map((cy) => cy.peak_stress_pa * 1e-6), mode: "lines+markers" }]} xTitle="循环次数 N" yTitle="峰值应力 (MPa)" /></TabsContent>
        </Tabs>
      </Panel>
      <Panel title="逐循环结果">
        <div className="overflow-x-auto">
          <table className="w-full text-body">
            <thead><tr className="border-b text-left text-fg-2">
              {["圈", "λmax", "峰值应力", "加载功", "卸载功", "滞后能", "滞后比", "残余应变", "闭合"].map((h) => <th key={h} className="py-1 pr-3 font-medium">{h}</th>)}
            </tr></thead>
            <tbody className="tnum">
              {cycles.map((cy) => (
                <tr key={cy.index} className="border-b">
                  <td className="py-1 pr-3">{cy.index}</td>
                  <td className="py-1 pr-3">{fmt(cy.stretch_max)}</td>
                  <td className="py-1 pr-3">{show(cy.peak_stress_pa, "Pa")}</td>
                  <td className="py-1 pr-3">{show(cy.loading_work_j_m3, "J/m^3")}</td>
                  <td className="py-1 pr-3">{show(cy.unloading_work_j_m3, "J/m^3")}</td>
                  <td className="py-1 pr-3">{show(cy.hysteresis_j_m3, "J/m^3")}</td>
                  <td className="py-1 pr-3">{cy.hysteresis_ratio === null ? "—" : `${fmt(cy.hysteresis_ratio * 100, 3)} %`}</td>
                  <td className="py-1 pr-3">{cy.residual_strain === null ? "—" : `${fmt(cy.residual_strain * 100, 3)} %`}</td>
                  <td className="py-1 pr-3">{!cy.complete ? "未完成" : cy.closed ? "是" : "否（滞后能≠完整耗散）"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-subhead text-fg-2">累积滞后能：{show((run.result.cumulative_hysteresis_j_m3 as number[]).at(-1) ?? null, "J/m^3")}</p>
      </Panel>
    </div>
  );
}

export function PureShearView({ run }: { run: Run }) {
  const r = run.result;
  const c = run.curves;
  const lc = r.critical_stretch;
  return (
    <div className="space-y-3">
      <Panel>
        <Chart
          ariaLabel="无裂纹与有裂纹纯剪切样品的应力–拉伸比曲线，含临界拉伸比"
          series={[
            { name: "无裂纹样品", x: c.stretch, y: num(c.nominal_stress_pa, 1e-6) },
            { name: "有裂纹样品", x: c.notched_stretch, y: num(c.notched_stress_pa, 1e-6) },
          ]}
          xTitle="拉伸比 λ"
          yTitle="名义应力 σ (MPa)"
          vlines={[{ x: lc.value, label: `λc ${lc.confirmed ? "" : "（候选）"}` }]}
        />
      </Panel>
      <Panel title="结果">
        <KeyValue items={[
          ["断裂韧性 Gc = H0·W(λc)", <span className={lc.confirmed ? "" : "text-warning"}>{show(r.toughness_j_m2, "J/m^2")}{lc.confirmed ? "" : "（临时：λc 未确认）"}</span>],
          ["W(λc)", show(r.strain_energy_density_at_critical_j_m3, "J/m^3")],
          ["H0", show(r.height_m, "m")],
          ["λc", `${fmt(lc.value)}（${{ manual: "人工输入", photo: "照片", video_frame: "视频帧", time_sync: "时间同步", force_peak_candidate: "力峰值候选" }[lc.method as string] ?? lc.method}${lc.note ? `：${lc.note}` : ""}）`],
          ["λc 定义", r.lambda_c_definition === "crack_onset" ? "裂纹开始增长（刘 p.77）" : "裂纹开始稳态扩展（陈 p.34）"],
          ["Rp/H0 ≈ W(λc)/Wf", fmt(r.process_zone_to_height_ratio, 3)],
          ["无裂纹样品断裂拉伸比", fmt(r.unnotched.break_stretch)],
        ]} />
      </Panel>
    </div>
  );
}

export function FatigueSteadyView({ run }: { run: Run }) {
  const r = run.result;
  return (
    <div className="space-y-3">
      <Panel><Chart ariaLabel="无裂纹样品循环曲线" series={[{ name: "循环记录", x: run.curves.stretch, y: num(run.curves.nominal_stress_pa, 1e-6) }]} xTitle="拉伸比 λ" yTitle="名义应力 σ (MPa)" /></Panel>
      <Panel title="稳态加载条件">
        <KeyValue items={[
          ["稳态判定", r.stabilized ? `已稳定（最后对比变化 ${fmt(r.relative_change * 100, 3)} %）` : `未稳定（变化 ${fmt(r.relative_change * 100, 3)} %）`],
          ["使用循环", `第 ${r.cycle_index} 圈 / 共 ${r.n_complete_cycles} 圈`],
          ["λmin – λmax", `${fmt(r.stretch_min)} – ${fmt(r.stretch_max)}`],
          ["W（稳态加载段）", show(r.energy_density_j_m3, "J/m^3")],
          ["G = H0·W", show(r.loading.energy_release_rate_j_m2, "J/m^2")],
          ["G 约定", r.loading.convention],
        ]} />
      </Panel>
    </div>
  );
}

export function CrackGrowthView({ run }: { run: Run }) {
  const r = run.result;
  return (
    <div className="space-y-3">
      <Panel><Chart ariaLabel="裂纹长度随循环次数变化" series={[{ name: "裂纹长度", x: run.curves.crack_cycles, y: num(run.curves.crack_length_m, 1e3), mode: "lines+markers" }]} xTitle="循环次数 N" yTitle="裂纹长度 c (mm)" /></Panel>
      <Panel title="裂纹扩展速率">
        <KeyValue items={[
          ["状态", r.status === "measured" ? "可测扩展" : "低于检测限（删失观测，不记为 0）"],
          ["dc/dN = Δc/ΔN", r.dc_dn_m_per_cycle === null ? `< ${show(r.detection_limit_m_per_cycle, "m/cycle")}` : show(r.dc_dn_m_per_cycle, "m/cycle")],
          ["检测限 = 分辨率/ΔN", `${show(r.detection_limit_m_per_cycle, "m/cycle")}（${show(r.resolution_m * 1e6, "1")} μm / ${fmt(r.delta_n_cycles)} 次）`],
          ["Δc", show(r.delta_c_m, "m")],
          ["回归斜率", r.regression_slope_m_per_cycle === null ? "观测点不足 3 个" : `${show(r.regression_slope_m_per_cycle, "m/cycle")} ± ${show(r.regression_stderr_m_per_cycle, "m/cycle", 2)}`],
          ["G", `${show(r.loading.energy_release_rate_j_m2, "J/m^2")}（${r.loading.convention}，λ ${fmt(r.loading.stretch_min)}–${fmt(r.loading.stretch_max)}）`],
        ]} />
      </Panel>
    </div>
  );
}

export function ThresholdView({ run }: { run: Run }) {
  const { fit, bracket } = run.result;
  const c = run.curves;
  const series: Series[] = [
    { name: "可测 dc/dN", x: c.g_j_m2, y: num(c.dc_dn_m_per_cycle, 1e9), mode: "markers" },
    { name: "未检出（上界 = 检测限）", x: c.censored_g_j_m2, y: num(c.censored_upper_m_per_cycle, 1e9), mode: "markers", marker: "circle-open", color: PALETTE[5] },
  ];
  if (c.fit_g_j_m2) series.push({ name: "线性外推", x: c.fit_g_j_m2, y: num(c.fit_dc_dn_m_per_cycle, 1e9), dash: "dash", color: PALETTE[4] });
  return (
    <div className="space-y-3">
      <Panel><Chart ariaLabel="dc/dN 与能量释放率 G 的关系及阈值外推" series={series} xTitle="能量释放率 G (J/m²)" yTitle="dc/dN (nm/cycle)"
        vlines={fit.threshold_j_m2 ? [{ x: fit.threshold_j_m2, label: "G0" }] : []} /></Panel>
      <div className="grid gap-3 lg:grid-cols-2">
        <Panel title="线性外推阈值">
          {fit.reportable ? (
            <KeyValue items={[
              ["G0", show(fit.threshold_j_m2, "J/m^2")],
              ["标准误差（delta 法）", show(fit.threshold_stderr_j_m2, "J/m^2", 3)],
              ["95% 置信区间（bootstrap）", fit.ci95_j_m2 ? `${show(fit.ci95_j_m2[0], "J/m^2")} – ${show(fit.ci95_j_m2[1], "J/m^2")}` : "不稳定，未给出"],
              ["R² / 点数", `${fmt(fit.fit.r_squared, 4)} / ${fit.n_measured_used}（删失 ${fit.n_censored} 个未参与拟合）`],
              ["外推距离", show(fit.extrapolation_distance_j_m2, "J/m^2")],
              ["G 约定", fit.convention],
            ]} />
          ) : (
            <div className="space-y-1">
              <p className="font-medium">不报告确定数值，原因：</p>
              <ul className="list-disc pl-5 text-fg-2">{fit.refusal_reasons.map((x: string) => <li key={x}>{x}</li>)}</ul>
            </div>
          )}
        </Panel>
        <Panel title="实验区间">
          <p>{bracket.statement}</p>
        </Panel>
      </div>
    </div>
  );
}
