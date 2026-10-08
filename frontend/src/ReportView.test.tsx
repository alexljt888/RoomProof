import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import ReportView from "./components/ReportView";
import { createDemoApi } from "./api/demo";
import { httpApi } from "./api/http";
import type { InspectionReport } from "./api/types";

const report = (): InspectionReport => ({
  inspection_id: "example",
  address: "Approved property",
  unit: "101",
  renter: "Example",
  room_count: 1,
  finding_count: 1,
  pending_findings: 0,
  pending_analyses: 0,
  unanalysed_photos: 0,
  failed_analyses: 0,
  review_complete: true,
  photos_needing_analysis: 0,
  unavailable_evidence: 0,
  export_ready: true,
  rooms: [
    {
      id: "room",
      name: "Kitchen",
      findings: [
        {
          id: "finding",
          category: "hole",
          surface: "wall",
          location: "Left",
          description: "Human approved indentation",
          evidence_photo_ids: ["photo"],
        },
      ],
    },
  ],
});
function setup(value = report()) {
  const api = createDemoApi();
  api.reports = {
    preview: vi.fn(async () => value),
    download: vi.fn(
      async () => new Blob(["synthetic PDF"], { type: "application/pdf" }),
    ),
  };
  api.content = {
    upload: vi.fn(),
    contentUrl: () => "/api/inspections/example/photos/photo/content",
  };
  const view = render(<ReportView api={api} inspectionId="example" />);
  return { api, ...view };
}
describe("backend-authoritative reports", () => {
  it("shows approved backend projection without reusing demo findings or calculating eligibility", async () => {
    const { api } = setup();
    expect(
      await screen.findByText("Human approved indentation"),
    ).toBeInTheDocument();
    expect(api.reports!.preview).toHaveBeenCalledWith("example");
    expect(screen.getByText("hole on wall")).toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: "Approved report evidence" }),
    ).toHaveAttribute("src", expect.stringContaining("/content"));
    expect(
      screen.queryByText(/Synthetic example scratch/),
    ).not.toBeInTheDocument();
  });
  it("warns and blocks export while review remains pending", async () => {
    const value = report();
    value.review_complete = false;
    value.export_ready = false;
    value.pending_findings = 2;
    value.rooms[0].findings = [];
    value.finding_count = 0;
    const { api } = setup(value);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "2 pending suggestions",
    );
    expect(screen.getByRole("button", { name: "Download PDF" })).toBeDisabled();
    expect(api.reports!.download).not.toHaveBeenCalled();
  });
  it("keeps preview visible but uses backend export eligibility for unanalysed photos", async () => {
    const value = report();
    value.photos_needing_analysis = 1;
    value.unanalysed_photos = 1;
    value.export_ready = false;
    const { api } = setup(value);
    expect(
      await screen.findByText("Human approved indentation"),
    ).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "1 photo still needs successful analysis",
    );
    expect(screen.getByRole("button", { name: "Download PDF" })).toBeDisabled();
    expect(api.reports!.download).not.toHaveBeenCalled();
  });
  it("does not infer readiness from review status or counts", async () => {
    const value = report();
    value.export_ready = false;
    setup(value);
    expect(
      await screen.findByRole("button", { name: "Download PDF" }),
    ).toBeDisabled();
  });
  it("shows a zero-findings state from backend despite fixture findings", async () => {
    const value = report();
    value.finding_count = 0;
    value.rooms[0].findings = [];
    setup(value);
    expect(
      await screen.findByText("No confirmed reportable findings"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download PDF" })).toBeEnabled();
    expect(
      screen.queryByText("Human approved indentation"),
    ).not.toBeInTheDocument();
  });
  it("downloads only the backend PDF and releases its temporary URL", async () => {
    const { api } = setup();
    vi.stubGlobal(
      "URL",
      Object.assign(URL, {
        createObjectURL: vi.fn(() => "blob:synthetic"),
        revokeObjectURL: vi.fn(),
      }),
    );
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});
    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("button", { name: "Download PDF" }),
    );
    expect(api.reports!.download).toHaveBeenCalledExactlyOnceWith("example");
    expect(click).toHaveBeenCalledOnce();
    click.mockRestore();
    await waitFor(
      () => expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:synthetic"),
      { timeout: 2000 },
    );
  });
  it("refetches on remount and explicit refresh", async () => {
    const { api, unmount } = setup();
    await screen.findByText("Human approved indentation");
    unmount();
    const changed = report();
    changed.rooms[0].findings[0].description = "Latest approved content";
    vi.mocked(api.reports!.preview).mockResolvedValue(changed);
    render(<ReportView api={api} inspectionId="example" />);
    expect(
      await screen.findByText("Latest approved content"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Refresh preview" }));
    await waitFor(() => expect(api.reports!.preview).toHaveBeenCalledTimes(3));
  });
  it("describes unavailable evidence without claiming it is missing", async () => {
    setup();
    fireEvent.error(
      await screen.findByRole("img", { name: "Approved report evidence" }),
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      "Evidence could not be displayed",
    );
  });
  it("uses scoped HTTP preview and PDF routes and handles blocked export", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify(report()), {
        headers: { "content-type": "application/json" },
      }),
    );
    expect((await httpApi().reports!.preview("example")).finding_count).toBe(1);
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/inspections/example/report",
      {},
    );
    fetchMock.mockResolvedValueOnce(
      new Response("%PDF-synthetic", {
        headers: { "content-type": "application/pdf" },
      }),
    );
    expect((await httpApi().reports!.download("example")).type).toBe(
      "application/pdf",
    );
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/inspections/example/report.pdf",
    );
    fetchMock.mockResolvedValueOnce(
      new Response("private diagnostics", { status: 409 }),
    );
    await expect(httpApi().reports!.download("example")).rejects.toThrow(
      "Export blocked",
    );
  });
});
