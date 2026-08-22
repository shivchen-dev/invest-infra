import "@testing-library/jest-dom/vitest";
import {
  cleanup,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import type {
  EvidencePackResponse,
  ResearchCaseResponse,
  ResearchCaseWorkspaceResponse,
  ResearchResultResponse,
  ResearchRunResponse,
} from "../api/types";
import {
  errorQuery,
  pendingQuery,
  successQuery,
} from "../features/research/dashboard/test-helpers";
import { Router } from "../router";
import { ResearchCasePage } from "./ResearchCasePage";

vi.mock("../api/researchCaseWorkspace", () => ({
  fetchResearchCaseWorkspace: vi.fn(),
  useResearchCaseWorkspace: vi.fn(),
  researchCaseWorkspaceQueryKey: vi.fn(),
  RESEARCH_CASE_WORKSPACE_REFETCH_INTERVAL: 60_000,
}));

import {
  useResearchCaseWorkspace,
} from "../api/researchCaseWorkspace";

const mockUseWorkspace = vi.mocked(useResearchCaseWorkspace);

function setPathname(pathname: string) {
  window.history.replaceState(null, "", pathname);
}

function renderCasePage(path: string) {
  setPathname(path);
  return render(
    <Router
      routes={[{ path: "/research/:caseId", element: <ResearchCasePage /> }]}
    />,
  );
}

function makeCase(
  overrides: Partial<ResearchCaseResponse> = {},
): ResearchCaseResponse {
  return {
    case_id: "11111111-1111-1111-1111-111111111111",
    instrument_id: "22222222-2222-2222-2222-222222222222",
    as_of_date: "2026-08-08",
    question: "趋势通道判断",
    horizon: "30d",
    status: "open",
    created_at: "2026-08-09T00:00:00Z",
    candidate_pool_run_id: null,
    closed_at: null,
    ...overrides,
  };
}

function makeRun(
  overrides: Partial<ResearchRunResponse> = {},
): ResearchRunResponse {
  return {
    run_id: "33333333-3333-3333-3333-333333333333",
    case_id: "11111111-1111-1111-1111-111111111111",
    evidence_pack_id: "44444444-4444-4444-4444-444444444444",
    playbook_key: "playbook.default",
    runner_key: "runner.default",
    attempt: 1,
    started_at: "2026-08-09T00:00:00Z",
    finished_at: "2026-08-09T00:30:00Z",
    status: "succeeded",
    error_summary: null,
    ...overrides,
  };
}

function makeResult(
  overrides: Partial<ResearchResultResponse> = {},
): ResearchResultResponse {
  return {
    result_id: "55555555-5555-5555-5555-555555555555",
    run_id: "33333333-3333-3333-3333-333333333333",
    evidence_pack_id: "44444444-4444-4444-4444-444444444444",
    model_key: "model.basic",
    model_version: "1.0.0",
    adapter_version: "1",
    playbook_version: "1.0.0",
    conclusion: "趋势向上",
    report_markdown: "# 趋势向上",
    evidence_ids: ["evidence-1"],
    risks: [],
    created_at: "2026-08-09T00:35:00Z",
    ...overrides,
  };
}

function makeEvidencePack(
  overrides: Partial<EvidencePackResponse> = {},
): EvidencePackResponse {
  return {
    pack_id: "44444444-4444-4444-4444-444444444444",
    pack_hash: "deadbeef",
    schema_version: "1.0.0",
    factor_set_key: "factor.basic",
    factor_set_version: "1",
    generated_at: "2026-08-09T00:10:00Z",
    case: {
      case_id: "11111111-1111-1111-1111-111111111111",
      instrument_id: "22222222-2222-2222-2222-222222222222",
      as_of_date: "2026-08-08",
      question: "趋势通道判断",
      horizon: "30d",
    },
    instrument: {
      instrument_id: "22222222-2222-2222-2222-222222222222",
      symbol: "ETF.SYMBOL",
      exchange: "SH",
      currency: "CNY",
      name: "示例 ETF",
    },
    market_snapshot: {
      currency: "CNY",
      latest_close: "1.234",
      latest_trade_date: "2026-08-08",
      observed_trading_days: 22,
      valid_price_days: 22,
      suspended_days: 0,
    },
    data_quality: {
      quality_status: "ok",
      freshness_status: "current",
      conflict_detected: false,
      target_trading_days: 22,
      observed_trading_days: 22,
      valid_price_days: 22,
      suspended_days: 0,
      invalid_days: 0,
    },
    factors: [],
    source_refs: [],
    missing_fields: [],
    warnings: [],
    ...overrides,
  };
}

function makeWorkspace(
  overrides: Partial<ResearchCaseWorkspaceResponse> = {},
): ResearchCaseWorkspaceResponse {
  return {
    case: makeCase(),
    evidence_packs: [],
    runs: [],
    results: [],
    external_discovery: [],
    ...overrides,
  };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("ResearchCasePage", () => {
  describe("routing and shell", () => {
    beforeEach(() => {
      mockUseWorkspace.mockReturnValue(pendingQuery());
    });

    it("renders the case header, decoded case id, and breadcrumb", () => {
      renderCasePage("/research/case-2026-08-03");

      expect(
        screen.getByRole("heading", { name: /Research Case · case-2026-08-03/ }),
      ).toBeInTheDocument();

      const breadcrumb = screen.getByLabelText("Research Case 路径");
      expect(within(breadcrumb).getByText("Dashboard")).toBeInTheDocument();
      expect(
        within(breadcrumb).getByText("Research History"),
      ).toBeInTheDocument();
      expect(
        within(breadcrumb).getByText("Case · case-2026-08-03"),
      ).toBeInTheDocument();
    });

    it("decodes a percent-encoded caseId", () => {
      renderCasePage("/research/case%2D2026-q3");

      expect(
        screen.getByRole("heading", { name: /Research Case · case-2026-q3/ }),
      ).toBeInTheDocument();
    });

    it("preserves the seven-section layout and the read-only hint", () => {
      renderCasePage("/research/case-x");

      const subnav = screen.getByLabelText("Case 工作区导航");
      const labels = within(subnav)
        .getAllByRole("link")
        .map((link) => link.textContent);
      expect(labels).toEqual([
        "Case 概览",
        "Evidence Pack",
        "External Discovery",
        "Factor Snapshot",
        "Research Result",
        "Risk Monitor",
        "Report Viewer",
      ]);

      expect(
        screen.getAllByText("只读模式 · 浏览器不写入 Research 数据").length,
      ).toBeGreaterThanOrEqual(1);
    });
  });

  describe("loading state", () => {
    beforeEach(() => {
      mockUseWorkspace.mockReturnValue(pendingQuery());
    });

    it("shows loading markers while the workspace query is pending", () => {
      renderCasePage("/research/case-loading");

      const widgetGrid = screen.getByLabelText("Research Case widgets");
      const loadingWidgets = within(widgetGrid).getAllByText(
        "正在加载 Case Workspace…",
      );
      // The three contract-backed widgets surface the loading marker; the
      // honest-unavailable widgets fall back to the workspace state label.
      expect(loadingWidgets.length).toBeGreaterThanOrEqual(1);

      const caseMeta = screen.getByRole("region", { name: "Case 元数据" });
      const statusBadges = within(caseMeta).getAllByText("Loading");
      expect(statusBadges.length).toBeGreaterThanOrEqual(1);
    });
  });

  describe("failed state", () => {
    it("surfaces the error message and marks every widget failed", () => {
      mockUseWorkspace.mockReturnValue(
        errorQuery(new ApiError("Research query failed", 500)),
      );

      renderCasePage("/research/case-failed");

      const widgetGrid = screen.getByLabelText("Research Case widgets");
      const alerts = within(widgetGrid).getAllByRole("alert");
      expect(alerts.length).toBeGreaterThan(0);
      expect(
        within(widgetGrid).getAllByText("Research query failed").length,
      ).toBeGreaterThan(0);

      const caseMeta = screen.getByRole("region", { name: "Case 元数据" });
      const statusBadges = within(caseMeta).getAllByText("Failed");
      expect(statusBadges.length).toBeGreaterThanOrEqual(1);
    });
  });

  describe("empty populated state", () => {
    it("renders the workspace shell with explicit empty markers", async () => {
      mockUseWorkspace.mockReturnValue(successQuery(makeWorkspace()));

      renderCasePage("/research/case-empty");

      const widgetGrid = screen.getByLabelText("Research Case widgets");

      // Case overview reflects the case row.
      const overview = widgetGrid.querySelector(
        '[data-widget-id="case-overview"]',
      ) as HTMLElement;
      expect(overview).toHaveTextContent("趋势通道判断");
      expect(overview).toHaveTextContent("30d");

      // Evidence Pack renders the explicit empty placeholder.
      const evidence = widgetGrid.querySelector(
        '[data-widget-id="evidence-pack"]',
      ) as HTMLElement;
      expect(evidence).toHaveTextContent("暂无 Evidence Pack");

      // External Discovery renders the explicit empty placeholder.
      const discovery = widgetGrid.querySelector(
        '[data-widget-id="external-discovery"]',
      ) as HTMLElement;
      expect(discovery).toHaveTextContent("暂无 External Discovery");

      // Research Result renders the explicit empty placeholder.
      const result = widgetGrid.querySelector(
        '[data-widget-id="research-result"]',
      ) as HTMLElement;
      expect(result).toHaveTextContent("尚无 Run 与 Result");

      const factor = widgetGrid.querySelector(
        '[data-widget-id="factor-snapshot"]',
      ) as HTMLElement;
      const risk = widgetGrid.querySelector(
        '[data-widget-id="risk-monitor"]',
      ) as HTMLElement;
      const report = widgetGrid.querySelector(
        '[data-widget-id="report-viewer"]',
      ) as HTMLElement;
      expect(factor).toHaveTextContent("暂未接入");
      expect(risk).toHaveTextContent("暂未接入");
      expect(report).toHaveTextContent("暂无报告");
      expect(report).toHaveTextContent("report_markdown");
      expect(report.querySelector(".cockpitReportMarkdown")).toBeNull();
      expect(factor.textContent ?? "").not.toMatch(/buy|sell|stance/i);
      expect(risk.textContent ?? "").not.toMatch(/buy|sell|stance/i);
      expect(report.textContent ?? "").not.toMatch(/buy|sell|stance/i);

      const caseMeta = screen.getByRole("region", { name: "Case 元数据" });
      const statusBadges = within(caseMeta).getAllByText("Ready");
      expect(statusBadges.length).toBeGreaterThanOrEqual(1);
      expect(
        within(caseMeta).getByText("Stage 4D Task 3.3 Workspace Read API"),
      ).toBeInTheDocument();
    });
  });

  describe("populated state", () => {
    it("renders real Case metadata, Evidence Pack list, and Run/Result summary", async () => {
      const pack = makeEvidencePack({
        pack_hash: "feedface",
        data_quality: {
          quality_status: "partial",
          freshness_status: "current",
          conflict_detected: false,
          target_trading_days: 22,
          observed_trading_days: 22,
          valid_price_days: 20,
          suspended_days: 0,
          invalid_days: 0,
        },
      });
      mockUseWorkspace.mockReturnValue(
        successQuery(
          makeWorkspace({
            evidence_packs: [pack],
            runs: [
              makeRun({
                run_id: "33333333-3333-3333-3333-333333333333",
                status: "succeeded",
              }),
            ],
            results: [
              makeResult({
                run_id: "33333333-3333-3333-3333-333333333333",
                conclusion: "趋势向上",
              }),
            ],
          }),
        ),
      );

      renderCasePage("/research/case-populated");

      const widgetGrid = await screen.findByLabelText("Research Case widgets");

      // Case metadata is rendered.
      const overview = widgetGrid.querySelector(
        '[data-widget-id="case-overview"]',
      ) as HTMLElement;
      expect(overview).toHaveTextContent("11111111-1111-1111-1111-111111111111");
      expect(overview).toHaveTextContent("趋势通道判断");
      expect(overview).toHaveTextContent("open");

      // Evidence Pack list shows the bound pack.
      const evidence = widgetGrid.querySelector(
        '[data-widget-id="evidence-pack"]',
      ) as HTMLElement;
      expect(evidence).toHaveTextContent("feedface");
      expect(evidence).toHaveTextContent("partial");
      expect(evidence).toHaveTextContent("current");

      // Run + Result pair is rendered positionally.
      const result = widgetGrid.querySelector(
        '[data-widget-id="research-result"]',
      ) as HTMLElement;
      expect(result).toHaveTextContent("33333333-3333-3333-3333-333333333333");
      expect(result).toHaveTextContent("已完成");
      expect(result).toHaveTextContent("趋势向上");

      const report = widgetGrid.querySelector(
        '[data-widget-id="report-viewer"]',
      ) as HTMLElement;
      const reportViewer = report.querySelector(
        ".cockpitReportViewer",
      ) as HTMLElement;
      expect(reportViewer).toHaveAttribute("data-report-read-only", "true");
      const markdownView = report.querySelector(
        ".cockpitReportMarkdown",
      ) as HTMLElement;
      expect(markdownView).toBeInTheDocument();
      expect(markdownView.querySelector("h3")).toHaveTextContent("趋势向上");
      expect(markdownView).toHaveTextContent("趋势向上");
      expect(report.querySelector("textarea")).toBeNull();
      expect(report.querySelector("[contenteditable]")).toBeNull();

      // No fabricated stance / confidence language.
      expect(widgetGrid.textContent ?? "").not.toMatch(/buy|sell/i);

      // Subnav meta reflects the Stage 4D Task 3.3 milestone copy.
      const meta = screen.getByText(/Stage 4D Task 3.3 · 统一时间线已接入/);
      expect(meta).toBeInTheDocument();
    });

    it("renders the latest non-null report as a read-only view", async () => {
      const olderResult = makeResult({
        result_id: "55555555-5555-5555-5555-555555555551",
        run_id: "run-old",
        report_markdown: "# Older report",
        created_at: "2026-08-09T00:35:00Z",
      });
      const latestResult = makeResult({
        result_id: "55555555-5555-5555-5555-555555555552",
        run_id: "run-latest",
        report_markdown: "# Latest report\n\nEvidence-backed conclusion.",
        created_at: "2026-08-09T01:35:00Z",
      });
      mockUseWorkspace.mockReturnValue(
        successQuery(
          makeWorkspace({
            runs: [
              makeRun({ run_id: "run-old" }),
              makeRun({ run_id: "run-latest" }),
            ],
            results: [olderResult, latestResult],
          }),
        ),
      );

      renderCasePage("/research/case-report");

      const widgetGrid = await screen.findByLabelText("Research Case widgets");
      const report = widgetGrid.querySelector(
        '[data-widget-id="report-viewer"]',
      ) as HTMLElement;
      const markdownView = report.querySelector(
        ".cockpitReportMarkdown",
      ) as HTMLElement;

      expect(markdownView).toBeInTheDocument();
      expect(markdownView.querySelector("h3")).toHaveTextContent(
        "Latest report",
      );
      expect(markdownView).toHaveTextContent("Evidence-backed conclusion.");
      expect(markdownView).not.toHaveTextContent("Older report");
      const reportViewer = report.querySelector(
        ".cockpitReportViewer",
      ) as HTMLElement;
      expect(reportViewer).toHaveAttribute("data-report-read-only", "true");
      expect(report.querySelector("textarea")).toBeNull();
      expect(report.querySelector("[contenteditable]")).toBeNull();
    });

    it("renders an explicit empty report state when the latest result is missing", async () => {
      mockUseWorkspace.mockReturnValue(
        successQuery(
          makeWorkspace({
            runs: [makeRun({ run_id: "run-without-result" })],
            results: [null],
          }),
        ),
      );

      renderCasePage("/research/case-report-empty");

      const widgetGrid = await screen.findByLabelText("Research Case widgets");
      const report = widgetGrid.querySelector(
        '[data-widget-id="report-viewer"]',
      ) as HTMLElement;

      expect(report).toHaveTextContent("暂无报告");
      expect(report).toHaveTextContent("尚无 Result");
      expect(report.querySelector(".cockpitReportMarkdown")).toBeNull();
    });

    it("renders an explicit empty report state when report_markdown is blank", async () => {
      mockUseWorkspace.mockReturnValue(
        successQuery(
          makeWorkspace({
            runs: [makeRun()],
            results: [makeResult({ report_markdown: "   " })],
          }),
        ),
      );

      renderCasePage("/research/case-report-blank");

      const widgetGrid = await screen.findByLabelText("Research Case widgets");
      const report = widgetGrid.querySelector(
        '[data-widget-id="report-viewer"]',
      ) as HTMLElement;

      expect(report).toHaveTextContent("暂无报告");
      expect(report).toHaveTextContent("未提供 report_markdown");
      expect(report.querySelector(".cockpitReportMarkdown")).toBeNull();
    });

    it("renders an explicit missing-result marker when results[i] is null", async () => {
      mockUseWorkspace.mockReturnValue(
        successQuery(
          makeWorkspace({
            runs: [makeRun({ run_id: "run-1", status: "running" })],
            results: [null],
          }),
        ),
      );

      renderCasePage("/research/case-nullable-result");

      const widgetGrid = await screen.findByLabelText("Research Case widgets");
      const result = widgetGrid.querySelector(
        '[data-widget-id="research-result"]',
      ) as HTMLElement;

      expect(result).toHaveTextContent("尚无研究结论");
      expect(result).toHaveTextContent("尚无 Result");
      expect(result).toHaveTextContent("run-1");
      expect(result).toHaveTextContent("运行中");
      expect(result.textContent ?? "").not.toMatch(/buy|sell/i);
    });

    it("renders the run diagnostic block with error_summary when a run is failed", async () => {
      mockUseWorkspace.mockReturnValue(
        successQuery(
          makeWorkspace({
            runs: [
              makeRun({
                run_id: "run-failed",
                status: "failed",
                error_summary: "evidence pack hash mismatch",
              }),
            ],
            results: [null],
          }),
        ),
      );

      renderCasePage("/research/case-failed-run");

      const widgetGrid = await screen.findByLabelText("Research Case widgets");
      const result = widgetGrid.querySelector(
        '[data-widget-id="research-result"]',
      ) as HTMLElement;

      const diagnostic = result.querySelector(
        "[data-run-diagnostic]",
      ) as HTMLElement;
      expect(diagnostic).toBeInTheDocument();
      expect(diagnostic).toHaveClass("cockpitRunDiagnostic");
      expect(diagnostic).toHaveTextContent("evidence pack hash mismatch");
    });

    it("keeps the raw status text for an unknown run status", async () => {
      mockUseWorkspace.mockReturnValue(
        successQuery(
          makeWorkspace({
            runs: [
              makeRun({
                run_id: "run-unknown-status",
                status: "weird_state",
              }),
            ],
            results: [null],
          }),
        ),
      );

      renderCasePage("/research/case-unknown-run-status");

      const widgetGrid = await screen.findByLabelText("Research Case widgets");
      const result = widgetGrid.querySelector(
        '[data-widget-id="research-result"]',
      ) as HTMLElement;

      const statusNode = result.querySelector(
        "[data-run-status]",
      ) as HTMLElement;
      expect(statusNode).toHaveAttribute("data-run-status", "weird_state");
      expect(statusNode).toHaveTextContent("weird_state");
      expect(result.querySelector("[data-run-diagnostic]")).toBeNull();
    });
  });

  describe("Report Viewer markdown rendering", () => {
    function setupReportWorkspace(reportMarkdown: string): void {
      const result = makeResult({
        result_id: "55555555-5555-5555-5555-555555555555",
        run_id: "33333333-3333-3333-3333-333333333333",
        model_key: "model.basic",
        model_version: "1.2.3",
        adapter_version: "adapter-2026.08",
        playbook_version: "playbook.v2",
        report_markdown: reportMarkdown,
        evidence_ids: ["evidence-alpha", "evidence-beta"],
      });
      mockUseWorkspace.mockReturnValue(
        successQuery(
          makeWorkspace({
            runs: [makeRun()],
            results: [result],
          }),
        ),
      );
    }

    function getReportRoot(): HTMLElement {
      const widgetGrid = screen.getByLabelText("Research Case widgets");
      const report = widgetGrid.querySelector(
        '[data-widget-id="report-viewer"]',
      );
      if (!report) throw new Error("report-viewer widget not found");
      return report as HTMLElement;
    }

    function getMarkdownView(): HTMLElement {
      const markdown = getReportRoot().querySelector(
        ".cockpitReportMarkdown",
      );
      if (!markdown) throw new Error("cockpitReportMarkdown not found");
      return markdown as HTMLElement;
    }

    it("renders the supported block nodes: headings, paragraphs, lists, code, inline code, links", async () => {
      setupReportWorkspace(
        [
          "# Top heading",
          "## Sub heading",
          "### Tiny heading",
          "",
          "Plain paragraph with `inline_code` and a [safe link](https://example.com/path).",
          "",
          "- first bullet",
          "- second bullet with `code`",
          "",
          "```ts",
          "const x: number = 1;",
          "```",
        ].join("\n"),
      );

      renderCasePage("/research/case-report-markdown");

      const markdownView = getMarkdownView();

      const headings = markdownView.querySelectorAll(
        ".cockpitReportHeading",
      );
      expect(headings.length).toBe(3);
      expect(headings[0]?.tagName).toBe("H3");
      expect(headings[0]).toHaveTextContent("Top heading");
      expect(headings[0]).toHaveAttribute("data-report-level", "1");
      expect(headings[1]?.tagName).toBe("H4");
      expect(headings[1]).toHaveTextContent("Sub heading");
      expect(headings[1]).toHaveAttribute("data-report-level", "2");
      expect(headings[2]?.tagName).toBe("H5");
      expect(headings[2]).toHaveTextContent("Tiny heading");
      expect(headings[2]).toHaveAttribute("data-report-level", "3");

      const paragraphs = markdownView.querySelectorAll(
        ".cockpitReportParagraph",
      );
      expect(paragraphs.length).toBe(1);
      expect(paragraphs[0]).toHaveTextContent("Plain paragraph with");
      const inlineCode = markdownView.querySelectorAll(
        ".cockpitReportInlineCode",
      );
      expect(inlineCode.length).toBeGreaterThanOrEqual(1);
      expect(inlineCode[0]).toHaveTextContent("inline_code");

      const link = markdownView.querySelector(".cockpitReportLink");
      expect(link).not.toBeNull();
      expect(link).toHaveAttribute("href", "https://example.com/path");
      expect(link).toHaveTextContent("safe link");
      expect(link).toHaveAttribute("rel", "noopener noreferrer");
      expect(link).toHaveAttribute("target", "_blank");

      const list = markdownView.querySelector(".cockpitReportList");
      expect(list).not.toBeNull();
      const items = list?.querySelectorAll("li") ?? [];
      expect(items.length).toBe(2);
      expect(items[0]).toHaveTextContent("first bullet");
      expect(items[1]).toHaveTextContent("second bullet with");

      const codeBlock = markdownView.querySelector(
        ".cockpitReportCodeBlock",
      );
      expect(codeBlock).not.toBeNull();
      expect(codeBlock?.tagName).toBe("PRE");
      expect(codeBlock).toHaveTextContent("const x: number = 1;");
      expect(codeBlock).toHaveAttribute("data-report-code-block", "true");
    });

    it("treats HTML tags and script content as inert text, never as elements", async () => {
      setupReportWorkspace(
        [
          "# Safe title",
          "",
          "<script>window.__pwned = true;</script>",
          "",
          "Inline <img src=x onerror=alert(1)> stays as text.",
        ].join("\n"),
      );

      renderCasePage("/research/case-report-xss");

      const markdownView = getMarkdownView();
      expect(markdownView.querySelector("script")).toBeNull();
      expect(markdownView.querySelector("img")).toBeNull();
      expect(markdownView.querySelector("[onerror]")).toBeNull();
      expect(markdownView).toHaveTextContent("<script>");
      expect(markdownView).toHaveTextContent("window.__pwned = true;");
      expect(markdownView).toHaveTextContent("Inline");
      expect(markdownView).toHaveTextContent("onerror=alert(1)");
    });

    it("renders unsafe URLs as inert text instead of a clickable link", async () => {
      setupReportWorkspace(
        [
          "Refer to [evil js](javascript:alert(1)) and [evil mail](mailto:x@y.test).",
          "",
          "Real safe link: [docs](https://example.com/docs).",
        ].join("\n"),
      );

      renderCasePage("/research/case-report-unsafe-url");

      const markdownView = getMarkdownView();
      const links = Array.from(
        markdownView.querySelectorAll("a"),
      ) as HTMLAnchorElement[];
      const safeLinks = links.filter((link) =>
        link.classList.contains("cockpitReportLink"),
      );
      expect(safeLinks.length).toBe(1);
      expect(safeLinks[0]).toHaveAttribute("href", "https://example.com/docs");
      expect(safeLinks[0]).toHaveTextContent("docs");

      const jsLink = links.find((link) =>
        (link.getAttribute("href") ?? "").toLowerCase().startsWith(
          "javascript:",
        ),
      );
      expect(jsLink).toBeUndefined();

      expect(markdownView).toHaveTextContent("[evil js](javascript:alert(1))");
      expect(markdownView).toHaveTextContent("[evil mail](mailto:x@y.test)");
    });

    it("renders the report metadata block (result_id, created_at, model@version, adapter, playbook)", async () => {
      setupReportWorkspace("# Title");

      renderCasePage("/research/case-report-meta");

      const report = getReportRoot();
      expect(report).toHaveTextContent("Result ID");
      expect(report).toHaveTextContent("55555555-5555-5555-5555-555555555555");
      expect(report).toHaveTextContent("Created At");
      expect(report).toHaveTextContent("2026-08-09T00:35:00Z");
      expect(report).toHaveTextContent("Model");
      const modelField = report.querySelector(
        '[data-report-meta-field="model"]',
      );
      expect(modelField).toHaveTextContent("model.basic@1.2.3");
      expect(report).toHaveTextContent("Adapter");
      const adapterField = report.querySelector(
        '[data-report-meta-field="adapter"]',
      );
      expect(adapterField).toHaveTextContent("adapter-2026.08");
      expect(report).toHaveTextContent("Playbook");
      const playbookField = report.querySelector(
        '[data-report-meta-field="playbook"]',
      );
      expect(playbookField).toHaveTextContent("playbook.v2");
    });

    it("renders evidence_ids as read-only anchors that target #case-evidence-pack", async () => {
      setupReportWorkspace("# Title");

      renderCasePage("/research/case-report-evidence");

      const report = getReportRoot();
      const refs = Array.from(
        report.querySelectorAll("[data-evidence-ref]"),
      ) as HTMLAnchorElement[];
      expect(refs.length).toBe(2);

      const alpha = refs.find(
        (ref) => ref.getAttribute("data-evidence-ref") === "evidence-alpha",
      );
      expect(alpha).toBeDefined();
      expect(alpha).toHaveAttribute("href", "#case-evidence-pack");
      expect(alpha).toHaveTextContent("evidence-alpha");

      const beta = refs.find(
        (ref) => ref.getAttribute("data-evidence-ref") === "evidence-beta",
      );
      expect(beta).toBeDefined();
      expect(beta).toHaveAttribute("href", "#case-evidence-pack");
      expect(beta).toHaveTextContent("evidence-beta");

      const target = document.getElementById("case-evidence-pack");
      expect(target).not.toBeNull();
    });

    it("omits the evidence list when result has no evidence_ids", async () => {
      mockUseWorkspace.mockReturnValue(
        successQuery(
          makeWorkspace({
            runs: [makeRun()],
            results: [
              makeResult({
                report_markdown: "# No evidence",
                evidence_ids: [],
              }),
            ],
          }),
        ),
      );

      renderCasePage("/research/case-report-no-evidence");

      const report = getReportRoot();
      expect(report.querySelector("[data-evidence-ref]")).toBeNull();
      expect(report.querySelector(".cockpitReportEvidenceList")).toBeNull();
      expect(getMarkdownView()).toHaveTextContent("No evidence");
    });
  });

  describe("External Discovery section", () => {
    function makeDiscoveryItem(
      overrides: Partial<
        NonNullable<
          ResearchCaseWorkspaceResponse["external_discovery"]
        >[number]
      > = {},
    ): NonNullable<
      ResearchCaseWorkspaceResponse["external_discovery"]
    >[number] {
      return {
        evidence_id: "ext-evi:11111111",
        observation_id: "22222222-2222-2222-2222-222222222222",
        run_id: "33333333-3333-3333-3333-333333333333",
        producer: "workbuddy",
        as_of: "2026-08-14",
        observed_at: "2026-08-14T09:00:00Z",
        source_uri: "archive://run/a.json",
        content_hash: "a".repeat(64),
        admission_status: "admitted",
        admission: {
          status: "admitted",
          reason: "all admission checks passed",
          rules_version: "observation-admission/1.0",
          decided_by: "system",
          checks: {
            identity_ok: true,
            freshness_ok: true,
            unit_ok: true,
            internal_cross_check_ok: true,
            conflict_detected: false,
          },
        },
        artifact: {
          logical_uri: "archive://run/a.json",
          content_hash: "a".repeat(64),
          media_type: "application/json",
          size_bytes: 256,
          run_id: "33333333-3333-3333-3333-333333333333",
          created_at: "2026-08-14T08:30:00Z",
        },
        ...overrides,
      };
    }

    function getDiscoveryWidget(): HTMLElement {
      const widgetGrid = screen.getByLabelText("Research Case widgets");
      const node = widgetGrid.querySelector(
        '[data-widget-id="external-discovery"]',
      );
      if (!node) throw new Error("external-discovery widget not found");
      return node as HTMLElement;
    }

    it("renders the explicit empty placeholder when no external evidence is bound", async () => {
      mockUseWorkspace.mockReturnValue(
        successQuery(makeWorkspace({ external_discovery: [] })),
      );

      renderCasePage("/research/case-discovery-empty");

      const discovery = getDiscoveryWidget();
      expect(discovery).toHaveTextContent("暂无 External Discovery");
      expect(
        discovery.querySelector(".cockpitExternalDiscoveryList"),
      ).toBeNull();
    });

    it("renders the discovery chain with distinct WorkBuddy / Admission / Artifact badges", async () => {
      mockUseWorkspace.mockReturnValue(
        successQuery(
          makeWorkspace({
            external_discovery: [
              makeDiscoveryItem({
                evidence_id: "ext-evi:workbuddy-1",
                admission_status: "admitted",
              }),
            ],
          }),
        ),
      );

      renderCasePage("/research/case-discovery-populated");

      const discovery = getDiscoveryWidget();
      // The chain row is keyed by ``evidence_id`` so the front-end
      // can deep-link to a specific provenance slot.
      const item = discovery.querySelector(
        '[data-external-discovery-id="ext-evi:workbuddy-1"]',
      ) as HTMLElement;
      expect(item).toBeInTheDocument();
      // WorkBuddy observation badge: distinct visual label so the
      // external observation is not mistaken for a formal fact or a
      // research interpretation.
      const observationKind = item.querySelector(
        "[data-discovery-observation-kind]",
      );
      expect(observationKind?.textContent ?? "").toMatch(/WorkBuddy 观察/);
      // Admission status badge: keeps the formal decision visible.
      const admissionBadge = item.querySelector(
        "[data-discovery-admission-status]",
      );
      expect(admissionBadge?.textContent ?? "").toMatch(/Admission: admitted/);
      // Provenance metadata surfaces the rule-set identity and
      // decision reason so a reviewer can audit the chain.
      expect(item).toHaveTextContent("observation-admission/1.0");
      expect(item).toHaveTextContent("all admission checks passed");
      // The artifact summary carries only safe provenance fields
      // (logical URI, hash, media type, size, run id, created_at).
      expect(item).toHaveTextContent("archive://run/a.json");
      expect(item).toHaveTextContent("application/json");
      const artifactBlock = item.querySelector(
        '[data-discovery-artifact-state="available"]',
      );
      expect(artifactBlock).not.toBeNull();
      // Host paths and shared-directory paths must never appear in
      // the rendered HTML.
      expect(discovery.textContent ?? "").not.toMatch(/\/mnt\/|C:\\|\\\\host/);
    });

    it("renders an understandable unavailable state when artifact is null", async () => {
      mockUseWorkspace.mockReturnValue(
        successQuery(
          makeWorkspace({
            external_discovery: [
              makeDiscoveryItem({
                evidence_id: "ext-evi:no-artifact",
                artifact: null,
              }),
            ],
          }),
        ),
      );

      renderCasePage("/research/case-discovery-no-artifact");

      const discovery = getDiscoveryWidget();
      const item = discovery.querySelector(
        '[data-external-discovery-id="ext-evi:no-artifact"]',
      ) as HTMLElement;
      // The unavailable block is the only artifact summary so the
      // front-end never fabricates size_bytes / media_type / hash.
      const unavailable = item.querySelector(
        '[data-discovery-artifact-state="unavailable"]',
      );
      expect(unavailable).not.toBeNull();
      expect(item.querySelector('[data-discovery-artifact-state="available"]'))
        .toBeNull();
      expect(unavailable).toHaveTextContent("Artifact 暂不可用");
      // Producer / admission metadata still surfaces so the
      // WorkBuddy observation is visible even when artifact is null.
      expect(item).toHaveTextContent("WorkBuddy 观察");
      expect(item).toHaveTextContent("Admission: admitted");
    });

    it("keeps WorkBuddy observation, formal admission, and research interpretation visibly distinct", async () => {
      const runId = "33333333-3333-3333-3333-333333333333";
      mockUseWorkspace.mockReturnValue(
        successQuery(
          makeWorkspace({
            external_discovery: [
              makeDiscoveryItem({
                evidence_id: "ext-evi:distinct",
                admission_status: "corroborated",
              }),
            ],
            runs: [
              makeRun({ run_id: runId, status: "succeeded" }),
            ],
            results: [
              makeResult({
                run_id: runId,
                conclusion: "趋势向上",
              }),
            ],
          }),
        ),
      );

      renderCasePage("/research/case-discovery-distinct");

      const widgetGrid = screen.getByLabelText("Research Case widgets");
      const discovery = widgetGrid.querySelector(
        '[data-widget-id="external-discovery"]',
      ) as HTMLElement;
      const result = widgetGrid.querySelector(
        '[data-widget-id="research-result"]',
      ) as HTMLElement;
      // WorkBuddy observation: appears under the discovery widget.
      expect(discovery.textContent ?? "").toMatch(/WorkBuddy 观察/);
      // Formal admission: appears under the discovery widget too
      // but with a different badge ("Admission: corroborated"),
      // distinct from the run status badge ("succeeded") under the
      // research result widget.
      expect(discovery.textContent ?? "").toMatch(
        /Admission: corroborated/,
      );
      expect(result.textContent ?? "").not.toMatch(/Admission: corroborated/);
      expect(result.textContent ?? "").toMatch(/已完成/);
      // Research interpretation: the result widget carries the
      // conclusion text, never the discovery widget.
      expect(discovery.textContent ?? "").not.toMatch(/趋势向上/);
      expect(result.textContent ?? "").toMatch(/趋势向上/);
    });
  });

  describe("error fallback", () => {
    it("surfaces a 404 detail as an explicit failed state", async () => {
      mockUseWorkspace.mockReturnValue(
        errorQuery(new ApiError("Research Case not found", 404)),
      );

      renderCasePage("/research/missing-case");

      const widgetGrid = screen.getByLabelText("Research Case widgets");
      await waitFor(() => {
        expect(
          within(widgetGrid).getAllByText("Research Case not found").length,
        ).toBeGreaterThan(0);
      });
    });
  });
});
