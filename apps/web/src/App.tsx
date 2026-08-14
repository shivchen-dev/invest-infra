import { AppShell } from "./components/AppShell";
import { CandidatePoolPage } from "./pages/CandidatePoolPage";
import { DashboardPage } from "./pages/DashboardPage";
import { EtfDetailPage } from "./pages/EtfDetailPage";
import { OperationsPage } from "./pages/OperationsPage";
import { OpportunityRadarPage } from "./pages/OpportunityRadarPage";
import { AutomationCenterPage } from "./pages/AutomationCenterPage";
import { PlaceholderPage } from "./pages/PlaceholderPage";
import { ResearchCasePage } from "./pages/ResearchCasePage";
import { ResearchHistoryPage } from "./pages/ResearchHistoryPage";
import { Router, RouterOutlet } from "./router";

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
    element: <OperationsPage />,
  },
  {
    path: "/opportunity-radar",
    element: <OpportunityRadarPage />,
  },
  {
    path: "/automation",
    element: <AutomationCenterPage />,
  },
  {
    path: "/research/history",
    element: <ResearchHistoryPage />,
  },
  {
    path: "/research/:caseId",
    element: <ResearchCasePage />,
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
    <Router routes={ROUTES} fallback={NOT_FOUND}>
      <AppShell>
        <RouterOutlet />
      </AppShell>
    </Router>
  );
}
