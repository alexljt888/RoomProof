// Mirrors backend/app/schemas.py. IDs and timestamps are serialized strings.
export const categories = [
  "scratch",
  "scuff",
  "stain",
  "crack",
  "hole",
  "chipped_paint",
  "dirt",
  "chip",
] as const;
export const surfaces = [
  "wall",
  "floor",
  "door",
  "trim",
  "countertop",
] as const;
export type Category = (typeof categories)[number];
export type Surface = (typeof surfaces)[number];
export interface CreateInspection {
  property_details: { address: string; unit?: string | null };
  renter_name: string;
}
export interface InspectionSummary {
  id: string;
  created_at: string;
  property_details: { address: string; unit: string | null };
  renter_name: string;
}
export interface Room {
  id: string;
  inspection_id: string;
  created_at: string;
  name: string;
}
export interface RegisterPhoto {
  original_filename: string;
  declared_media_type: string;
  capture_surface_hint?: Surface | null;
}
export interface Photo extends RegisterPhoto {
  id: string;
  inspection_id: string;
  room_id: string;
  created_at: string;
  capture_surface_hint: Surface | null;
}
export interface Content {
  category: Category;
  surface: Surface;
  location: string;
  description: string;
  evidence_photo_ids: string[];
}
export interface Proposal extends Content {
  certainty: "clear" | "possible";
}
export interface Approved extends Content {
  reportable: boolean;
}
export type ReviewRequest =
  | { action: "confirm"; reportable: boolean }
  | ({
      action: "edit_and_confirm";
      reportable: boolean;
      evidence_photo_ids?: string[] | null;
    } & Omit<Content, "evidence_photo_ids">)
  | { action: "reject"; reason?: string | null };
export interface Finding {
  id: string;
  inspection_id: string;
  room_id: string;
  created_at: string;
  source_analysis_id: string;
  state: "pending_review" | "confirmed" | "rejected";
  original_proposal: Proposal;
  review: {
    action: ReviewRequest["action"];
    reviewed_at: string;
    approved: Approved | null;
    reason: string | null;
  } | null;
  eligible_for_report: boolean;
}
export interface Analysis {
  id: string;
  inspection_id: string;
  photo_id: string;
  created_at: string;
  analyzer_id: string;
  analyzer_version: string;
  status: "pending" | "succeeded" | "failed";
  outcome: "findings_present" | "no_visible_findings" | "uncertain" | null;
  completed_at: string | null;
  limitations: string[];
  failure_code: "unavailable" | "invalid_response" | "unreadable_image" | null;
  provenance: {
    requested_model: string | null;
    provider_model: string | null;
    prompt_version: string | null;
    schema_version: string | null;
    preparation_version: string | null;
  } | null;
}
export interface Inspection extends InspectionSummary {
  rooms: Room[];
  photos: Photo[];
  analyses: Analysis[];
  findings: Finding[];
}
export interface InspectionApi {
  list(): Promise<InspectionSummary[]>;
  get(id: string): Promise<Inspection>;
  create(body: CreateInspection): Promise<Inspection>;
  addRoom(id: string, name: string): Promise<Inspection>;
  registerPhoto(
    id: string,
    room: string,
    body: RegisterPhoto,
  ): Promise<Inspection>;
  analyze(id: string, photo: string): Promise<Inspection>;
  review(id: string, finding: string, body: ReviewRequest): Promise<Inspection>;
}
