import { useEffect, useRef, useState } from "react";
import type { InspectionApi, InspectionReport } from "../api/types";

export default function ReportView({
  api,
  inspectionId,
}: {
  api: InspectionApi;
  inspectionId: string;
}) {
  const [report, setReport] = useState<InspectionReport>();
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState(false);
  const downloading = useRef(false);
  useEffect(() => {
    let active = true;
    api.reports
      ?.preview(inspectionId)
      .then((value) => {
        if (active) setReport(value);
      })
      .catch(() => {
        if (active)
          setError(
            "Unable to load report preview. Check the backend connection.",
          );
      });
    return () => {
      active = false;
    };
  }, [api, inspectionId, revision]);
  async function download() {
    if (!api.reports || downloading.current) return;
    downloading.current = true;
    setBusy(true);
    setError("");
    try {
      const blob = await api.reports.download(inspectionId);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "roomproof-inspection.pdf";
      document.body.append(link);
      link.click();
      link.remove();
      // Allow the browser to consume the download URL before releasing it.
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to download PDF.");
    } finally {
      downloading.current = false;
      setBusy(false);
    }
  }
  if (!api.reports)
    return (
      <div className="card report-card">
        <h3>Reports use the local backend</h3>
        <p>
          Switch from illustrated demo mode to the HTTP workflow to preview and
          export a report.
        </p>
      </div>
    );
  return (
    <div className="report-preview">
      <div className="row">
        <h3>Report preview</h3>
        <button
          onClick={() => {
            setReport(undefined);
            setError("");
            setRevision((v) => v + 1);
          }}
          disabled={busy}
        >
          Refresh preview
        </button>
      </div>
      {error && <p role="alert">{error}</p>}
      {!report ? (
        !error && <p role="status">Loading report…</p>
      ) : (
        <>
          <p className="caption">
            Approved human content only. Local storage is transient; save your
            downloaded copy.
          </p>
          {!report.review_complete && (
            <p role="alert">
              Review incomplete: {report.pending_findings} pending suggestions
              and {report.pending_analyses} active analyses. PDF export is
              blocked.
            </p>
          )}
          {report.photos_needing_analysis > 0 && (
            <p role="alert">
              {report.photos_needing_analysis}{" "}
              {report.photos_needing_analysis === 1
                ? "photo still needs"
                : "photos still need"}{" "}
              successful analysis before the final PDF can be downloaded.
              Analyze unprocessed photos or retry failed analyses.
            </p>
          )}
          {report.unavailable_evidence > 0 && (
            <p role="alert">
              Approved evidence is unavailable for {report.unavailable_evidence}{" "}
              photos. PDF export is blocked.
            </p>
          )}
          <div className="card report-card">
            <h3>{report.address}</h3>
            <p>
              {report.unit && `Unit ${report.unit} · `}
              {report.renter}
            </p>
            <p>
              {report.room_count} rooms · {report.finding_count} confirmed
              reportable findings
            </p>
            <p>
              {report.unanalysed_photos} photos without analysis ·{" "}
              {report.failed_analyses} failed analysis attempts
            </p>
            <p className="caption">
              Review completion does not establish complete inspection coverage
              or a damage-free property. The backend rechecks review and
              evidence on every export.
            </p>
            <button
              className="primary"
              disabled={!report.export_ready || busy}
              onClick={() => void download()}
            >
              {busy ? "Preparing PDF…" : "Download PDF"}
            </button>
          </div>
          {!report.finding_count && (
            <div className="card report-card">
              <h3>No confirmed reportable findings</h3>
              <p>
                A zero-findings report is available once analysis, review, and
                evidence checks are complete. This does not certify absence of
                damage.
              </p>
            </div>
          )}
          {report.rooms.map((room) => (
            <section className="report-room" key={room.id}>
              <h3>{room.name}</h3>
              {room.findings.map((f) => (
                <article className="card report-card" key={f.id}>
                  <h4>
                    {f.category.replaceAll("_", " ")} on {f.surface}
                  </h4>
                  <p>{f.location}</p>
                  <p>{f.description}</p>
                  {f.evidence_photo_ids.map((pid) => (
                    <ReportEvidence
                      key={pid}
                      url={api.content?.contentUrl(inspectionId, pid)}
                    />
                  ))}
                </article>
              ))}
            </section>
          ))}
        </>
      )}
    </div>
  );
}
function ReportEvidence({ url }: { url?: string }) {
  const [failed, setFailed] = useState(false);
  if (!url || failed)
    return (
      <p role="status">
        Evidence could not be displayed. Export requires the backend to resolve
        all approved evidence.
      </p>
    );
  return (
    <img
      src={url}
      alt="Approved report evidence"
      onError={() => setFailed(true)}
      style={{ maxWidth: "100%", maxHeight: 280, objectFit: "contain" }}
    />
  );
}
