import "@testing-library/jest-dom/vitest";
import { afterEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";
vi.stubGlobal(
  "fetch",
  vi.fn(() => {
    throw new Error("Network forbidden in fixture tests");
  }),
);
afterEach(cleanup);
