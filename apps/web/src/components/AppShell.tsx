import type { ReactNode } from "react";
import { NavLink } from "../router";

interface NavItem {
  to: string;
  label: string;
  description: string;
}

const NAV_ITEMS: NavItem[] = [
  {
    to: "/dashboard",
    label: "Dashboard",
    description: "数据状态与候选概览",
  },
  {
    to: "/candidate-pool",
    label: "候选池",
    description: "入选 / 排除 / 全部",
  },
  {
    to: "/operations",
    label: "Operations",
    description: "Pipeline Run 历史",
  },
  {
    to: "/opportunity-radar",
    label: "机会雷达",
    description: "外部候选与准入状态",
  },
  {
    to: "/automation",
    label: "Automation Center",
    description: "外部工作流观测",
  },
];

interface AppShellProps {
  children: ReactNode;
}

export function AppShell({ children }: AppShellProps) {
  return (
    <div className="appShell">
      <aside className="appSidebar" aria-label="主导航">
        <div className="appBrand">
          <p className="brandEyebrow">INVEST INFRA V2</p>
          <h1 className="brandTitle">投研工作台</h1>
          <p className="brandSubtitle">个人 ETF 流水线观测台</p>
        </div>
        <nav className="appNav" aria-label="主导航链接">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `appNavItem${isActive ? " appNavItemActive" : ""}`
              }
            >
              <span className="appNavLabel">{item.label}</span>
              <span className="appNavDescription">{item.description}</span>
            </NavLink>
          ))}
        </nav>
        <p className="appSidebarFooter">
          数据按需刷新；浏览器内不触发任何写操作。
        </p>
      </aside>
      <main className="appContent" id="main-content" tabIndex={-1}>
        {children}
      </main>
    </div>
  );
}
