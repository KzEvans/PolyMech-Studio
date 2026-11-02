import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ChevronDown, FileUp, Sparkles } from "lucide-react";
import { api, ApiError, type CheckResult, type ImportFile, type ImportTable, type Suggestion, type Vocabulary } from "@/lib/api";
import { fromMm } from "@/lib/units";
import { cn } from "@/lib/utils";
import { Toolbar } from "@/components/shell/AppShell";
import { Chart } from "@/components/Chart";
import { EmptyState, FlagList, Panel, StatusLine } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";

const IGNORE = "__ignore";

type Row = { column_index: number; header: string; quantity: string; unit: string; suggestion: Suggestion; confirmed: boolean };
type TableKey = `${number}:${number}`;

function rowsFrom(t: ImportTable): Row[] {
  return t.suggestions.map((s) => ({
    column_index: s.column_index,
    header: s.header,
    quantity: s.quantity ?? IGNORE,
    unit: s.unit ?? "",
    suggestion: s,
    confirmed: !s.needs_confirmation,
  }));
}

// Metadata fields shown in the form; lengths are entered in mm, stored in SI.
const FIELDS: { key: string; label: string; kind: "text" | "mm" | "num" | "date"; unit?: string }[] = [
  { key: "thickness_m", label: "样品厚度", kind: "mm", unit: "mm" },
  { key: "width_m", label: "样品宽度", kind: "mm", unit: "mm" },
  { key: "gauge_length_m", label: "初始标距 L0", kind: "mm", unit: "mm" },
  { key: "height_m", label: "可拉伸高度 H0", kind: "mm", unit: "mm" },
  { key: "notch_length_m", label: "预切裂纹长度 c0", kind: "mm", unit: "mm" },
  { key: "crack_resolution_m", label: "裂纹位置分辨率", kind: "num", unit: "μm" },
  { key: "temperature_c", label: "测试温度", kind: "num", unit: "°C" },
  { key: "stretch_rate_per_s", label: "拉伸速率", kind: "num", unit: "s⁻¹" },
  { key: "cycle_frequency_hz", label: "循环频率", kind: "num", unit: "Hz" },
  { key: "precycles", label: "预循环次数", kind: "num" },
  { key: "instrument", label: "仪器名称", kind: "text" },
  { key: "fixture", label: "夹具类型", kind: "text" },
  { key: "test_date", label: "测试日期", kind: "date" },
];

export default function ImportPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const vocab = useQuery({ queryKey: ["vocabulary"], queryFn: () => api.get<Vocabulary>("/vocabulary") });
  const [files, setFiles] = useState<ImportFile[]>([]);
  const [errors, setErrors] = useState<{ file: string; error: string }[]>([]);
  const [selected, setSelected] = useState<TableKey | null>(null);
  const [rows, setRows] = useState<Record<TableKey, Row[]>>({});
  const [testType, setTestType] = useState("uniaxial");
  const [meta, setMeta] = useState<Record<string, string>>({ material_name: "", specimen_label: "", batch: "", notes: "" });
  const [check, setCheck] = useState<CheckResult | null>(null);
  const [aiOpen, setAiOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  const current = useMemo(() => {
    if (!selected) return null;
    const [fid, ti] = selected.split(":").map(Number);
    const f = files.find((x) => x.raw_file_id === fid);
    return f ? { file: f, table: f.tables[ti] } : null;
  }, [selected, files]);
  const currentRows = selected ? (rows[selected] ?? []) : [];

  const upload = useMutation({
    mutationFn: (list: File[]) => api.upload<{ files: ImportFile[]; errors: { file: string; error: string }[] }>("/imports", list),
    onSuccess: (res) => {
      setFiles((prev) => [...prev, ...res.files]);
      setErrors(res.errors);
      const next: Record<TableKey, Row[]> = {};
      res.files.forEach((f) => f.tables.forEach((t) => (next[`${f.raw_file_id}:${t.index}`] = rowsFrom(t))));
      setRows((r) => ({ ...r, ...next }));
      const first = res.files[0];
      if (first) setSelected(`${first.raw_file_id}:0`);
      if (res.errors.length) toast.error(`${res.errors.length} 个文件无法读取`);
    },
    onError: (e: Error) => toast.error(e.message),
  });

  useEffect(() => setCheck(null), [selected]);

  const mapped = currentRows.filter((r) => r.quantity !== IGNORE);
  const unconfirmed = currentRows.filter((r) => r.quantity !== IGNORE && !r.confirmed);
  const missingUnit = mapped.filter((r) => !r.unit.trim());
  const required = useQuery({
    queryKey: ["required", testType, mapped.map((r) => r.quantity).join(",")],
    queryFn: () => api.get<{ field: string; label: string }[]>(`/metadata/required?test_type=${testType}&quantities=${mapped.map((r) => r.quantity).join(",")}`),
    enabled: !!current,
  });
  const requiredSet = new Set((required.data ?? []).map((r) => r.field));
  const missingMeta = (required.data ?? []).filter((r) => {
    if (r.field === "material_name") return !meta.material_name?.trim();
    const v = meta[r.field];
    return !v || !(Number(v) > 0);
  });

  const mappingsBody = () => mapped.map((r) => ({ column_index: r.column_index, quantity: r.quantity, unit: r.unit.trim() }));

  const runCheck = useMutation({
    mutationFn: () =>
      api.post<CheckResult>(`/imports/${current!.file.raw_file_id}/tables/${current!.table.index}/check`, { test_type: testType, mappings: mappingsBody() }),
    onSuccess: setCheck,
    onError: (e: Error) => toast.error(e.message),
  });

  const create = useMutation({
    mutationFn: () => {
      const num = (k: string) => (meta[k]?.trim() ? Number(meta[k]) : null);
      const body: Record<string, unknown> = {
        raw_file_id: current!.file.raw_file_id,
        table_index: current!.table.index,
        mappings: mapped.map((r) => ({
          column_index: r.column_index,
          quantity: r.quantity,
          unit: r.unit.trim(),
          source: r.suggestion.source === "rules" && r.quantity === r.suggestion.quantity && r.unit === (r.suggestion.unit ?? "") ? "rules" : r.suggestion.source.startsWith("ai") || r.suggestion.source.startsWith("rules+ai") ? r.suggestion.source : "user",
          confidence: r.suggestion.confidence,
        })),
        material_name: meta.material_name.trim(),
        specimen_label: meta.specimen_label.trim() || current!.table.sheet || current!.file.file_name,
        batch: meta.batch?.trim() ?? "",
        test_type: testType,
        notes: meta.notes ?? "",
        instrument: meta.instrument ?? "",
        fixture: meta.fixture ?? "",
        test_date: meta.test_date ?? "",
        stretch_rate_per_s: num("stretch_rate_per_s"),
        cycle_frequency_hz: num("cycle_frequency_hz"),
        precycles: num("precycles"),
        temperature_k: num("temperature_c") === null ? null : num("temperature_c")! + 273.15,
        crack_resolution_m: num("crack_resolution_m") === null ? null : num("crack_resolution_m")! * 1e-6,
      };
      for (const k of ["thickness_m", "width_m", "gauge_length_m", "height_m", "notch_length_m"]) body[k] = fromMm(meta[k] ?? "");
      return api.post<{ id: number }>("/experiments", body);
    },
    onSuccess: (exp) => {
      qc.invalidateQueries({ queryKey: ["experiments"] });
      toast.success("实验已创建，原始文件已归档");
      navigate(`/analysis/${exp.id}`);
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const setRow = (i: number, patch: Partial<Row>) =>
    setRows((r) => ({ ...r, [selected!]: r[selected!].map((x, j) => (j === i ? { ...x, ...patch, confirmed: patch.confirmed ?? true } : x)) }));

  const onFiles = (list: FileList | null) => list && list.length && upload.mutate(Array.from(list));
  const canCheck = !!current && mapped.length > 0 && unconfirmed.length === 0 && missingUnit.length === 0;
  const canCreate = canCheck && !!check && !check.issues.some((i) => i.severity === "error") && missingMeta.length === 0 && !!meta.material_name.trim();

  return (
    <>
      <Toolbar title="导入数据" subtitle={current ? `${current.file.file_name}${current.table.sheet ? ` · ${current.table.sheet}` : ""}` : undefined}>
        <input ref={inputRef} type="file" multiple accept=".csv,.tsv,.txt,.dat,.xlsx,.xlsm,.xls" className="hidden" onChange={(e) => onFiles(e.target.files)} aria-label="选择数据文件" />
        <Button size="sm" variant="outline" onClick={() => inputRef.current?.click()} disabled={upload.isPending}>
          <FileUp className="size-4" aria-hidden />
          {upload.isPending ? "正在读取…" : "添加文件…"}
        </Button>
        <Button size="sm" variant="outline" disabled={!current} onClick={() => setAiOpen(true)}>
          <Sparkles className="size-4" aria-hidden />
          AI 识别列…
        </Button>
        <Button size="sm" disabled={!canCreate || create.isPending} onClick={() => create.mutate()}>
          {create.isPending ? "正在创建…" : "创建实验"}
        </Button>
      </Toolbar>

      {files.length === 0 ? (
        <main
          className={cn("m-4 flex flex-1 items-center justify-center rounded-lg border-2 border-dashed bg-content", dragging && "border-[var(--accent-text)]")}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            onFiles(e.dataTransfer.files);
          }}
        >
          <EmptyState title="把仪器导出的数据文件拖到这里">
            支持 CSV、TSV、TXT、XLSX（多工作表）与批量导入；中文/英文表头、GBK 与 UTF-8 编码、仪器说明行、多层表头会自动识别。原始文件只读归档，不会被修改。
            <div className="mt-3">
              <Button size="sm" onClick={() => inputRef.current?.click()}>选择文件…</Button>
            </div>
            {errors.length > 0 && <FlagList flags={errors.map((e) => ({ code: "file", severity: "error" as const, message: `${e.file}：${e.error}` }))} />}
          </EmptyState>
        </main>
      ) : (
        <div className="flex min-h-0 flex-1">
          {/* table list */}
          <nav aria-label="已导入的表格" className="w-56 shrink-0 overflow-auto border-r bg-inspector p-2">
            {files.map((f) => (
              <div key={f.raw_file_id} className="mb-2">
                <p className="truncate px-2 text-subhead font-medium text-fg-2" title={f.file_name}>{f.file_name}</p>
                {f.tables.map((t) => {
                  const k = `${f.raw_file_id}:${t.index}` as TableKey;
                  const pending = (rows[k] ?? []).filter((r) => r.quantity !== IGNORE && !r.confirmed).length;
                  return (
                    <button
                      key={k}
                      type="button"
                      onClick={() => setSelected(k)}
                      aria-current={selected === k}
                      className={cn("flex w-full items-center justify-between rounded-md px-2 py-1 text-left hover:bg-hover", selected === k && "bg-hover font-medium")}
                    >
                      <span className="truncate">{t.sheet ?? "表格"} · {t.n_rows} 行</span>
                      {pending > 0 && <Badge variant="outline" className="text-warning">{pending} 待确认</Badge>}
                    </button>
                  );
                })}
              </div>
            ))}
            {errors.map((e) => (
              <StatusLine key={e.file} severity="error" className="px-2 text-subhead">{e.file}：{e.error}</StatusLine>
            ))}
          </nav>

          {/* mapping + preview */}
          <main className="min-w-0 flex-1 space-y-3 overflow-auto p-3">
            {current && (
              <>
                <Panel
                  title="列映射"
                  actions={
                    <span className="text-subhead text-fg-2">
                      编码 {current.table.encoding ?? "Excel"} · {current.table.profile ? `已套用仪器规则“${current.table.profile}”` : "规则识别"}
                    </span>
                  }
                >
                  <MappingTable rows={currentRows} vocab={vocab.data} table={current.table} onChange={setRow} />
                  <div className="mt-2 flex flex-wrap items-center gap-3">
                    {unconfirmed.length > 0 && <StatusLine severity="warning">还有 {unconfirmed.length} 列需要确认（勾选“已确认”或修改映射）</StatusLine>}
                    {missingUnit.length > 0 && <StatusLine severity="warning">{missingUnit.map((r) => r.header).join("、")} 未指定单位</StatusLine>}
                    <Button size="sm" variant="ghost" onClick={() => setProfileOpen(true)} disabled={!canCheck}>
                      保存为仪器导入规则…
                    </Button>
                  </div>
                </Panel>
                {current.table.preamble.length > 0 && (
                  <Collapsible>
                    <CollapsibleTrigger className="flex items-center gap-1 text-subhead text-fg-2 hover:text-fg-1">
                      <ChevronDown className="size-3" aria-hidden /> 文件说明行（{current.table.preamble.length} 行）
                    </CollapsibleTrigger>
                    <CollapsibleContent>
                      <pre className="mt-1 max-h-40 overflow-auto rounded-md border bg-content p-2 font-mono text-callout">{current.table.preamble.join("\n")}</pre>
                    </CollapsibleContent>
                  </Collapsible>
                )}
                <Panel title="数据检查与预览">
                  {!check ? (
                    <p className="text-fg-2">确认映射并选择测试类型后，点击右侧“检查数据”。检查只标注问题，不会删除或修改任何数据。</p>
                  ) : (
                    <div className="space-y-3">
                      <FlagList flags={check.issues} empty="没有发现数据质量问题" />
                      <PreviewChart check={check} vocab={vocab.data} />
                    </div>
                  )}
                </Panel>
              </>
            )}
          </main>

          {/* inspector */}
          <aside aria-label="实验信息" className="w-80 shrink-0 space-y-4 overflow-auto border-l bg-inspector p-3">
            <div className="space-y-1.5">
              <Label htmlFor="test-type">测试类型</Label>
              <Select value={testType} onValueChange={(v) => { setTestType(v); setCheck(null); }}>
                <SelectTrigger id="test-type" className="h-7 w-full"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {vocab.data?.test_types.map((t) => <SelectItem key={t.id} value={t.id}>{t.label}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <Button className="w-full" size="sm" variant="outline" disabled={!canCheck || runCheck.isPending} onClick={() => runCheck.mutate()}>
              {runCheck.isPending ? "正在检查…" : "检查数据"}
            </Button>
            <fieldset className="space-y-2">
              <legend className="mb-1 text-headline font-semibold">材料与样品</legend>
              <Field id="material_name" label="材料名称" required value={meta.material_name} onChange={(v) => setMeta({ ...meta, material_name: v })} />
              <Field id="specimen_label" label="样品编号" value={meta.specimen_label} placeholder={current?.table.sheet ?? "如 U-01"} onChange={(v) => setMeta({ ...meta, specimen_label: v })} />
              <Field id="batch" label="批次" value={meta.batch} onChange={(v) => setMeta({ ...meta, batch: v })} />
            </fieldset>
            <fieldset className="space-y-2">
              <legend className="mb-1 text-headline font-semibold">尺寸与条件</legend>
              {FIELDS.map((f) => (
                <Field
                  key={f.key}
                  id={f.key}
                  label={f.label}
                  unit={f.unit}
                  type={f.kind === "text" ? "text" : f.kind === "date" ? "date" : "number"}
                  required={requiredSet.has(f.key)}
                  value={meta[f.key] ?? ""}
                  onChange={(v) => setMeta({ ...meta, [f.key]: v })}
                />
              ))}
              <div className="space-y-1">
                <Label htmlFor="notes">实验备注</Label>
                <Textarea id="notes" rows={2} value={meta.notes} onChange={(e) => setMeta({ ...meta, notes: e.target.value })} />
              </div>
            </fieldset>
            {missingMeta.length > 0 && (
              <StatusLine severity="warning">计算还需要：{missingMeta.map((m) => m.label).join("、")}。缺少尺寸时不会假设默认值。</StatusLine>
            )}
          </aside>
        </div>
      )}

      {current && (
        <AiDialog open={aiOpen} onOpenChange={setAiOpen} rawFileId={current.file.raw_file_id} tableIndex={current.table.index}
          onResult={(sugg) => setRows((r) => ({ ...r, [selected!]: rowsFrom({ ...current.table, suggestions: sugg }) }))} />
      )}
      {current && (
        <ProfileDialog open={profileOpen} onOpenChange={setProfileOpen} rawFileId={current.file.raw_file_id} tableIndex={current.table.index} mappings={mappingsBody()} />
      )}
    </>
  );
}

function Field({ id, label, value, onChange, unit, type = "text", required, placeholder }: {
  id: string; label: string; value: string; onChange: (v: string) => void; unit?: string; type?: string; required?: boolean; placeholder?: string;
}) {
  return (
    <div className="grid grid-cols-[1fr_7.5rem] items-center gap-2">
      <Label htmlFor={id} className="font-normal">
        {label}
        {required && <span className="ml-0.5 text-danger" aria-label="必填">*</span>}
      </Label>
      <div className="flex items-center gap-1">
        <Input id={id} type={type} inputMode={type === "number" ? "decimal" : undefined} step="any" value={value} placeholder={placeholder}
          required={required} aria-required={required} onChange={(e) => onChange(e.target.value)} className="tnum h-7 px-2 text-right" />
        {unit && <span className="w-7 shrink-0 text-subhead text-fg-2">{unit}</span>}
      </div>
    </div>
  );
}

function MappingTable({ rows, vocab, table, onChange }: { rows: Row[]; vocab?: Vocabulary; table: ImportTable; onChange: (i: number, p: Partial<Row>) => void }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-body">
        <thead>
          <tr className="border-b text-left text-fg-2">
            <th className="py-1.5 pr-2 font-medium">原始列</th>
            <th className="py-1.5 pr-2 font-medium">样例值</th>
            <th className="py-1.5 pr-2 font-medium">物理量</th>
            <th className="py-1.5 pr-2 font-medium">单位</th>
            <th className="py-1.5 pr-2 font-medium">置信度与依据</th>
            <th className="py-1.5 font-medium">已确认</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => {
            const col = table.columns[r.column_index];
            const s = r.suggestion;
            return (
              <tr key={r.column_index} className="border-b align-top">
                <td className="py-1.5 pr-2">
                  <div className="font-medium">{r.header}</div>
                  <div className="text-subhead text-fg-2">文件中单位：{col.unit_text ?? "未给出"}{col.n_missing ? ` · 缺失 ${col.n_missing}` : ""}{col.n_non_numeric ? ` · 非数值 ${col.n_non_numeric}` : ""}</div>
                </td>
                <td className="tnum py-1.5 pr-2 text-fg-2">{col.preview.slice(0, 3).map((v) => (v === null ? "—" : v)).join(", ")}</td>
                <td className="py-1.5 pr-2">
                  <Select value={r.quantity} onValueChange={(v) => onChange(i, { quantity: v })}>
                    <SelectTrigger aria-label={`${r.header} 的物理量`} className="h-7 w-40"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value={IGNORE}>忽略该列</SelectItem>
                      {vocab?.quantities.map((q) => <SelectItem key={q.id} value={q.id}>{q.label}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </td>
                <td className="py-1.5 pr-2">
                  <Input aria-label={`${r.header} 的单位`} value={r.unit} disabled={r.quantity === IGNORE} placeholder="必填" onChange={(e) => onChange(i, { unit: e.target.value })} className="h-7 w-24" />
                </td>
                <td className="py-1.5 pr-2">
                  <div className="flex items-center gap-1.5">
                    <Badge variant="outline" className={cn("tnum", s.confidence >= 0.8 ? "text-success" : "text-warning")}>{Math.round(s.confidence * 100)}%</Badge>
                    <span className="text-subhead text-fg-2">{s.source.startsWith("rules+ai") ? "规则+AI 一致" : s.source.startsWith("ai") ? "AI" : s.source.startsWith("profile") ? "仪器规则" : "规则"}</span>
                  </div>
                  {s.ambiguities.map((a) => <StatusLine key={a} severity="warning" className="mt-1 text-subhead">{a}</StatusLine>)}
                  {s.rationale.length > 0 && <p className="mt-1 text-subhead text-fg-2">{s.rationale.join("；")}</p>}
                </td>
                <td className="py-1.5">
                  <Checkbox checked={r.confirmed} disabled={r.quantity === IGNORE} aria-label={`确认 ${r.header} 的映射`} onCheckedChange={(c) => onChange(i, { confirmed: c === true })} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function PreviewChart({ check, vocab }: { check: CheckResult; vocab?: Vocabulary }) {
  const label = (q: string) => vocab?.quantities.find((x) => x.id === q)?.label ?? q;
  const unitOf = (q: string) => check.conversions.find((c) => c.quantity === q)?.to_unit ?? "";
  const ys = Object.keys(check.preview).filter((q) => q !== check.x_quantity);
  if (!check.x_quantity || ys.length === 0) return <p className="text-fg-2">没有可预览的曲线。</p>;
  const y = ys.find((q) => ["nominal_stress", "force", "crack_length", "storage_modulus"].includes(q)) ?? ys[0];
  const p = check.preview[y];
  return (
    <Chart
      ariaLabel={`${label(y)} 对 ${label(check.x_quantity)} 的预览曲线`}
      series={[{ name: label(y), x: p.x, y: p.y }]}
      xTitle={`${label(check.x_quantity)} (${unitOf(check.x_quantity)})`}
      yTitle={`${label(y)} (${unitOf(y)})`}
      height={300}
    />
  );
}

function AiDialog({ open, onOpenChange, rawFileId, tableIndex, onResult }: {
  open: boolean; onOpenChange: (v: boolean) => void; rawFileId: number; tableIndex: number; onResult: (s: Suggestion[]) => void;
}) {
  const [rowsToSend, setRowsToSend] = useState(5);
  const preview = useQuery({
    queryKey: ["ai-preview", rawFileId, tableIndex, rowsToSend],
    queryFn: () => api.post<{ provider: string; payload: unknown; note: string }>("/ai/mapping/preview", { raw_file_id: rawFileId, table_index: tableIndex, n_rows: rowsToSend }),
    enabled: open,
  });
  const run = useMutation({
    mutationFn: () => api.post<{ fallback: boolean; message?: string; error?: string; suggestions: Suggestion[]; provider?: string; model?: string; elapsed_s?: number }>(
      "/ai/mapping", { raw_file_id: rawFileId, table_index: tableIndex, n_rows: rowsToSend }),
    onSuccess: (r) => {
      onResult(r.suggestions);
      onOpenChange(false);
      if (r.fallback) toast.warning(`${r.message}（${r.error}）`);
      else toast.success(`AI（${r.provider} · ${r.model}）完成，用时 ${r.elapsed_s} s；与规则不一致的列已标为待确认`);
    },
    onError: (e: Error) => toast.error(e instanceof ApiError && e.status === 409 ? e.message : `AI 调用失败：${e.message}`),
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>AI 识别列</DialogTitle>
          <DialogDescription>
            将以下内容发送到 {preview.data?.provider ?? "所选"} 模型。CLI Provider 同样会把内容发送到云端（OpenAI / Anthropic）。只发送表头、文件中写明的单位和少量样例行；结果只作为建议，与规则不一致时需要你确认。
          </DialogDescription>
        </DialogHeader>
        <div className="flex items-center gap-2">
          <Label htmlFor="ai-rows">样例行数</Label>
          <Input id="ai-rows" type="number" min={0} max={50} value={rowsToSend} onChange={(e) => setRowsToSend(Math.max(0, Math.min(50, Number(e.target.value))))} className="h-7 w-20" />
        </div>
        <pre className="max-h-72 overflow-auto rounded-md border bg-window p-2 font-mono text-callout">
          {preview.isPending ? "正在生成预览…" : JSON.stringify(preview.data?.payload, null, 2)}
        </pre>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>取消</Button>
          <Button onClick={() => run.mutate()} disabled={run.isPending || preview.isPending}>{run.isPending ? "AI 正在识别（约 10–20 秒）" : "发送并识别"}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ProfileDialog({ open, onOpenChange, rawFileId, tableIndex, mappings }: {
  open: boolean; onOpenChange: (v: boolean) => void; rawFileId: number; tableIndex: number; mappings: { column_index: number; quantity: string; unit: string }[];
}) {
  const [name, setName] = useState("");
  const [instrument, setInstrument] = useState("");
  const save = useMutation({
    mutationFn: () => api.post("/profiles", { name, instrument, raw_file_id: rawFileId, table_index: tableIndex, mappings }),
    onSuccess: () => {
      toast.success(`已保存仪器导入规则“${name}”，相同表头的文件将自动套用`);
      onOpenChange(false);
    },
    onError: (e: Error) => toast.error(e.message),
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>保存仪器导入规则</DialogTitle>
          <DialogDescription>以后导入表头完全相同的文件时，将直接使用当前确认的映射和单位。</DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          <div className="space-y-1"><Label htmlFor="pname">规则名称</Label><Input id="pname" value={name} onChange={(e) => setName(e.target.value)} /></div>
          <div className="space-y-1"><Label htmlFor="pinst">仪器</Label><Input id="pinst" value={instrument} onChange={(e) => setInstrument(e.target.value)} /></div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>取消</Button>
          <Button disabled={!name.trim() || save.isPending} onClick={() => save.mutate()}>保存</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
