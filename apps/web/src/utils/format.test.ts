import { describe, expect, it } from "vitest";
import { formatDateTime } from "./format";

describe("formatDateTime", () => {
  it("renders timestamps in Asia/Shanghai", () => {
    expect(formatDateTime("2026-08-02T16:30:00Z")).toBe("2026-08-03 00:30:00");
  });

  it("keeps date-only values unchanged", () => {
    expect(formatDateTime("2026-08-03")).toBe("2026-08-03");
  });
});
