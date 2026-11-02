/** Shared pieces of the “导出到 Origin” dialogs (analysis page and Plot Studio). */
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { StatusLine } from "@/components/common";
import { Checkbox } from "@/components/ui/checkbox";

export type OriginJob = {
  id: number;
  status: string;
  error: string;
  files: string[];
  opju_file: string | null;
  png_file: string | null;
  verification: { passed?: boolean; export_errors?: Record<string, string> };
};

export const useOriginStatus = () =>
  useQuery({ queryKey: ["origin-status"], queryFn: () => api.get<{ reachable: boolean; error?: string }>("/origin/status") });

export function FormatPicker({ formats, onChange }: { formats: Set<string>; onChange: (f: Set<string>) => void }) {
  return (
    <fieldset className="relative flex gap-4">
      <legend className="sr-only">导出格式</legend>
      {["png", "pdf", "svg"].map((f) => (
        <label key={f} className="flex items-center gap-1.5">
          <Checkbox checked={formats.has(f)} onCheckedChange={(c) => { const s = new Set(formats); if (c === true) s.add(f); else s.delete(f); onChange(s); }} />
          {f.toUpperCase()}
        </label>
      ))}
    </fieldset>
  );
}

/** Polls a submitted job; when done, lists the downloaded OPJU and images. */
export function OriginJobProgress({ jobId }: { jobId: number }) {
  const job = useQuery({
    queryKey: ["origin-job", jobId],
    queryFn: () => api.get<OriginJob>(`/origin/jobs/${jobId}`),
    refetchInterval: (q) => (q.state.data && !["queued", "running"].includes(q.state.data.status) ? false : 2000),
  });
  const st = job.data?.status;
  return (
    <div className="space-y-2" role="status" aria-live="polite">
      <p>{{ queued: "排队中…", running: "Origin 正在生成工程并核验…", done: "完成", failed: "失败", cancelled: "已取消" }[st ?? "queued"] ?? st}</p>
      {job.data?.error && <StatusLine severity="error">{job.data.error}</StatusLine>}
      {st === "done" && (
        <>
          <StatusLine severity={job.data?.verification.passed ? "success" : "warning"}>
            {job.data?.verification.passed ? "OPJU 已重新打开并核对数据与图页" : "核验未通过，请检查文件"}
          </StatusLine>
          <ul className="space-y-1">
            {job.data?.files.map((f) => (
              <li key={f}><a className="text-accent-text underline" href={`/api/origin/jobs/${jobId}/files/${encodeURIComponent(f)}`} download>{f}</a></li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
