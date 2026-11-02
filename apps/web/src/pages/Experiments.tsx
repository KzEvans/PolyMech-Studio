import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ArrowDown, ArrowUp, Trash2, Upload } from "lucide-react";
import { api, type ExperimentSummary, type Vocabulary } from "@/lib/api";
import { Toolbar } from "@/components/shell/AppShell";
import { shortcut } from "@/lib/platform";
import { EmptyState, StatusLine } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { ConfirmDelete } from "@/components/confirm";

type SortKey = "id" | "material" | "specimen" | "test_type" | "n_runs";

export default function Experiments() {
  const navigate = useNavigate();
  const exps = useQuery({ queryKey: ["experiments"], queryFn: () => api.get<ExperimentSummary[]>("/experiments") });
  const vocab = useQuery({ queryKey: ["vocabulary"], queryFn: () => api.get<Vocabulary>("/vocabulary") });
  const [filter, setFilter] = useState("");
  const [sort, setSort] = useState<{ key: SortKey; asc: boolean }>({ key: "id", asc: false });
  const [toDelete, setToDelete] = useState<ExperimentSummary | null>(null);
  const qc = useQueryClient();
  const del = useMutation({
    mutationFn: (id: number) => api.delete<{ deleted_runs: number }>(`/experiments/${id}`),
    onSuccess: (r, id) => {
      toast.success(`已删除实验 #${id} 及其 ${r.deleted_runs} 个分析版本`);
      setToDelete(null);
      qc.invalidateQueries();
    },
    onError: (e: Error) => { toast.error(e.message); setToDelete(null); },
  });
  const label = (t: string) => vocab.data?.test_types.find((x) => x.id === t)?.label ?? t;

  const rows = useMemo(() => {
    const f = filter.trim().toLowerCase();
    const list = (exps.data ?? []).filter(
      (e) => !f || [e.material.name, e.specimen.label, label(e.test_type), e.batch].some((s) => s.toLowerCase().includes(f)),
    );
    const val = (e: ExperimentSummary): string | number =>
      ({ id: e.id, material: e.material.name, specimen: e.specimen.label, test_type: label(e.test_type), n_runs: e.n_runs })[sort.key];
    return [...list].sort((a, b) => (val(a) < val(b) ? -1 : val(a) > val(b) ? 1 : 0) * (sort.asc ? 1 : -1));
  }, [exps.data, filter, sort, vocab.data]); // eslint-disable-line react-hooks/exhaustive-deps

  const head = (key: SortKey, text: string, cls = "") => (
    <th className={`h-8 px-3 text-left font-medium text-fg-2 ${cls}`} aria-sort={sort.key === key ? (sort.asc ? "ascending" : "descending") : "none"}>
      <button type="button" className="inline-flex items-center gap-1 hover:text-fg-1" onClick={() => setSort({ key, asc: sort.key === key ? !sort.asc : true })}>
        {text}
        {sort.key === key && (sort.asc ? <ArrowUp className="size-3" aria-hidden /> : <ArrowDown className="size-3" aria-hidden />)}
      </button>
    </th>
  );

  return (
    <>
      <Toolbar title="实验">
        <Input aria-label="筛选实验" placeholder="筛选材料、样品、测试类型" value={filter} onChange={(e) => setFilter(e.target.value)} className="h-7 w-56" />
        <Button size="sm" onClick={() => navigate("/experiments/import")} title={`导入数据（${shortcut("O")}）`}>
          <Upload className="size-4" aria-hidden />
          导入数据…
        </Button>
      </Toolbar>
      <main className="min-h-0 flex-1 overflow-auto bg-content">
        {exps.isError && <StatusLine severity="error" className="p-4">{(exps.error as Error).message}</StatusLine>}
        {exps.data && exps.data.length === 0 ? (
          <EmptyState title="还没有实验">
            从仪器导出的 CSV / TXT / Excel 文件开始。<Link className="text-accent-text underline" to="/experiments/import">导入数据…</Link>
          </EmptyState>
        ) : (
          <table className="w-full border-collapse text-body">
            <thead className="sticky top-0 border-b bg-content">
              <tr>
                {head("id", "#", "w-14")}
                {head("material", "材料")}
                {head("specimen", "样品")}
                {head("test_type", "测试类型")}
                <th className="h-8 px-3 text-left font-medium text-fg-2">元数据</th>
                {head("n_runs", "分析版本", "w-24")}
                <th className="w-10"><span className="sr-only">操作</span></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((e) => (
                <tr
                  key={e.id}
                  tabIndex={0}
                  className="cursor-default border-b hover:bg-hover focus-visible:bg-hover"
                  onDoubleClick={() => navigate(`/analysis/${e.id}`)}
                  onKeyDown={(k) => k.key === "Enter" && navigate(`/analysis/${e.id}`)}
                >
                  <td className="tnum px-3 py-1.5 text-fg-2">{e.id}</td>
                  <td className="px-3 py-1.5">{e.material.name}</td>
                  <td className="px-3 py-1.5">{e.specimen.label}</td>
                  <td className="px-3 py-1.5">{label(e.test_type)}</td>
                  <td className="px-3 py-1.5">
                    {e.missing_metadata.length ? (
                      <StatusLine severity="warning">缺少 {e.missing_metadata.map((m) => m.label).join("、")}</StatusLine>
                    ) : (
                      <span className="text-fg-2">完整</span>
                    )}
                  </td>
                  <td className="tnum px-3 py-1.5">
                    {e.latest_run ? (
                      <Badge variant={e.latest_run.status === "ok" ? "secondary" : "outline"}>
                        v{e.latest_run.version} {e.latest_run.status === "ok" ? "" : "临时"}
                      </Badge>
                    ) : (
                      <span className="text-fg-3">未分析</span>
                    )}
                  </td>
                  <td className="px-1 py-1">
                    <Button size="icon" variant="ghost" className="size-7 text-fg-2 hover:text-danger" aria-label={`删除实验 #${e.id}`} title="删除实验…"
                      onClick={(ev) => { ev.stopPropagation(); setToDelete(e); }} onDoubleClick={(ev) => ev.stopPropagation()}>
                      <Trash2 className="size-4" aria-hidden />
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </main>
      {toDelete && (
        <ConfirmDelete title={`删除实验 #${toDelete.id}？`} pending={del.isPending} onConfirm={() => del.mutate(toDelete.id)} onClose={() => setToDelete(null)}>
          <p>{toDelete.material.name} · {toDelete.specimen.label} · {label(toDelete.test_type)}</p>
          <p>将删除：这个实验、它的全部分析版本及其性能数值（材料数据库中的对应条目）、列映射与数据修正、归档的原始文件（与其他导入共用的文件保留）。</p>
          <p>已导出的 Origin 工程和已保存的图不受影响。若其他实验的分析用到了它（如疲劳裂纹扩展用到的稳态结果），删除会被拒绝。</p>
        </ConfirmDelete>
      )}
    </>
  );
}
