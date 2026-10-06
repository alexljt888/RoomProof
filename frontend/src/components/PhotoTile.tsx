import { useState } from "react";
import type { Analysis, Photo, PhotoContentApi } from "../api/types";
import { Badge } from "./FindingCard";
export function PhotoTile({
  photo,
  index,
  content,
  analysis,
  busy,
  uploading,
  analyzing,
  onAnalyze,
  onReview,
  onRetryUpload,
}: {
  photo: Photo;
  index: number;
  content: PhotoContentApi;
  analysis?: Analysis;
  busy: boolean;
  uploading: boolean;
  analyzing: boolean;
  onAnalyze: () => void;
  onReview: () => void;
  onRetryUpload: () => void;
}) {
  const [availability, setAvailability] = useState<
    "loading" | "ready" | "missing"
  >("loading");
  const status = uploading
    ? "uploading"
    : analyzing
      ? "pending"
      : (analysis?.status ?? availability);
  return (
    <article className="card photo-card">
      {uploading ? (
        <div
          className="evidence photo-evidence"
          aria-label="Photo upload in progress"
        />
      ) : (
        <img
          className="evidence photo-evidence"
          src={content.contentUrl(photo.inspection_id, photo.id)}
          alt={`Room evidence ${index + 1}`}
          onLoad={() => setAvailability("ready")}
          onError={() => setAvailability("missing")}
        />
      )}
      <div className="photo-body">
        <div className="row">
          <h3>Room detail {index + 1}</h3>
          <Badge state={status} />
        </div>
        <p className="caption" role="status">
          {uploading
            ? "Uploading photo…"
            : availability === "missing"
              ? "Content unavailable. Choose the file again to retry upload."
              : status === "pending"
                ? "Analysis in progress. No automatic retry."
                : analysis?.status === "failed"
                  ? `Analysis failed: ${analysis.failure_code}. Retry only when you choose.`
                  : analysis?.status === "succeeded"
                    ? `Outcome: ${analysis.outcome?.replaceAll("_", " ")}`
                    : availability === "loading"
                      ? "Loading uploaded evidence…"
                      : "Photo ready for analysis."}
        </p>
        {analysis?.analyzer_id === "fake" && (
          <p className="caption">Fake analysis · no AI inspected this image.</p>
        )}
        {analysis?.limitations.map((text, i) => (
          <p className="caption" key={i}>
            {text}
          </p>
        ))}
        {availability === "missing" && !uploading ? (
          <button className="secondary" disabled={busy} onClick={onRetryUpload}>
            Choose photo to retry upload
          </button>
        ) : analysis?.status === "succeeded" ? (
          <button className="secondary" onClick={onReview}>
            Review suggestions →
          </button>
        ) : (
          <button
            disabled={
              busy ||
              uploading ||
              availability !== "ready" ||
              status === "pending"
            }
            onClick={onAnalyze}
          >
            {status === "pending"
              ? "Analyzing…"
              : analysis?.status === "failed"
                ? "Retry analysis"
                : "Analyze photo"}
          </button>
        )}
      </div>
    </article>
  );
}
