import { describe, it, expect, vi } from "vitest";
import { render, screen, within, act, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import App from "./App";
import { createDemoApi } from "./api/demo";
function setup(path = "/") {
  const user = userEvent.setup();
  render(
    <MemoryRouter initialEntries={[path]}>
      <App api={createDemoApi()} />
    </MemoryRouter>,
  );
  return user;
}
async function review() {
  const user = setup("/inspections/demo");
  await user.click(await screen.findByRole("button", { name: "Review (1)" }));
  return user;
}
describe("RoomProof demo", () => {
  it("renders landing and navigates to a new inspection", async () => {
    const user = setup();
    expect(screen.getByText("Your peace of mind.")).toBeInTheDocument();
    await user.click(screen.getByRole("link", { name: /Start inspection/ }));
    expect(
      screen.getByRole("heading", { name: "Let’s make it yours." }),
    ).toBeInTheDocument();
    await user.type(screen.getByLabelText("Renter name"), "Demo Renter");
    await user.type(screen.getByLabelText("Property address"), "Example home");
    await user.click(screen.getByRole("button", { name: /Create inspection/ }));
    expect(
      await screen.findByRole("heading", { name: "Example home" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Add your first room")).toBeInTheDocument();
  });
  it("shows rooms, photo states and summary", async () => {
    const user = setup("/inspections/demo");
    expect(
      await screen.findByRole("heading", { name: "Living room" }),
    ).toBeInTheDocument();
    for (const state of ["ready", "pending", "failed", "succeeded"])
      expect(screen.getByText(state)).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "Inspection summary" }),
    );
    expect(screen.getByText("Confirmed · not reportable")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Bedroom/ }));
    expect(screen.getByText("A fresh canvas.")).toBeInTheDocument();
  });
  it("requires reportability choice before confirming", async () => {
    const user = await review();
    expect(screen.getByText("pending review")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Confirm" }));
    await user.click(screen.getByRole("button", { name: "Save review" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Choose Yes or No");
    await user.click(screen.getByLabelText("No, keep it out"));
    await user.click(screen.getByRole("button", { name: "Save review" }));
    expect(
      await screen.findByText("Confirmed · not included in future report"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Confirm" }),
    ).not.toBeInTheDocument();
  });
  it("keeps original proposal separate from edited approved content", async () => {
    const user = await review();
    await user.click(screen.getByRole("button", { name: "Edit" }));
    const description = screen.getByLabelText("Description");
    await user.clear(description);
    await user.type(description, "Human description of this mark");
    await user.click(screen.getByLabelText("Yes, include it"));
    await user.click(screen.getByRole("button", { name: "Save review" }));
    expect(
      await screen.findByText("Human description of this mark"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "A small area of chipped finish is visible on the wall.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Your approved content")).toBeInTheDocument();
    expect(screen.getByText("Included in future report")).toBeInTheDocument();
  });
  it("rejects with an optional reason and updates summary", async () => {
    const user = await review();
    await user.click(screen.getByRole("button", { name: "Reject" }));
    await user.type(
      screen.getByLabelText("Reason (optional)"),
      "This is a seam",
    );
    await user.click(screen.getByRole("button", { name: "Reject suggestion" }));
    expect(
      await screen.findByText(/You rejected this suggestion/),
    ).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "Inspection summary" }),
    );
    const label = screen.getByText("Rejected");
    expect(within(label.parentElement!).getByText("1")).toBeInTheDocument();
  });
  it("adds a room and fixture photo through the shared client boundary", async () => {
    const user = setup("/inspections/demo");
    await user.click(await screen.findByRole("button", { name: "+ Add room" }));
    await user.type(screen.getByLabelText("Room name"), "Study");
    await user.click(screen.getByRole("button", { name: "Add room" }));
    await user.click(
      await screen.findByRole("button", { name: "+ Add demo photo" }),
    );
    await user.click(
      await screen.findByRole("button", { name: "Analyze demo photo" }),
    );
    expect(
      await screen.findByRole("button", { name: "Review suggestions →" }),
    ).toBeInTheDocument();
  });
});

describe("demo photo additions", () => {
  it.each(["Review (1)", "Inspection summary"])(
    "reveals exactly one ready photo from %s in the selected room",
    async (tab) => {
      const api = createDemoApi();
      const register = vi.spyOn(api, "registerPhoto");
      const user = userEvent.setup();
      render(
        <MemoryRouter initialEntries={["/inspections/demo"]}>
          <App api={api} />
        </MemoryRouter>,
      );
      await user.click(await screen.findByRole("button", { name: /Bedroom/ }));
      await user.click(
        screen.getByRole("button", {
          name: tab === "Review (1)" ? "Review (0)" : tab,
        }),
      );
      await user.click(
        screen.getByRole("button", { name: "+ Add demo photo" }),
      );
      expect(
        await screen.findByRole("heading", { name: "Room detail 1" }),
      ).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Photos" })).toHaveAttribute(
        "aria-pressed",
        "true",
      );
      expect(screen.getByText("ready")).toBeInTheDocument();
      expect(register).toHaveBeenCalledTimes(1);
      expect(
        (await api.get("demo")).photos.filter((p) => p.room_id === "bedroom"),
      ).toHaveLength(1);
      await user.click(
        screen.getByRole("button", { name: "Analyze demo photo" }),
      );
      await user.click(
        await screen.findByRole("button", { name: "Review suggestions →" }),
      );
      expect(screen.getByText("pending review")).toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: /Living room/ }));
      expect(
        screen.getAllByRole("heading", { name: /Room detail/ }),
      ).toHaveLength(4);
    },
  );
  it("ignores a duplicate event while an addition is in flight", async () => {
    const api = createDemoApi();
    const original = api.registerPhoto.bind(api);
    let release!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const register = vi
      .spyOn(api, "registerPhoto")
      .mockImplementation(async (...args) => {
        await gate;
        return original(...args);
      });
    render(
      <MemoryRouter initialEntries={["/inspections/demo"]}>
        <App api={api} />
      </MemoryRouter>,
    );
    const add = await screen.findByRole("button", { name: "+ Add demo photo" });
    act(() => {
      fireEvent.click(add);
      fireEvent.click(add);
    });
    expect(register).toHaveBeenCalledTimes(1);
    expect(add).toBeDisabled();
    await act(async () => {
      release();
      await gate;
    });
    expect(
      await screen.findByRole("heading", { name: "Room detail 5" }),
    ).toBeInTheDocument();
    expect((await api.get("demo")).photos).toHaveLength(5);
  });
});
