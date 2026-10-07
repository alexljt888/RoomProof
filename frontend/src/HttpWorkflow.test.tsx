import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import App from "./App";
import { createDemoApi } from "./api/demo";
import { httpApi } from "./api/http";

function setup() {
  const api = createDemoApi();
  api.mode = "http";
  api.content = {
    upload: vi.fn(async () => {}),
    contentUrl: (i, p) => `/api/inspections/${i}/photos/${p}/content`,
  };
  const user = userEvent.setup();
  render(
    <MemoryRouter initialEntries={["/inspections/demo"]}>
      <App api={api} />
    </MemoryRouter>,
  );
  return { api, user };
}
async function choose(file: File) {
  fireEvent.change(await screen.findByLabelText("Choose room photo"), {
    target: { files: [file] },
  });
}
const file = (type = "image/png") =>
  new File(
    ["synthetic"],
    type === "image/png" ? "example.png" : "example.jpg",
    { type },
  );

describe("HTTP-mode photo workflow", () => {
  it("reviews backend-authoritative real findings without a fake label or provider connection", async () => {
    const { api, user } = setup();
    const originalAnalyze = api.analyze.bind(api);
    vi.spyOn(api, "analyze").mockImplementation(async (iid, pid) => {
      const state = await originalAnalyze(iid, pid);
      const analysis = state.analyses.find((a) => a.photo_id === pid)!;
      analysis.analyzer_id = "openai-photo";
      analysis.limitations = [];
      analysis.provenance = {
        requested_model: "synthetic-model",
        provider_model: "synthetic-model",
        prompt_version: "roomproof-observations-v1",
        schema_version: "roomproof-observations-v1",
        preparation_version: "rgb-png-v1",
      };
      return state;
    });
    await user.click(await screen.findByRole("button", { name: /Bedroom/ }));
    await choose(file());
    fireEvent.load(await screen.findByRole("img", { name: "Room evidence 1" }));
    await user.click(screen.getByRole("button", { name: "Analyze photo" }));
    await user.click(
      await screen.findByRole("button", { name: "Review suggestions →" }),
    );
    expect(
      screen.queryByText("Fake analysis · no AI inspected this image."),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText(/default backend uses fake/),
    ).not.toBeInTheDocument();
    expect(screen.getByText("pending review")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Confirm" }));
    await user.click(screen.getByLabelText("No, keep it out"));
    await user.click(screen.getByRole("button", { name: "Save review" }));
    expect(api.analyze).toHaveBeenCalledTimes(1);
    // Global fetch is blocked by test setup; all calls use the injected backend API.
    expect(vi.mocked(fetch)).not.toHaveBeenCalled();
  });

  it("binds the selected bytes to this registration, not another tab's unseen photo", async () => {
    const { api, user } = setup();
    await user.click(await screen.findByRole("button", { name: /Bedroom/ }));
    // Simulate another tab registering metadata after this UI fetched its snapshot.
    const other = await api.registerPhoto("demo", "living", {
      original_filename: "other.png",
      declared_media_type: "image/png",
    });
    const otherId = other.photos.at(-1)!.id;
    const selected = file();
    await choose(selected);
    await screen.findByRole("img", { name: "Room evidence 1" });
    const latest = await api.get("demo");
    const own = latest.photos.find((p) => p.room_id === "bedroom")!;
    expect(api.content!.upload).toHaveBeenCalledExactlyOnceWith(
      "demo",
      own.id,
      selected,
    );
    expect(own.id).not.toBe(otherId);
  });

  it.each(["image/jpeg", "image/png"])(
    "uploads %s once, waits for content, then analyzes",
    async (type) => {
      const { api, user } = setup();
      const register = vi.spyOn(api, "registerPhoto");
      const analyze = vi.spyOn(api, "analyze");
      let finish!: () => void;
      const gate = new Promise<void>((r) => {
        finish = r;
      });
      vi.mocked(api.content!.upload).mockImplementation(() => gate);
      await user.click(await screen.findByRole("button", { name: /Bedroom/ }));
      await choose(file(type));
      expect(await screen.findByText("Uploading photo…")).toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: "Analyze photo" }),
      ).toBeDisabled();
      await choose(file(type));
      expect(register).toHaveBeenCalledTimes(1);
      await act(async () => {
        finish();
        await gate;
      });
      const image = await screen.findByRole("img", { name: "Room evidence 1" });
      expect(image.getAttribute("src")).toContain("/content");
      fireEvent.load(image);
      await user.click(screen.getByRole("button", { name: "Analyze photo" }));
      expect(analyze).toHaveBeenCalledTimes(1);
      expect(
        await screen.findByText("Fake analysis · no AI inspected this image."),
      ).toBeInTheDocument();
      await user.click(
        screen.getByRole("button", { name: "Review suggestions →" }),
      );
      expect(screen.getByText("pending review")).toBeInTheDocument();
      expect(
        screen
          .getByRole("img", { name: "Original finding evidence" })
          .getAttribute("src"),
      ).toContain("/content");
      await user.click(screen.getByRole("button", { name: "Confirm" }));
      await user.click(screen.getByLabelText("Yes, include it"));
      await user.click(screen.getByRole("button", { name: "Save review" }));
      expect(
        await screen.findByText("Included in future report"),
      ).toBeInTheDocument();
    },
  );
  it("rejects unsupported selection without registration/upload", async () => {
    const { api } = setup();
    const register = vi.spyOn(api, "registerPhoto");
    await choose(
      new File(["synthetic"], "example.heic", { type: "image/heic" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("JPEG/PNG only");
    expect(register).not.toHaveBeenCalled();
    expect(api.content!.upload).not.toHaveBeenCalled();
  });
  it("retries failed upload on the same photo UUID", async () => {
    const { api, user } = setup();
    const register = vi.spyOn(api, "registerPhoto");
    vi.mocked(api.content!.upload).mockRejectedValueOnce(
      new Error("Upload failed"),
    );
    await user.click(await screen.findByRole("button", { name: /Bedroom/ }));
    await choose(file());
    expect(await screen.findByRole("alert")).toHaveTextContent("Upload failed");
    fireEvent.error(screen.getByRole("img", { name: "Room evidence 1" }));
    await user.click(
      screen.getByRole("button", { name: "Choose photo to retry upload" }),
    );
    await choose(file());
    expect(register).toHaveBeenCalledTimes(1);
    expect(api.content!.upload).toHaveBeenCalledTimes(2);
    const calls = vi.mocked(api.content!.upload).mock.calls;
    expect(calls[0][1]).toBe(calls[1][1]);
  });
  it("refreshes failed analysis state without retrying inference", async () => {
    const { api, user } = setup();
    const originalGet = api.get.bind(api);
    const failed = await originalGet("demo");
    const a = failed.analyses.find((a) => a.photo_id === "corner")!;
    const analyze = vi.spyOn(api, "analyze").mockResolvedValue(failed);
    const get = vi.spyOn(api, "get");
    await screen.findByRole("heading", { name: "Living room" });
    fireEvent.load(screen.getByRole("img", { name: "Room evidence 4" }));
    await user.click(screen.getByRole("button", { name: "Retry analysis" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "State refreshed",
    );
    expect(analyze).toHaveBeenCalledTimes(1);
    expect(get).toHaveBeenCalled();
    expect(a.status).toBe("failed");
  });
  it("blocks analysis after unknown outcome until explicit refresh succeeds", async () => {
    const { api, user } = setup();
    await screen.findByRole("heading", { name: "Living room" });
    const originalGet = api.get.bind(api);
    const analyze = vi
      .spyOn(api, "analyze")
      .mockRejectedValue(new Error("Connection lost"));
    const get = vi.spyOn(api, "get").mockRejectedValue(new Error("Offline"));
    fireEvent.load(screen.getByRole("img", { name: "Room evidence 2" }));
    await user.click(screen.getByRole("button", { name: "Analyze photo" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "status is unknown",
    );
    expect(analyze).toHaveBeenCalledTimes(1);
    expect(
      screen.getByRole("button", { name: "Analyze photo" }),
    ).toBeDisabled();
    get.mockImplementation(originalGet);
    await user.click(
      screen.getByRole("button", { name: "Refresh analysis state" }),
    );
    expect(
      screen.queryByRole("button", { name: "Refresh analysis state" }),
    ).not.toBeInTheDocument();
    expect(analyze).toHaveBeenCalledTimes(1);
  });
});

describe("native fetch boundary", () => {
  it("uses JSON operations and raw binary upload without inference retries", async () => {
    const fetch = vi.mocked(globalThis.fetch);
    fetch.mockResolvedValue({ ok: true, json: async () => ({}) } as Response);
    const api = httpApi();
    await api.create({
      renter_name: "Example",
      property_details: { address: "Synthetic" },
    });
    await api.addRoom("i", "Room");
    await api.registerPhoto("i", "r", {
      original_filename: "example.png",
      declared_media_type: "image/png",
    });
    const image = file();
    await api.content!.upload("i", "p", image);
    expect(fetch.mock.calls.at(-1)?.[1]).toEqual({
      method: "PUT",
      headers: { "Content-Type": "image/png" },
      body: image,
    });
    await api.analyze("i", "p");
    expect(
      fetch.mock.calls.filter(([url]) => String(url).endsWith("/analyses")),
    ).toHaveLength(1);
  });
  it.each([
    { error: { code: "invalid_domain_input" } },
    { detail: [{ loc: ["body"], msg: "private", type: "missing" }] },
  ])("handles both 422 shapes safely", async (body) => {
    vi.mocked(globalThis.fetch).mockResolvedValue({
      ok: false,
      status: 422,
      json: async () => body,
    } as Response);
    await expect(httpApi().addRoom("i", "")).rejects.toThrow(
      "Check the entered information",
    );
  });
});
