/** Inspector forms: method parameters for each analysis. Values are sent as typed JSON. */
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type ExperimentDetail, type ExperimentSummary, type Run } from "@/lib/api";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Checkbox } from "@/components/ui/checkbox";

export type Body = Record<string, unknown>;

function Num({ id, label, value, onChange, hint, unit }: { id: string; label: string; value: string; onChange: (v: string) => void; hint?: string; unit?: string }) {
  return (
    <div className="space-y-1">
      <Label htmlFor={id} className="font-normal">{label}</Label>
      <div className="flex items-center gap-1">
        <Input id={id} type="number" step="any" inputMode="decimal" value={value} onChange={(e) => onChange(e.target.value)} className="tnum h-7 text-right" />
        {unit && <span className="w-12 text-subhead text-fg-2">{unit}</span>}
      </div>
      {hint && <p className="text-subhead text-fg-2">{hint}</p>}
    </div>
  );
}

const n = (s: string) => (s.trim() === "" ? null : Number(s));

export function UniaxialParams({ initial, onChange }: { initial?: Body; onChange: (b: Body) => void }) {
  const range = (initial?.modulus_stretch_range as number[]) ?? [1, 1.05];
  const [lo, setLo] = useState(String(range[0]));
  const [hi, setHi] = useState(String(range[1]));
  const [brk, setBrk] = useState(initial?.break_stretch ? String(initial.break_stretch) : "");
  const [smooth, setSmooth] = useState(initial?.smoothing_window ? String(initial.smoothing_window) : "");
  useEffect(() => {
    onChange({ modulus_stretch_range: [n(lo) ?? 1, n(hi) ?? 1.05], break_stretch: n(brk), smoothing_window: n(smooth) });
  }, [lo, hi, brk, smooth]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-2">
        <Num id="lo" label="模量拟合 λ 下限" value={lo} onChange={setLo} />
        <Num id="hi" label="λ 上限" value={hi} onChange={setHi} />
      </div>
      <Num id="brk" label="断裂拉伸比（人工指定）" value={brk} onChange={setBrk} hint="留空则自动检测断裂点" />
      <Num id="smooth" label="微分模量平滑窗口" value={smooth} onChange={setSmooth} hint="Savitzky–Golay，奇数 ≥ 5；留空为不平滑" unit="点" />
    </div>
  );
}

export function CyclicParams({ initial, onChange }: { initial?: Body; onChange: (b: Body) => void }) {
  const [amp, setAmp] = useState(String(initial?.min_amplitude_fraction ?? 0.05));
  const [tol, setTol] = useState(String(initial?.closure_stretch_tol ?? 0.01));
  const [thr, setThr] = useState(String(initial?.residual_stress_threshold_pa ?? 0));
  const [frac, setFrac] = useState(String(initial?.modulus_fraction ?? 0.1));
  useEffect(() => {
    onChange({ min_amplitude_fraction: n(amp), closure_stretch_tol: n(tol), residual_stress_threshold_pa: n(thr), modulus_fraction: n(frac) });
  }, [amp, tol, thr, frac]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="space-y-3">
      <Num id="amp" label="最小循环幅度比例" value={amp} onChange={setAmp} hint="峰谷显著度 / 拉伸比总范围，用于排除噪声" />
      <Num id="tol" label="闭合判据 Δλ" value={tol} onChange={setTol} />
      <Num id="thr" label="残余应变读取应力" value={thr} onChange={setThr} unit="Pa" />
      <Num id="frac" label="加载模量拟合比例" value={frac} onChange={setFrac} />
    </div>
  );
}

export function PureShearParams({ exp, onChange }: { exp: ExperimentDetail; onChange: (b: Body) => void }) {
  const others = useQuery({
    queryKey: ["experiments", "unnotched", exp.material.id],
    queryFn: () => api.get<ExperimentSummary[]>(`/experiments?material_id=${exp.material.id}&test_type=pure_shear_unnotched`),
  });
  const [unnotched, setUnnotched] = useState<string>("");
  const [mode, setMode] = useState<"candidate" | "manual" | "time">("manual");
  const [value, setValue] = useState("");
  const [method, setMethod] = useState("photo");
  const [time, setTime] = useState("");
  const [def, setDef] = useState("crack_onset");
  const [confirmed, setConfirmed] = useState(false);
  useEffect(() => {
    if (!unnotched && others.data?.length) setUnnotched(String(others.data[0].id));
  }, [others.data, unnotched]);
  useEffect(() => {
    const cs =
      mode === "candidate" ? {} : mode === "time" ? { crack_onset_time_s: n(time), method } : { value: n(value), method, confirmed };
    onChange({ unnotched_experiment_id: unnotched ? Number(unnotched) : null, critical_stretch: cs, lambda_c_definition: def });
  }, [unnotched, mode, value, method, time, def, confirmed]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="space-y-3">
      <div className="space-y-1">
        <Label htmlFor="ps-unnotched">无裂纹样品（同一材料）</Label>
        <Select value={unnotched} onValueChange={setUnnotched}>
          <SelectTrigger id="ps-unnotched" className="h-7 w-full"><SelectValue placeholder={others.data?.length ? "选择" : "没有同材料的无裂纹实验"} /></SelectTrigger>
          <SelectContent>{others.data?.map((e) => <SelectItem key={e.id} value={String(e.id)}>#{e.id} {e.specimen.label}</SelectItem>)}</SelectContent>
        </Select>
      </div>
      <div className="space-y-1">
        <Label htmlFor="ps-lc-source">临界拉伸比 λc 来源</Label>
        <Select value={mode} onValueChange={(v) => setMode(v as typeof mode)}>
          <SelectTrigger id="ps-lc-source" className="h-7 w-full"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="manual">人工输入（照片/视频帧判读）</SelectItem>
            <SelectItem value="time">按同步时间（裂纹萌生时刻）</SelectItem>
            <SelectItem value="candidate">力峰值候选（仅供参考，结果为临时值）</SelectItem>
          </SelectContent>
        </Select>
      </div>
      {mode !== "candidate" && (
        <div className="space-y-1">
          <Label htmlFor="ps-lc-method">判读依据</Label>
          <Select value={method} onValueChange={setMethod}>
            <SelectTrigger id="ps-lc-method" className="h-7 w-full"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="photo">照片</SelectItem>
              <SelectItem value="video_frame">视频帧</SelectItem>
              <SelectItem value="manual">人工观察</SelectItem>
            </SelectContent>
          </Select>
        </div>
      )}
      {mode === "manual" && (
        <>
          <Num id="lc" label="λc" value={value} onChange={setValue} />
          <label className="flex items-center gap-2"><Checkbox checked={confirmed} onCheckedChange={(c) => setConfirmed(c === true)} />已确认 λc（未确认的结果为临时值，不入库统计）</label>
        </>
      )}
      {mode === "time" && <Num id="t" label="裂纹萌生时刻" value={time} onChange={setTime} unit="s" hint="需要有裂纹样品数据中有时间列" />}
      <div className="space-y-1">
        <Label htmlFor="ps-lc-def">λc 定义</Label>
        <Select value={def} onValueChange={setDef}>
          <SelectTrigger id="ps-lc-def" className="h-7 w-full"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="crack_onset">裂纹开始增长（刘 p.77）</SelectItem>
            <SelectItem value="steady_propagation">裂纹开始稳态扩展（陈 p.34）</SelectItem>
          </SelectContent>
        </Select>
      </div>
    </div>
  );
}

export function FatigueSteadyParams({ onChange }: { onChange: (b: Body) => void }) {
  const [back, setBack] = useState("10");
  const [tol, setTol] = useState("0.01");
  const [conv, setConv] = useState("G_max");
  useEffect(() => {
    onChange({ compare_back: n(back), tolerance: n(tol), convention: conv });
  }, [back, tol, conv]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="space-y-3">
      <Num id="back" label="稳态比较间隔" value={back} onChange={setBack} unit="圈" hint="比较最后一圈与若干圈之前的加载功" />
      <Num id="tol" label="稳态容差" value={tol} onChange={setTol} hint="相对变化，0.01 = 1%" />
      <div className="space-y-1">
        <Label htmlFor="fat-conv">G 约定</Label>
        <Select value={conv} onValueChange={setConv}>
          <SelectTrigger id="fat-conv" className="h-7 w-full"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="G_max">G_max（加载段 λmin→λmax 积分）</SelectItem>
            <SelectItem value="delta_G">ΔG</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <p className="text-subhead text-fg-2">不同约定的结果不会合并拟合。</p>
    </div>
  );
}

export function CrackGrowthParams({ exp, onChange }: { exp: ExperimentDetail; onChange: (b: Body) => void }) {
  const steady = useQuery({
    queryKey: ["runs", "fatigue_steady", exp.material.id],
    queryFn: () => api.get<{ id: number; experiment_id: number; version: number; status: string; specimen: string; material: number }[]>("/analyses?method=fatigue_steady&limit=200"),
  });
  const options = (steady.data ?? []).filter((r) => r.material === exp.material.id);
  const firstStable = options.find((r) => r.status === "ok");
  const [run, setRun] = useState("");
  const [res, setRes] = useState(exp.crack_resolution_m ? String(exp.crack_resolution_m * 1e6) : "");
  useEffect(() => {
    if (!run && firstStable) setRun(String(firstStable.id));
  }, [firstStable?.id, run]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    onChange({ steady_run_id: run ? Number(run) : null, resolution_m: n(res) === null ? null : n(res)! * 1e-6 });
  }, [run, res]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="space-y-3">
      <div className="space-y-1">
        <Label htmlFor="cg-steady">加载条件（无裂纹样品稳态分析）</Label>
        <Select value={run} onValueChange={setRun}>
          <SelectTrigger id="cg-steady" className="h-7 w-full"><SelectValue placeholder={firstStable ? "选择" : "同材料没有已稳定的能量分析"} /></SelectTrigger>
          <SelectContent>{options.map((r) => <SelectItem key={r.id} value={String(r.id)} disabled={r.status !== "ok"}>#{r.id} {r.specimen} v{r.version}{r.status !== "ok" ? "（未稳定）" : ""}</SelectItem>)}</SelectContent>
        </Select>
      </div>
      <Num id="res" label="裂纹位置测量分辨率" value={res} onChange={setRes} unit="μm" hint="检测限 = 分辨率 / 观测循环数" />
    </div>
  );
}

export function ThresholdParams({ exp, onChange }: { exp: ExperimentDetail; onChange: (b: Body) => void }) {
  const runs = useQuery({
    queryKey: ["runs", "crack_growth", exp.material.id],
    queryFn: () => api.get<{ id: number; version: number; specimen: string; material: number; experiment_id: number }[]>("/analyses?method=crack_growth&limit=500"),
  });
  const latest = new Map<number, { id: number; specimen: string }>();
  (runs.data ?? []).filter((r) => r.material === exp.material.id).forEach((r) => {
    if (!latest.has(r.experiment_id)) latest.set(r.experiment_id, r); // list is newest-first
  });
  const options = [...latest.values()];
  const [chosen, setChosen] = useState<Set<number>>(new Set());
  const [lo, setLo] = useState("");
  const [hi, setHi] = useState("");
  useEffect(() => {
    if (chosen.size === 0 && options.length) setChosen(new Set(options.map((o) => o.id)));
  }, [options.length]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    onChange({ crack_growth_run_ids: [...chosen], attach_experiment_id: exp.id, g_range_j_m2: n(lo) !== null && n(hi) !== null ? [n(lo), n(hi)] : null });
  }, [chosen, lo, hi]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="space-y-3">
      <fieldset className="space-y-1">
        <legend className="text-body font-medium">参与的裂纹扩展结果（同材料，各实验最新版本）</legend>
        {options.map((o) => (
          <label key={o.id} className="flex items-center gap-2">
            <Checkbox checked={chosen.has(o.id)} onCheckedChange={(c) => {
              const s = new Set(chosen);
              if (c === true) s.add(o.id); else s.delete(o.id);
              setChosen(s);
            }} />
            #{o.id} {o.specimen}
          </label>
        ))}
        {options.length === 0 && <p className="text-fg-2">还没有裂纹扩展速率结果</p>}
      </fieldset>
      <div className="grid grid-cols-2 gap-2">
        <Num id="glo" label="拟合 G 下限" value={lo} onChange={setLo} unit="J/m²" />
        <Num id="ghi" label="G 上限" value={hi} onChange={setHi} unit="J/m²" />
      </div>
      <p className="text-subhead text-fg-2">留空则使用全部可测点；低于检测限的观测不参与线性拟合。</p>
    </div>
  );
}

export type { Run };

const toK = (s: string) => (s.trim() === "" ? null : Number(s) + 273.15);
const toC = (k: unknown) => (typeof k === "number" ? String(Number((k - 273.15).toPrecision(6))) : "");

export function DMAParams({ initial, onChange }: { initial?: Body; onChange: (b: Body) => void }) {
  const win = (initial?.tg_window_k as number[] | null) ?? null;
  const base = (initial?.onset_baseline_k as number[] | null) ?? null;
  const [mode, setMode] = useState(String(initial?.deformation_mode ?? "tension"));
  const [wLo, setWLo] = useState(toC(win?.[0]));
  const [wHi, setWHi] = useState(toC(win?.[1]));
  const [bLo, setBLo] = useState(toC(base?.[0]));
  const [bHi, setBHi] = useState(toC(base?.[1]));
  const [ref, setRef] = useState(toC((initial?.reference_temperatures_k as number[] | undefined)?.[0] ?? 298.15));
  const [prom, setProm] = useState(String(initial?.peak_prominence_fraction ?? 0.1));
  const [second, setSecond] = useState(String(initial?.secondary_peak_ratio ?? 0.5));
  const [spike, setSpike] = useState(String(initial?.spike_threshold ?? 6));
  useEffect(() => {
    const pair = (a: string, b: string) => (toK(a) !== null && toK(b) !== null ? [toK(a), toK(b)] : null);
    onChange({
      deformation_mode: mode,
      tg_window_k: pair(wLo, wHi),
      onset_baseline_k: pair(bLo, bHi),
      reference_temperatures_k: toK(ref) === null ? [] : [toK(ref)],
      peak_prominence_fraction: n(prom),
      secondary_peak_ratio: n(second),
      spike_threshold: n(spike),
    });
  }, [mode, wLo, wHi, bLo, bHi, ref, prom, second, spike]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="space-y-3">
      <div className="space-y-1">
        <Label htmlFor="dmode" className="font-normal">形变模式</Label>
        <Select value={mode} onValueChange={setMode}>
          <SelectTrigger id="dmode" className="h-7 w-full"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="tension">拉伸（E′、E″）</SelectItem>
            <SelectItem value="shear">剪切（G′、G″）</SelectItem>
            <SelectItem value="unknown">未知</SelectItem>
          </SelectContent>
        </Select>
        <p className="text-subhead text-fg-2">只用于标注与比较分组，不改变计算。</p>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <Num id="wlo" label="Tg 搜索下限" value={wLo} onChange={setWLo} unit="°C" />
        <Num id="whi" label="上限" value={wHi} onChange={setWHi} unit="°C" />
      </div>
      <p className="text-subhead text-fg-2">留空为全范围；出现多个显著峰时用它限定要报告的转变。</p>
      <div className="grid grid-cols-2 gap-2">
        <Num id="blo" label="E′ 起始基线下限" value={bLo} onChange={setBLo} unit="°C" />
        <Num id="bhi" label="上限" value={bHi} onChange={setBHi} unit="°C" />
      </div>
      <p className="text-subhead text-fg-2">留空为最低 10 % 温度范围（玻璃态平台）。</p>
      <Num id="tref" label="参考温度" value={ref} onChange={setRef} unit="°C" hint="报告该温度下的 E′、E″、tan δ（只插值不外推）" />
      <Num id="prom" label="峰显著性比例" value={prom} onChange={setProm} hint="峰的显著度 / 曲线范围" />
      <Num id="second" label="多峰判定比例" value={second} onChange={setSecond} hint="次峰显著度 ≥ 主峰 × 该比例时视为多峰" />
      <Num id="spike" label="异常点阈值（稳健 z）" value={spike} onChange={setSpike} />
    </div>
  );
}
