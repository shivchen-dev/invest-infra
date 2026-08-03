import "@testing-library/jest-dom/vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { NavLink, Router, useParams } from "./router";

function setPathname(pathname: string) {
  window.history.replaceState(null, "", pathname);
}

function InstrumentRoute() {
  const { instrumentId } = useParams<{ instrumentId: string }>();
  return <h1>ETF {instrumentId}</h1>;
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("Router", () => {
  it("redirects the root path to the dashboard", () => {
    setPathname("/");
    const replaceState = vi.spyOn(window.history, "replaceState");

    render(
      <Router
        routes={[{ path: "/dashboard", element: <h1>Dashboard</h1> }]}
      />,
    );

    expect(window.location.pathname).toBe("/dashboard");
    expect(replaceState).toHaveBeenCalledWith(null, "", "/dashboard");
    expect(screen.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  });

  it("renders a static route", () => {
    setPathname("/operations");

    render(
      <Router
        routes={[
          { path: "/dashboard", element: <h1>Dashboard</h1> },
          { path: "/operations", element: <h1>Operations</h1> },
        ]}
      />,
    );

    expect(screen.getByRole("heading", { name: "Operations" })).toBeVisible();
  });

  it("provides dynamic route parameters", () => {
    setPathname("/etf/510300");

    render(
      <Router
        routes={[{ path: "/etf/:instrumentId", element: <InstrumentRoute /> }]}
      />,
    );

    expect(screen.getByRole("heading", { name: "ETF 510300" })).toBeVisible();
  });

  it("decodes dynamic route parameters", () => {
    setPathname("/etf/%E4%B8%8A%E8%AF%81%20ETF");

    render(
      <Router
        routes={[{ path: "/etf/:instrumentId", element: <InstrumentRoute /> }]}
      />,
    );

    expect(screen.getByRole("heading", { name: "ETF 上证 ETF" })).toBeVisible();
  });

  it("renders the fallback for an unknown route", () => {
    setPathname("/unknown");

    render(
      <Router
        routes={[{ path: "/dashboard", element: <h1>Dashboard</h1> }]}
        fallback={<h1>Page not found</h1>}
      />,
    );

    expect(
      screen.getByRole("heading", { name: "Page not found" }),
    ).toBeVisible();
  });

  it("responds to back and forward navigation", async () => {
    const user = userEvent.setup();
    setPathname("/dashboard");

    render(
      <Router
        routes={[
          {
            path: "/dashboard",
            element: <NavLink to="/operations">Open operations</NavLink>,
          },
          {
            path: "/operations",
            element: <NavLink to="/dashboard">Open dashboard</NavLink>,
          },
        ]}
      />,
    );

    await user.click(screen.getByRole("link", { name: "Open operations" }));
    expect(window.location.pathname).toBe("/operations");
    expect(
      screen.getByRole("link", { name: "Open dashboard" }),
    ).toBeVisible();

    window.history.back();
    await waitFor(() => {
      expect(window.location.pathname).toBe("/dashboard");
      expect(
        screen.getByRole("link", { name: "Open operations" }),
      ).toBeVisible();
    });

    window.history.forward();
    await waitFor(() => {
      expect(window.location.pathname).toBe("/operations");
      expect(
        screen.getByRole("link", { name: "Open dashboard" }),
      ).toBeVisible();
    });
  });

  it("marks the matching NavLink as active", () => {
    setPathname("/dashboard");

    render(
      <Router
        routes={[
          {
            path: "/dashboard",
            element: (
              <nav>
                <NavLink
                  to="/dashboard"
                  className={({ isActive }) =>
                    isActive ? "active" : "inactive"
                  }
                >
                  Dashboard
                </NavLink>
                <NavLink
                  to="/operations"
                  className={({ isActive }) =>
                    isActive ? "active" : "inactive"
                  }
                >
                  Operations
                </NavLink>
              </nav>
            ),
          },
        ]}
      />,
    );

    expect(screen.getByRole("link", { name: "Dashboard" })).toHaveClass(
      "active",
    );
    expect(screen.getByRole("link", { name: "Operations" })).toHaveClass(
      "inactive",
    );
  });

  it.each([
    ["Control", { ctrlKey: true }],
    ["Meta", { metaKey: true }],
  ])("does not intercept a %s-click", (_modifier, eventInit) => {
    setPathname("/dashboard");
    const pushState = vi.spyOn(window.history, "pushState");

    render(
      <Router
        routes={[
          {
            path: "/dashboard",
            element: (
              <NavLink
                to="/operations"
                onClick={(event) => event.preventDefault()}
              >
                Operations
              </NavLink>
            ),
          },
        ]}
      />,
    );

    fireEvent.click(screen.getByRole("link", { name: "Operations" }), eventInit);

    expect(pushState).not.toHaveBeenCalled();
    expect(window.location.pathname).toBe("/dashboard");
  });

  it("does not push the current URL again", async () => {
    const user = userEvent.setup();
    setPathname("/dashboard");
    const pushState = vi.spyOn(window.history, "pushState");

    render(
      <Router
        routes={[
          {
            path: "/dashboard",
            element: <NavLink to="/dashboard">Dashboard</NavLink>,
          },
        ]}
      />,
    );

    await user.click(screen.getByRole("link", { name: "Dashboard" }));

    expect(pushState).not.toHaveBeenCalled();
    expect(window.location.pathname).toBe("/dashboard");
  });
});
