import type { InspectionApi } from "./types";
// Safe fixed messages: never display raw server diagnostics or validation inputs.
export async function responseError(response: Response): Promise<Error> {
  let data: { error?: { code?: string }; detail?: unknown } = {};
  try {
    data = await response.json();
  } catch {
    /* Non-JSON failure */
  }
  const validation =
    response.status === 422 &&
    (Array.isArray(data.detail) || data.error || data.detail);
  return new Error(
    response.status === 413
      ? "Image or transient storage limit exceeded."
      : response.status === 404
        ? "Inspection, photo, or uploaded content was not found."
        : response.status === 409
          ? "This action conflicts with the current state. Refresh before trying again."
          : validation
            ? "Check the entered information. Photos must be valid JPEG/PNG images."
            : "Unable to complete the request. Check that the local backend is running.",
  );
}
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
    if (!response.ok) throw await responseError(response);
    return response.json() as Promise<T>;
  }
  const path = (id: string) => `/inspections/${encodeURIComponent(id)}`;
  return {
    mode: "http",
    content: {
      contentUrl: (id, photo) =>
        base + path(id) + `/photos/${encodeURIComponent(photo)}/content`,
      upload: async (id, photo, file) => {
        const response = await fetch(
          base + path(id) + `/photos/${encodeURIComponent(photo)}/content`,
          {
            method: "PUT",
            headers: { "Content-Type": file.type },
            body: file,
          },
        );
        if (!response.ok) throw await responseError(response);
      },
    },
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
