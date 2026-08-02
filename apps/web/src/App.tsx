import { AppShell } from "./components/AppShell";
import { CandidatePoolPage } from "./pages/CandidatePoolPage";
import { DashboardPage } from "./pages/DashboardPage";
import { EtfDetailPage } from "./pages/EtfDetailPage";
import { PlaceholderPage } from "./pages/PlaceholderPage";
import { Router } from "./router";

const ROUTES = [
  { path: "/dashboard", element: <DashboardPage /> },
  {
    path: "/candidate-pool",
    element: <CandidatePoolPage />,
  },
  {
    path: "/etf/:instrumentId",
    element: <EtfDetailPage />,
  },
  {
    path: "/operations",
    element: (
      <PlaceholderPage
        title="Operations"
        description="Pipeline Run 历史与 runbook 提示将随 Web PR-05 落地。"
      />
    ),
  },
];

const NOT_FOUND = (
  <PlaceholderPage
    title="页面不存在"
    description="请通过左侧导航选择目标页面。"
  />
);

export function App() {
  return (
    <AppShell>
      <Router routes={ROUTES} fallback={NOT_FOUND} />
    </AppShell>
  );
}