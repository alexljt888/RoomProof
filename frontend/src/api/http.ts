import type { InspectionApi } from "./types";
// Prepared boundary only: the demo never instantiates this client.
export function httpApi(base = "/api"): InspectionApi {
  async function request<T>(path: string, body?: unknown): Promise<T> {
    const response = await fetch(
      base + path,
      body === undefined
        ? {}
        : {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          },
    );
    if (!response.ok)
      throw new Error(
        response.status === 409
          ? "This action conflicts with the current state. Refresh and try again."
          : response.status === 422
            ? "Check the entered information."
            : "Unable to complete the request.",
      );
    return response.json() as Promise<T>;
  }
  const path = (id: string) => `/inspections/${encodeURIComponent(id)}`;
  return {
    list: () => request("/inspections"),
    get: (id) => request(path(id)),
    create: (body) => request("/inspections", body),
    addRoom: (id, name) => request(path(id) + "/rooms", { name }),
    registerPhoto: (id, room, body) =>
      request(path(id) + `/rooms/${encodeURIComponent(room)}/photos`, body),
    analyze: (id, photo) =>
      request(path(id) + `/photos/${encodeURIComponent(photo)}/analyses`, {}),
    review: (id, finding, body) =>
      request(
        path(id) + `/findings/${encodeURIComponent(finding)}/review`,
        body,
      ),
  };
}
