import { lazy, Suspense, type ReactNode } from "react";
import { createBrowserRouter } from "react-router";
import { AppShell } from "@/components/shell/AppShell";
import { EmptyState } from "@/components/common";

// Chart-heavy pages load lazily so the shell paints immediately.
const Dashboard = lazy(() => import("@/pages/Dashboard"));
const Experiments = lazy(() => import("@/pages/Experiments"));
const ImportPage = lazy(() => import("@/pages/Import"));
const Analysis = lazy(() => import("@/pages/Analysis"));
const PlotStudio = lazy(() => import("@/pages/PlotStudio"));
const Materials = lazy(() => import("@/pages/Materials"));
const Reports = lazy(() => import("@/pages/Reports"));
const Settings = lazy(() => import("@/pages/Settings"));
const Help = lazy(() => import("@/pages/Help"));

const page = (el: ReactNode) => <Suspense fallback={<EmptyState title="正在加载…" />}>{el}</Suspense>;

export const router = createBrowserRouter([
  {
    path: "/",
    element: <AppShell />,
    errorElement: <EmptyState title="页面出错">请刷新页面；如果问题持续，请查看后端日志。</EmptyState>,
    children: [
      { index: true, element: page(<Dashboard />) },
      { path: "experiments", element: page(<Experiments />) },
      { path: "experiments/import", element: page(<ImportPage />) },
      { path: "analysis", element: page(<Analysis />) },
      { path: "analysis/:experimentId", element: page(<Analysis />) },
      { path: "plots", element: page(<PlotStudio />) },
      { path: "materials", element: page(<Materials />) },
      { path: "reports", element: page(<Reports />) },
      { path: "settings", element: page(<Settings />) },
      { path: "help", element: page(<Help />) },
      { path: "*", element: <EmptyState title="没有这个页面" /> },
    ],
  },
]);
