/** Data corrections (zero offset, contact shift, baseline, smoothing): preview before/after, save, deactivate.
 * Corrections apply to analyses run afterwards; earlier versions keep their inputs. */
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Plus } from "lucide-react";
import { api } from "@/lib/api";
import { fmt } from "@/lib/units";
import { Chart, PALETTE } from "@/components/Chart";
import { StatusLine } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";

type Correction = { id: number; quantity: string; quantity_label: string; algorithm: string; params: Record<string, unknown>; operator: string; timestamp: string; active: boolean };
type ListOut = { quantities: { id: string; label: string }[]; corrections: Correction[] };
type Preview = { record: { params: Record<string, unknown> }; x_key: string; x: number[]; before: number[]; after: number[]; n_points: number };

export const ALGORITHMS: Record<string, string> = {
  zero_offset: "零点校正",
  shift_to_contact: "位移按接触点归零",
  linear_baseline: "线性基线扣除",
  savgol: "Savitzky–Golay 平滑",
  moving_average: "滑动平均平滑",
};

/** SI → display unit for the quantities that can be corrected. */
const DISPLAY: Record<string, [string, number, number]> = {
  force: ["N", 1, 0],
  displacement: ["mm", 1e3, 0],
  nominal_stress: ["MPa", 1e-6, 0],
  true_stress: ["MPa", 1e-6, 0],
  storage_modulus: ["MPa", 1e-6, 0],
  loss_modulus: ["MPa", 1e-6, 0],
  temperature: ["°C", 1, -273.15],
  time: ["s", 1, 0],
  crack_length: ["mm", 1e3, 0],
  crack_extension: ["mm", 1e3, 0],
  peel_force: ["N", 1, 0],
  frequency: ["Hz", 1, 0],
};
const disp = (q: string) => DISPLAY[q] ?? ["", 1, 0];
const toDisplay = (q: string, v: number) => v * disp(q)[1] + disp(q)[2];
const toSI = (q: string, v: number) => (v - disp(q)[2]) / disp(q)[1];
const unitText = (q: string) => (disp(q)[0] ? ` (${disp(q)[0]})` : "");

export function describe(c: { algorithm: string; params: Record<string, unknown> }): string {
  const p = c.params;
  switch (c.algorithm) {
    case "zero_offset":
      return `前 ${p.n_points} 点均值 ${fmt(p.offset as number)}（SI）`;
    case "shift_to_contact":
      return `阈值 ${fmt(p.threshold as number)}，接触点 #${p.contact_index}`;
    case "linear_baseline":
      return `区间点 ${p.start}–${p.stop}，斜率 ${fmt(p.slope as number)}`;
    case "savgol":
      return `窗口 ${p.window}，阶数 ${p.polyorder}`;
    case "moving_average":
      return `窗口 ${p.window}`;
    default:
      return JSON.stringify(p);
  }
}

export function CorrectionsPanel({ experimentId }: { experimentId: number }) {
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["corrections", experimentId], queryFn: () => api.get<ListOut>(`/experiments/${experimentId}/corrections`) });
  const [open, setOpen] = useState(false);
  const deactivate = useMutation({
    mutationFn: (id: number) => api.post(`/corrections/${id}/deactivate`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["corrections", experimentId] });
      toast.success("已停用：之后的计算不再使用该修正（记录保留）");
    },
    onError: (e: Error) => toast.error(e.message),
  });
  const active = list.data?.corrections.filter((c) => c.active) ?? [];
  const inactive = (list.data?.corrections.length ?? 0) - active.length;
  return (
    <section className="space-y-2" aria-label="数据修正">
      <div className="flex items-center justify-between">
        <h3 className="text-headline font-semibold">数据修正</h3>
        <Button size="sm" variant="outline" onClick={() => setOpen(true)} disabled={!list.data}><Plus className="size-4" aria-hidden />添加修正…</Button>
      </div>
      {active.length === 0 ? (
        <p className="text-subhead text-fg-2">未使用修正，计算基于原始数据。</p>
      ) : (
        <ol className="space-y-1.5">
          {active.map((c, i) => (
            <li key={c.id} className="rounded-md border bg-content p-2 text-callout">
              <div className="flex items-start justify-between gap-2">
                <span><span className="text-fg-2">{i + 1}.</span> {ALGORITHMS[c.algorithm] ?? c.algorithm} · {c.quantity_label}</span>
                <Button size="sm" variant="ghost" className="h-6 px-2" onClick={() => deactivate.mutate(c.id)} aria-label={`停用修正 ${i + 1}`}>停用</Button>
              </div>
              <p className="text-fg-2">{describe(c)}</p>
              <p className="text-fg-3">{c.operator || "（未填写操作者）"} · {new Date(c.timestamp).toLocaleString("zh-CN")}</p>
            </li>
          ))}
        </ol>
      )}
      <p className="text-subhead text-fg-2">修正按顺序作用于之后的计算；已有版本不变。原始文件始终保持不变。{inactive > 0 && `已停用 ${inactive} 条（记录保留）。`}</p>
      {open && list.data && <CorrectionDialog experimentId={experimentId} quantities={list.data.quantities} onClose={() => setOpen(false)} />}
    </section>
  );
}

function CorrectionDialog({ experimentId, quantities, onClose }: { experimentId: number; quantities: ListOut["quantities"]; onClose: () => void }) {
  const qc = useQueryClient();
  const has = (q: string) => quantities.some((x) => x.id === q);
  const [algorithm, setAlgorithm] = useState("zero_offset");
  const [quantity, setQuantity] = useState(quantities.find((q) => q.id === "force" || q.id === "nominal_stress")?.id ?? quantities[0]?.id ?? "");
  const [nPoints, setNPoints] = useState("10");
  const [threshold, setThreshold] = useState("");
  const [xQuantity, setXQuantity] = useState(quantities.find((q) => q.id !== quantity)?.id ?? "");
  const [xMin, setXMin] = useState("");
  const [xMax, setXMax] = useState("");
  const [window, setWindow] = useState("11");
  const [polyorder, setPolyorder] = useState("3");
  const reference = has("force") ? "force" : "nominal_stress";

  useEffect(() => {
    if (algorithm === "shift_to_contact") setQuantity("displacement");
  }, [algorithm]);

  const num = (s: string) => (s.trim() === "" ? NaN : Number(s));
  const body = (): Record<string, unknown> | null => {
    switch (algorithm) {
      case "zero_offset":
        return Number.isInteger(num(nPoints)) ? { algorithm, quantity, n_points: num(nPoints) } : null;
      case "shift_to_contact":
        return Number.isFinite(num(threshold)) ? { algorithm, quantity: "displacement", reference, threshold: toSI(reference, num(threshold)) } : null;
      case "linear_baseline":
        return Number.isFinite(num(xMin)) && Number.isFinite(num(xMax)) ? { algorithm, quantity, x_quantity: xQuantity, x_min: toSI(xQuantity, num(xMin)), x_max: toSI(xQuantity, num(xMax)) } : null;
      case "savgol":
        return { algorithm, quantity, window: num(window), polyorder: num(polyorder) };
      case "moving_average":
        return { algorithm, quantity, window: num(window) };
    }
    return null;
  };
  const b = body();
  const key = JSON.stringify(b);
  const preview = useQuery({
    queryKey: ["correction-preview", experimentId, key],
    queryFn: () => api.post<Preview>(`/experiments/${experimentId}/corrections/preview`, { correction: b }),
    enabled: !!b && !!quantity,
    retry: false,
  });
  const save = useMutation({
    mutationFn: () => api.post(`/experiments/${experimentId}/corrections`, { correction: b }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["corrections", experimentId] });
      toast.success("修正已保存：对之后的计算生效，已有版本不变。点“按当前参数新建版本”重新计算。");
      onClose();
    },
    onError: (e: Error) => toast.error(e.message),
  });
  const q = quantity;
  const xKey = preview.data?.x_key ?? "index";
  const xs = preview.data ? preview.data.x.map((v) => (xKey === "index" ? v : toDisplay(xKey, v))) : [];
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-4xl">
        <DialogHeader>
          <DialogTitle>添加数据修正</DialogTitle>
          <DialogDescription>预览显示修正前（虚线）与修正后（实线）的曲线；已启用的修正已先行作用。保存后记录算法、参数与操作者。</DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 md:grid-cols-[16rem_1fr]">
          <div className="space-y-3">
            <div className="space-y-1">
              <Label htmlFor="c-algo">修正方法</Label>
              <Select value={algorithm} onValueChange={setAlgorithm}>
                <SelectTrigger id="c-algo" className="h-7 w-full"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {Object.entries(ALGORITHMS).map(([k, v]) => (
                    <SelectItem key={k} value={k} disabled={k === "shift_to_contact" && !(has("displacement") && (has("force") || has("nominal_stress")))}>{v}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {algorithm !== "shift_to_contact" && (
              <div className="space-y-1">
                <Label htmlFor="c-q">修正的列</Label>
                <Select value={quantity} onValueChange={setQuantity}>
                  <SelectTrigger id="c-q" className="h-7 w-full"><SelectValue /></SelectTrigger>
                  <SelectContent>{quantities.map((x) => <SelectItem key={x.id} value={x.id}>{x.label}</SelectItem>)}</SelectContent>
                </Select>
              </div>
            )}
            {algorithm === "zero_offset" && <Field id="c-n" label="取开头的点数" value={nPoints} onChange={setNPoints} hint="减去开头这些点的平均值" />}
            {algorithm === "shift_to_contact" && (
              <Field id="c-th" label={`接触阈值（${reference === "force" ? "力" : "名义应力"}${unitText(reference)}）`} value={threshold} onChange={setThreshold} hint="位移以该值首次被超过处为零点（去除松弛段）" />
            )}
            {algorithm === "linear_baseline" && (
              <>
                <div className="space-y-1">
                  <Label htmlFor="c-x">基线横坐标</Label>
                  <Select value={xQuantity} onValueChange={setXQuantity}>
                    <SelectTrigger id="c-x" className="h-7 w-full"><SelectValue /></SelectTrigger>
                    <SelectContent>{quantities.filter((x) => x.id !== quantity).map((x) => <SelectItem key={x.id} value={x.id}>{x.label}</SelectItem>)}</SelectContent>
                  </Select>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <Field id="c-xmin" label={`区间下限${unitText(xQuantity)}`} value={xMin} onChange={setXMin} />
                  <Field id="c-xmax" label={`上限${unitText(xQuantity)}`} value={xMax} onChange={setXMax} />
                </div>
                <p className="text-subhead text-fg-2">在该区间内拟合直线，从整条曲线中扣除。</p>
              </>
            )}
            {(algorithm === "savgol" || algorithm === "moving_average") && (
              <div className="grid grid-cols-2 gap-2">
                <Field id="c-w" label="窗口（奇数点数）" value={window} onChange={setWindow} />
                {algorithm === "savgol" && <Field id="c-p" label="多项式阶数" value={polyorder} onChange={setPolyorder} />}
              </div>
            )}
          </div>
          <div className="min-w-0 space-y-2" role="status" aria-live="polite">
            {!b && <p className="text-fg-2">填写参数后显示预览。</p>}
            {preview.isError && <StatusLine severity="error">{(preview.error as Error).message}</StatusLine>}
            {preview.data && (
              <>
                <Chart
                  ariaLabel="修正前后对比"
                  height={320}
                  xTitle={xKey === "index" ? "数据点序号" : `${quantities.find((x) => x.id === xKey)?.label ?? xKey}${unitText(xKey)}`}
                  yTitle={`${quantities.find((x) => x.id === q)?.label ?? q}${unitText(q)}`}
                  series={[
                    { name: "修正前", x: xs, y: preview.data.before.map((v) => toDisplay(q, v)), dash: "dash", color: PALETTE[2] },
                    { name: "修正后", x: xs, y: preview.data.after.map((v) => toDisplay(q, v)), color: PALETTE[5] },
                  ]}
                />
                <p className="text-subhead text-fg-2">参数：{describe({ algorithm, params: preview.data.record.params })} · 共 {preview.data.n_points} 点（图中为保形下采样）</p>
              </>
            )}
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>取消</Button>
          <Button disabled={!preview.isSuccess || save.isPending} onClick={() => save.mutate()}>{save.isPending ? "正在保存…" : "保存修正"}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Field({ id, label, value, onChange, hint }: { id: string; label: string; value: string; onChange: (v: string) => void; hint?: string }) {
  return (
    <div className="space-y-1">
      <Label htmlFor={id} className="font-normal">{label}</Label>
      <Input id={id} type="number" step="any" inputMode="decimal" className="tnum h-7 text-right" value={value} onChange={(e) => onChange(e.target.value)} />
      {hint && <p className="text-subhead text-fg-2">{hint}</p>}
    </div>
  );
}
