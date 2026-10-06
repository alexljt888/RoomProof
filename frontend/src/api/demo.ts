import type { Inspection, InspectionApi, Finding, Analysis } from "./types";
const now = () => new Date().toISOString();
const id = () => crypto.randomUUID();
export function createDemoApi(): InspectionApi {
  const stamp = now();
  const sample: Inspection = {
    id: "demo",
    created_at: stamp,
    renter_name: "Alex Example",
    property_details: { address: "24 Example Lane", unit: "4B" },
    rooms: [
      {
        id: "living",
        inspection_id: "demo",
        created_at: stamp,
        name: "Living room",
      },
      {
        id: "bedroom",
        inspection_id: "demo",
        created_at: stamp,
        name: "Bedroom",
      },
      {
        id: "kitchen",
        inspection_id: "demo",
        created_at: stamp,
        name: "Kitchen",
      },
    ],
    photos: [],
    analyses: [],
    findings: [],
  };
  for (const [pid, status] of [
    ["wall", "succeeded"],
    ["floor", "ready"],
    ["window", "pending"],
    ["corner", "failed"],
  ] as const) {
    sample.photos.push({
      id: pid,
      inspection_id: "demo",
      room_id: "living",
      created_at: stamp,
      original_filename: `example-${pid}.png`,
      declared_media_type: "image/png",
      capture_surface_hint: null,
    });
    if (status !== "ready")
      sample.analyses.push({
        id: "analysis-" + pid,
        inspection_id: "demo",
        photo_id: pid,
        created_at: stamp,
        analyzer_id: "fake",
        analyzer_version: "1",
        status,
        outcome: status === "succeeded" ? "findings_present" : null,
        completed_at: status === "pending" ? null : stamp,
        limitations: ["Illustrated demo only; no image was inspected."],
        failure_code: status === "failed" ? "unavailable" : null,
        provenance: null,
      });
  }
  function finding(i: Inspection, pid: string, aid: string): Finding {
    const photo = i.photos.find((p) => p.id === pid)!;
    return {
      id: id(),
      inspection_id: i.id,
      room_id: photo.room_id,
      created_at: now(),
      source_analysis_id: aid,
      state: "pending_review",
      original_proposal: {
        category: "chip",
        surface: "wall",
        location: "Lower wall, beside the baseboard",
        description: "A small area of chipped finish is visible on the wall.",
        certainty: "clear",
        evidence_photo_ids: [pid],
      },
      review: null,
      eligible_for_report: false,
    };
  }
  sample.findings.push(finding(sample, "wall", "analysis-wall"));
  const data = new Map([[sample.id, sample]]);
  const get = (key: string) => {
    const v = data.get(key);
    if (!v) throw new Error("Inspection not found.");
    return v;
  };
  const copy = (v: Inspection) => structuredClone(v);
  return {
    async list() {
      return [...data.values()].map(
        ({ id, created_at, property_details, renter_name }) =>
          structuredClone({ id, created_at, property_details, renter_name }),
      );
    },
    async get(key) {
      return copy(get(key));
    },
    async create(body) {
      const value: Inspection = {
        ...body,
        property_details: {
          ...body.property_details,
          unit: body.property_details.unit || null,
        },
        id: id(),
        created_at: now(),
        rooms: [],
        photos: [],
        analyses: [],
        findings: [],
      };
      data.set(value.id, value);
      return copy(value);
    },
    async addRoom(key, name) {
      const v = get(key);
      v.rooms.push({ id: id(), inspection_id: key, created_at: now(), name });
      return copy(v);
    },
    async registerPhoto(key, room, body) {
      const v = get(key);
      if (!v.rooms.some((r) => r.id === room))
        throw new Error("Room not found.");
      v.photos.push({
        ...body,
        id: id(),
        inspection_id: key,
        room_id: room,
        created_at: now(),
        capture_surface_hint: body.capture_surface_hint ?? null,
      });
      return copy(v);
    },
    async analyze(key, pid) {
      const v = get(key);
      if (!v.photos.some((p) => p.id === pid))
        throw new Error("Photo not found.");
      if (v.analyses.some((a) => a.photo_id === pid && a.status !== "failed"))
        throw new Error("Already analyzed or in progress.");
      const a: Analysis = {
        id: id(),
        inspection_id: key,
        photo_id: pid,
        created_at: now(),
        analyzer_id: "fake",
        analyzer_version: "1",
        status: "succeeded",
        outcome: "findings_present",
        completed_at: now(),
        limitations: ["Demo suggestion; no photo inspected."],
        failure_code: null,
        provenance: null,
      };
      v.analyses.push(a);
      v.findings.push(finding(v, pid, a.id));
      return copy(v);
    },
    async review(key, fid, body) {
      const v = get(key);
      const f = v.findings.find((f) => f.id === fid);
      if (!f || f.state !== "pending_review")
        throw new Error("Finding is unavailable for review.");
      let approved = null;
      if (body.action !== "reject") {
        const { certainty: _certainty, ...original } = f.original_proposal;
        void _certainty;
        approved =
          body.action === "confirm"
            ? { ...original, reportable: body.reportable }
            : {
                category: body.category,
                surface: body.surface,
                location: body.location,
                description: body.description,
                evidence_photo_ids:
                  body.evidence_photo_ids ?? original.evidence_photo_ids,
                reportable: body.reportable,
              };
      }
      f.review = {
        action: body.action,
        reviewed_at: now(),
        approved,
        reason: body.action === "reject" ? (body.reason ?? null) : null,
      };
      f.state = body.action === "reject" ? "rejected" : "confirmed";
      f.eligible_for_report = approved?.reportable ?? false;
      return copy(v);
    },
  };
}
