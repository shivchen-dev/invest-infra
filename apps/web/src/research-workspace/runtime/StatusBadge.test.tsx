import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { StatusBadge } from "./StatusBadge";

afterEach(() => {
  cleanup();
});

function getBadge() {
  return screen.getByText(/.*/, { selector: ".cockpitBadgeLabel" }).parentElement;
}

describe("StatusBadge", () => {
  it("renders the provided label", () => {
    render(<StatusBadge tone="info">待数据接入</StatusBadge>);
    expect(screen.getByText("待数据接入")).toBeInTheDocument();
  });

  it("uses the tone-specific class", () => {
    const { rerender } = render(<StatusBadge tone="success">Ready</StatusBadge>);
    expect(getBadge()).toHaveClass("cockpitBadge-Success");

    rerender(<StatusBadge tone="warning">Stale</StatusBadge>);
    expect(getBadge()).toHaveClass("cockpitBadge-Warning");

    rerender(<StatusBadge tone="danger">Failed</StatusBadge>);
    expect(getBadge()).toHaveClass("cockpitBadge-Danger");

    rerender(<StatusBadge tone="neutral">Idle</StatusBadge>);
    expect(getBadge()).toHaveClass("cockpitBadge-Neutral");
  });

  it("defaults to a neutral tone when none is provided", () => {
    render(<StatusBadge>Default</StatusBadge>);
    expect(getBadge()).toHaveClass("cockpitBadge-Neutral");
  });

  it("exposes a non-empty aria-label for screen readers", () => {
    render(<StatusBadge tone="info">Loading</StatusBadge>);
    expect(getBadge()).toHaveAttribute("aria-label", "Loading");
  });

  it("supports an explicit aria-label override", () => {
    render(
      <StatusBadge tone="info" ariaLabel="Loading research data">
        加载中
      </StatusBadge>,
    );
    expect(getBadge()).toHaveAttribute("aria-label", "Loading research data");
  });
});
