import { useState } from "react";
import type { Finding, ReviewRequest, Category, Surface } from "../api/types";
import { categories, surfaces } from "../api/types";
export const human = (s: string) => s.replaceAll("_", " ");
export function Badge({ state }: { state: string }) {
  return <span className={`badge ${state}`}>{human(state)}</span>;
}
export function Evidence({ variant = "wall" }: { variant?: string }) {
  return (
    <div
      className={`evidence ${variant}`}
      role="img"
      aria-label="Illustrated example wall and floor, not an inspection photo"
    >
      <div className="window-art" />
      <div className="mark-art" />
      <span>ILLUSTRATED DEMO</span>
    </div>
  );
}
export function FindingCard({
  finding,
  evidenceUrl,
  onReview,
  busy,
}: {
  finding: Finding;
  evidenceUrl?: string;
  onReview: (body: ReviewRequest) => Promise<void>;
  busy: boolean;
}) {
  const p = finding.original_proposal;
  const [mode, setMode] = useState<
    "confirm" | "edit_and_confirm" | "reject" | null
  >(null);
  const [choice, setChoice] = useState("");
  const [description, setDescription] = useState(p.description);
  const [location, setLocation] = useState(p.location);
  const [category, setCategory] = useState<Category>(p.category);
  const [surface, setSurface] = useState<Surface>(p.surface);
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  async function submit(e: React.SubmitEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!mode) return;
    if (mode !== "reject" && !choice) {
      setError("Choose Yes or No before confirming.");
      return;
    }
    if (
      mode === "edit_and_confirm" &&
      (!description.trim() || !location.trim())
    ) {
      setError("Enter a location and description.");
      return;
    }
    setError("");
    const body: ReviewRequest =
      mode === "reject"
        ? { action: mode, reason: reason || null }
        : mode === "confirm"
          ? { action: mode, reportable: choice === "yes" }
          : {
              action: mode,
              reportable: choice === "yes",
              category,
              surface,
              location: location.trim(),
              description: description.trim(),
            };
    try {
      await onReview(body);
      setMode(null);
    } catch {
      setError("Unable to save your review. Please try again.");
    }
  }
  return (
    <article className="finding card">
      <div className="finding-image">
        {evidenceUrl ? (
          <img
            className="evidence photo-evidence"
            src={evidenceUrl}
            alt="Original finding evidence"
          />
        ) : (
          <Evidence />
        )}
        <p className="caption">Original evidence · linked room photo</p>
      </div>
      <div className="finding-content">
        <div className="row">
          <span className="eyebrow">AI suggestion</span>
          <Badge state={finding.state} />
        </div>
        <h3>
          {human(p.category)} on {p.surface}
        </h3>
        <p>{p.description}</p>
        <div className="metadata">
          <span>↳ {p.location}</span>
          <span>Visibility: {p.certainty}</span>
        </div>
        {finding.review?.approved && (
          <section className="approved">
            <span className="eyebrow">Your approved content</span>
            <h4>
              {human(finding.review.approved.category)} on{" "}
              {finding.review.approved.surface}
            </h4>
            <p>{finding.review.approved.description}</p>
            <p>{finding.review.approved.location}</p>
            <strong>
              {finding.eligible_for_report
                ? "Included in future report"
                : "Confirmed · not included in future report"}
            </strong>
          </section>
        )}
        {finding.state === "rejected" && (
          <p className="review-note">
            You rejected this suggestion.
            {finding.review?.reason && ` Reason: ${finding.review.reason}`}
          </p>
        )}
        {finding.state === "pending_review" && !mode && (
          <div className="actions">
            <button onClick={() => setMode("confirm")}>Confirm</button>
            <button
              className="secondary"
              onClick={() => setMode("edit_and_confirm")}
            >
              Edit
            </button>
            <button className="quiet danger" onClick={() => setMode("reject")}>
              Reject
            </button>
          </div>
        )}
        {mode && (
          <form className="review-form" onSubmit={submit}>
            <h4>
              {mode === "edit_and_confirm"
                ? "Edit & confirm"
                : mode === "reject"
                  ? "Reject suggestion"
                  : "Confirm observation"}
            </h4>
            {mode === "edit_and_confirm" && (
              <>
                <div className="form-grid">
                  <label>
                    Category
                    <select
                      value={category}
                      onChange={(e) => setCategory(e.target.value as Category)}
                    >
                      {categories.map((c) => (
                        <option key={c} value={c}>
                          {human(c)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Surface
                    <select
                      value={surface}
                      onChange={(e) => setSurface(e.target.value as Surface)}
                    >
                      {surfaces.map((s) => (
                        <option key={s}>{s}</option>
                      ))}
                    </select>
                  </label>
                </div>
                <label>
                  Location
                  <input
                    required
                    value={location}
                    onChange={(e) => setLocation(e.target.value)}
                  />
                </label>
                <label>
                  Description
                  <textarea
                    required
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                  />
                </label>
                <p className="caption">
                  Original AI suggestion and source photo are retained.
                </p>
              </>
            )}
            {mode === "reject" ? (
              <label>
                Reason (optional)
                <input
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                />
              </label>
            ) : (
              <fieldset>
                <legend>Include in future report?</legend>
                <p className="caption">
                  A visible mark can be real without being significant. You
                  decide.
                </p>
                <div className="choices">
                  {["yes", "no"].map((v) => (
                    <label key={v}>
                      <input
                        type="radio"
                        name={`report-${finding.id}`}
                        value={v}
                        checked={choice === v}
                        onChange={() => setChoice(v)}
                      />
                      {v === "yes" ? "Yes, include it" : "No, keep it out"}
                    </label>
                  ))}
                </div>
              </fieldset>
            )}
            {error && (
              <p role="alert" className="error">
                {error}
              </p>
            )}
            <div className="actions">
              <button
                disabled={busy}
                className={mode === "reject" ? "destructive" : ""}
              >
                {busy
                  ? "Saving…"
                  : mode === "reject"
                    ? "Reject suggestion"
                    : "Save review"}
              </button>
              <button
                type="button"
                className="quiet"
                disabled={busy}
                onClick={() => {
                  setMode(null);
                  setError("");
                }}
              >
                Cancel
              </button>
            </div>
          </form>
        )}
      </div>
    </article>
  );
}
