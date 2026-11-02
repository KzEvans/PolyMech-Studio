import { Fragment, type ReactNode } from "react";
import { AlertTriangle, CheckCircle2, Info, OctagonX } from "lucide-react";
import type { Flag, QualityIssue } from "@/lib/api";
import { cn } from "@/lib/utils";
import { rich } from "@/lib/rich";

const ICON = { info: Info, warning: AlertTriangle, error: OctagonX, success: CheckCircle2 } as const;
const COLOR = { info: "text-info", warning: "text-warning", error: "text-danger", success: "text-success" } as const;

/** Status always pairs colour with an icon and text (HIG: never colour alone). */
export function StatusLine({ severity, children, className }: { severity: keyof typeof ICON; children: ReactNode; className?: string }) {
  const Icon = ICON[severity];
  return (
    // relative: anchors the sr-only label; otherwise it is positioned against the page and makes
    // the whole window scroll (blank area under the app)
    <div className={cn("relative flex items-start gap-2 text-body", className)}>
      <Icon aria-hidden className={cn("mt-px size-4 shrink-0", COLOR[severity])} />
      <span className="sr-only">{{ info: "提示", warning: "警告", error: "错误", success: "成功" }[severity]}：</span>
      <span>{children}</span>
    </div>
  );
}

export function FlagList({ flags, empty = "没有质量警告" }: { flags: (Flag | QualityIssue)[]; empty?: string }) {
  if (!flags.length) return <StatusLine severity="success">{empty}</StatusLine>;
  return (
    <ul className="space-y-1.5">
      {flags.map((f, i) => (
        <li key={`${f.code}-${i}`}>
          <StatusLine severity={f.severity}>{f.message}</StatusLine>
        </li>
      ))}
    </ul>
  );
}

export function Panel({ title, children, actions, className }: { title?: string; children: ReactNode; actions?: ReactNode; className?: string }) {
  return (
    <section className={cn("rounded-lg border bg-content", className)}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-2 border-b px-3 py-2">
          {title && <h2 className="text-headline font-semibold">{title}</h2>}
          {actions}
        </header>
      )}
      <div className="p-3">{children}</div>
    </section>
  );
}

// Break a value only before these separators, never inside “7.7e-11 MJ/m³” or “λ ∈ [1, 1.05]”
const BREAK_BEFORE = /(?=（| ± | · |，| – )/;

function unbroken(v: ReactNode): ReactNode {
  if (typeof v !== "string") return v;
  return v.split(BREAK_BEFORE).map((part, i) => (
    <Fragment key={i}>
      {i > 0 && <wbr />}
      {/* long free text (e.g. a user note) may still wrap normally */}
      <span className={part.length <= 32 ? "whitespace-nowrap" : undefined}>{rich(part)}</span>
    </Fragment>
  ));
}

/** Label–value list. Label and value share a row when they fit; otherwise the value moves to
 * its own line (right-aligned) instead of wrapping in the middle of a number. */
export function KeyValue({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="space-y-1.5 text-body">
      {items.map(([k, v]) => (
        <div key={k} className="flex flex-wrap items-baseline justify-between gap-x-4">
          <dt className="text-fg-2">{rich(k)}</dt>
          <dd className="tnum ml-auto text-right">{unbroken(v)}</dd>
        </div>
      ))}
    </dl>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="flex h-full min-h-48 flex-col items-center justify-center gap-2 p-8 text-center">
      <p className="text-title3 font-semibold">{title}</p>
      {children && <div className="max-w-md text-fg-2">{children}</div>}
    </div>
  );
}
