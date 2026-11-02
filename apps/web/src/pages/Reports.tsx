import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Download, Printer } from "lucide-react";
import { api } from "@/lib/api";
import { METHOD_LABELS } from "@/lib/units";
import { cn } from "@/lib/utils";
import { Toolbar } from "@/components/shell/AppShell";
import { EmptyState } from "@/components/common";
import { Button } from "@/components/ui/button";

type RunRow = { id: number; method: string; version: number; status: string; specimen: string; created_at: string };

export default function Reports() {
  const runs = useQuery({ queryKey: ["analyses", "all"], queryFn: () => api.get<RunRow[]>("/analyses?limit=200") });
  const [sel, setSel] = useState<number | null>(null);
  return (
    <>
      <Toolbar title="报告">
        {sel && (
          <>
            <Button size="sm" variant="ghost" asChild><a href={`/api/analyses/${sel}/report.json`} download><Download className="size-4" aria-hidden />JSON</a></Button>
            <Button size="sm" variant="ghost" asChild><a href={`/api/analyses/${sel}/report.html`} download><Download className="size-4" aria-hidden />HTML</a></Button>
            <Button size="sm" onClick={() => (document.getElementById("report-frame") as HTMLIFrameElement | null)?.contentWindow?.print()}><Printer className="size-4" aria-hidden />打印 / 存为 PDF…</Button>
          </>
        )}
      </Toolbar>
      <div className="flex min-h-0 flex-1">
        <nav aria-label="分析结果" className="w-64 shrink-0 overflow-auto border-r bg-inspector p-2">
          <ul className="space-y-0.5">
            {runs.data?.map((r) => (
              <li key={r.id}>
                <button type="button" onClick={() => setSel(r.id)} aria-current={r.id === sel} className={cn("w-full rounded-md px-2 py-1 text-left hover:bg-hover", r.id === sel && "bg-hover font-medium")}>
                  {r.specimen} · {METHOD_LABELS[r.method] ?? r.method} v{r.version}{r.status !== "ok" ? "（临时）" : ""}
                </button>
              </li>
            ))}
          </ul>
        </nav>
        <main className="min-w-0 flex-1 bg-content">
          {sel ? <iframe id="report-frame" title="分析报告" src={`/api/analyses/${sel}/report.html`} className="h-full w-full border-0" /> : <EmptyState title="选择一个分析结果生成报告">报告包含材料与样品信息、方法、公式、参数、结果、质量警告、原始数据来源、软件版本与哈希。</EmptyState>}
        </main>
      </div>
    </>
  );
}
