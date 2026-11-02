import { useEffect, useState, type ReactNode } from "react";
import { NavLink, Outlet, useNavigate } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { AnimatePresence, motion } from "motion/react";
import {
  BarChart3,
  BookOpen,
  Database,
  FileText,
  FlaskConical,
  LayoutDashboard,
  LineChart,
  PanelLeft,
  Settings as SettingsIcon,
} from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useApplyTheme, type ThemeSetting } from "@/lib/theme";
import { cn } from "@/lib/utils";
import { hasPrimaryKey, shortcut } from "@/lib/platform";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

type Settings = { theme: ThemeSetting; reduce_transparency: boolean; ai_enabled: boolean };
type OriginStatus = { reachable: boolean; error?: string };

const NAV = [
  { to: "/", label: "概览", icon: LayoutDashboard, end: true },
  { to: "/experiments", label: "实验", icon: FlaskConical },
  { to: "/analysis", label: "分析", icon: BarChart3 },
  { to: "/plots", label: "绘图工作室", icon: LineChart },
  { to: "/materials", label: "材料数据库", icon: Database },
  { to: "/reports", label: "报告", icon: FileText },
];

export function useSettings() {
  return useQuery({ queryKey: ["settings"], queryFn: () => api.get<Settings & Record<string, unknown>>("/settings") });
}

export function AppShell() {
  const settings = useSettings();
  useApplyTheme(settings.data?.theme ?? "system", settings.data?.reduce_transparency ?? false);
  const [sidebar, setSidebar] = useState(() => window.innerWidth >= 860);
  const navigate = useNavigate();
  const origin = useQuery({ queryKey: ["origin-status"], queryFn: () => api.get<OriginStatus>("/origin/status"), refetchInterval: 60_000 });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!hasPrimaryKey(e)) return;
      if (e.altKey && e.code === "KeyS") {
        e.preventDefault();
        setSidebar((v) => !v);
      } else if (e.key === "," && !e.altKey) {
        e.preventDefault();
        navigate("/settings");
      } else if (e.key.toLowerCase() === "o" && !e.altKey && !e.shiftKey) {
        e.preventDefault();
        navigate("/experiments/import");
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [navigate]);

  // Desktop app: native menu items arrive as DOM events (their shortcuts never reach keydown)
  useEffect(() => {
    const onMenu = (e: Event) => {
      const id = (e as CustomEvent<string>).detail;
      if (id.startsWith("nav:")) navigate(id.slice(4));
      else if (id === "settings") navigate("/settings");
      else if (id === "import") navigate("/experiments/import");
      else if (id === "toggle_sidebar") setSidebar((v) => !v);
    };
    const onDownloaded = (e: Event) => {
      const d = (e as CustomEvent<{ ok: boolean; path?: string }>).detail;
      if (d.ok) toast.success(`已保存到“下载”：${d.path?.split(/[\\/]/).pop() ?? ""}`);
      else toast.error("文件保存失败");
    };
    window.addEventListener("polymech:menu", onMenu);
    window.addEventListener("polymech:downloaded", onDownloaded);
    return () => {
      window.removeEventListener("polymech:menu", onMenu);
      window.removeEventListener("polymech:downloaded", onDownloaded);
    };
  }, [navigate]);

  return (
    <div className="flex h-full overflow-hidden">
      <AnimatePresence initial={false}>
      {sidebar && (
      // transform + opacity only (no width animation → no animated relayout); the content area
      // reflows once when the panel has left. Stiff, critically damped spring: no overshoot.
      <motion.aside
        key="sidebar"
        initial={{ x: -220, opacity: 0 }}
        animate={{ x: 0, opacity: 1, transition: { type: "spring", stiffness: 420, damping: 42 } }}
        exit={{ x: -220, opacity: 0, transition: { duration: 0.14, ease: [0.3, 0, 1, 1] } }}
        className="w-[220px] shrink-0 overflow-hidden border-r bg-sidebar backdrop-blur-xl"
        aria-label="主导航"
      >
        <div className="flex h-full w-[220px] flex-col">
          <div className="flex h-11 items-center px-4 text-headline font-semibold">PolyMech Studio</div>
          <nav className="flex-1 space-y-0.5 px-2">
            {NAV.map(({ to, label, icon: Icon, end }) => (
              <NavLink
                key={to}
                to={to}
                end={end}
                className={({ isActive }) =>
                  cn(
                    "flex h-7 items-center gap-2 rounded-md px-2 text-body transition-colors duration-[var(--dur-micro)]",
                    isActive ? "bg-[color-mix(in_srgb,var(--accent-text)_16%,transparent)] font-medium" : "hover:bg-hover",
                  )
                }
              >
                {({ isActive }) => (
                  <>
                    <Icon aria-hidden className={cn("size-4", isActive ? "text-accent-text" : "text-fg-2")} />
                    {label}
                  </>
                )}
              </NavLink>
            ))}
          </nav>
          <div className="space-y-0.5 border-t px-2 py-2">
            <NavLink
              to="/help"
              className={({ isActive }) => cn("flex h-7 items-center gap-2 rounded-md px-2", isActive ? "bg-hover font-medium" : "hover:bg-hover")}
            >
              <BookOpen aria-hidden className="size-4 text-fg-2" />
              使用说明
            </NavLink>
            <NavLink
              to="/settings"
              className={({ isActive }) => cn("flex h-7 items-center gap-2 rounded-md px-2", isActive ? "bg-hover font-medium" : "hover:bg-hover")}
            >
              <SettingsIcon aria-hidden className="size-4 text-fg-2" />
              设置
            </NavLink>
            <p className="flex items-center gap-2 px-2 pt-1 text-subhead text-fg-2" role="status">
              <span aria-hidden className={cn("size-2 rounded-full", origin.data?.reachable ? "bg-success" : "bg-fg-3")} />
              Origin：{origin.isPending ? "检测中…" : origin.data?.reachable ? "已连接" : "未连接"}
            </p>
          </div>
        </div>
      </motion.aside>
      )}
      </AnimatePresence>
      <div className="flex min-w-0 flex-1 flex-col">
        <Outlet context={{ sidebar, toggleSidebar: () => setSidebar((v) => !v) }} />
      </div>
    </div>
  );
}

/** Page toolbar: title on the left (<15 chars, HIG), grouped actions on the right, primary last. */
export function Toolbar({ title, children, subtitle }: { title: string; subtitle?: string; children?: ReactNode }) {
  return (
    <header className="flex h-11 shrink-0 items-center gap-2 border-b bg-window px-3">
      <SidebarToggle />
      {/* the title keeps a readable minimum width; in narrow windows the actions scroll instead
          of squeezing the title into one character per line */}
      <div className="min-w-24 flex-1">
        <h1 className="truncate text-headline font-semibold">{title}</h1>
        {subtitle && <p className="truncate text-subhead text-fg-2">{subtitle}</p>}
      </div>
      <div className="flex min-w-0 shrink items-center gap-1.5 overflow-x-auto [scrollbar-width:none]">{children}</div>
    </header>
  );
}

function SidebarToggle() {
  const toggle = () => window.dispatchEvent(new CustomEvent("polymech:menu", { detail: "toggle_sidebar" }));
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          onClick={toggle}
          aria-label={`显示或隐藏侧边栏（${shortcut("S", { alt: true })}）`}
          className="grid size-7 place-items-center rounded-md text-fg-2 hover:bg-hover active:bg-[var(--separator)]"
        >
          <PanelLeft className="size-4" aria-hidden />
        </button>
      </TooltipTrigger>
      <TooltipContent>显示/隐藏侧边栏 {shortcut("S", { alt: true })}</TooltipContent>
    </Tooltip>
  );
}
