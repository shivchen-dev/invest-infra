import { describe, expect, it } from "vitest";
import { computeExpectedTradeDate } from "./OperationsPage";

describe("computeExpectedTradeDate", () => {
  it("uses the Asia/Shanghai calendar date before rolling back weekends", () => {
    expect(computeExpectedTradeDate("2026-08-01T16:30:00Z")).toBe("2026-07-31");
    expect(computeExpectedTradeDate("2026-08-02T15:59:00Z")).toBe("2026-07-31");
  });

  it("does not shift date-only as_of values", () => {
    expect(computeExpectedTradeDate("2026-08-03")).toBe("2026-08-03");
  });
});
