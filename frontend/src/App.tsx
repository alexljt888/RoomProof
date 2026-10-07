import { useEffect, useRef, useState } from "react";
import { Link, Route, Routes, useNavigate, useParams } from "react-router";
import type { InspectionApi, Inspection, InspectionSummary } from "./api/types";
import { PhotoTile } from "./components/PhotoTile";
import { Badge, Evidence, FindingCard } from "./components/FindingCard";
function ErrorMessage({ message }: { message: string }) {
  return message ? (
    <p className="error" role="alert">
      {message}
    </p>
  ) : null;
}
function Home({ api }: { api: InspectionApi }) {
  const [items, setItems] = useState<InspectionSummary[]>([]);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    api
      .list()
      .then((v) => {
        if (active) setItems(v);
      })
      .catch(() => {
        if (active) setError("Unable to load inspections.");
      });
    return () => {
      active = false;
    };
  }, [api]);
  return (
    <>
      <section className="hero">
        <div>
          <span className="eyebrow">A confident start to your next home</span>
          <h1>
            Your space.
            <br />
            Your record.
            <br />
            <em>Your peace of mind.</em>
          </h1>
          <p>
            Document the little things before you settle in.
            <br />
            RoomProof helps you organize what you see.
          </p>
          <Link className="button" to="/new">
            Start inspection <span>→</span>
          </Link>
          <div className="trust">✓ AI suggests. You verify.</div>
        </div>
        <div className="hero-visual">
          <Evidence />
          <div className="floating card">
            <span className="check-icon">✓</span>
            <div>
              <strong>Every detail, in your hands.</strong>
              <p>You make the final call.</p>
            </div>
          </div>
          <span className="visual-label">01 / A fresh start</span>
        </div>
      </section>
      <section>
        <div className="section-heading">
          <div>
            <span className="eyebrow">Pick up where you left off</span>
            <h2>Your inspections</h2>
          </div>
          <span className="caption">
            {api.mode === "http"
              ? "Local backend · resets on server restart"
              : "Demo session · resets on refresh"}
          </span>
        </div>
        <ErrorMessage message={error} />
        <div className="inspection-grid">
          {items.map((i) => (
            <Link
              className="card inspection-card"
              key={i.id}
              to={`/inspections/${i.id}`}
            >
              <span className="house-icon">⌂</span>
              <div>
                <h3>{i.property_details.address}</h3>
                <p>
                  {i.property_details.unit
                    ? `Unit ${i.property_details.unit} · `
                    : ""}
                  {i.renter_name}
                </p>
                <span className="text-link">Open inspection →</span>
              </div>
            </Link>
          ))}
        </div>
      </section>
      <div className="steps-strip">
        <span>
          <b>01</b> Add your rooms
        </span>
        <span>
          <b>02</b> Document each space
        </span>
        <span>
          <b>03</b> Review every suggestion
        </span>
      </div>
    </>
  );
}
function NewInspection({ api }: { api: InspectionApi }) {
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(e: React.SubmitEvent<HTMLFormElement>) {
    e.preventDefault();
    const values = new FormData(e.currentTarget);
    const renter = String(values.get("renter")).trim(),
      address = String(values.get("address")).trim();
    if (!renter || !address) {
      setError("Enter your name and property address.");
      return;
    }
    setBusy(true);
    try {
      const state = await api.create({
        renter_name: renter,
        property_details: {
          address,
          unit: String(values.get("unit")).trim() || null,
        },
      });
      navigate(`/inspections/${state.id}`);
    } catch {
      setError("Unable to create inspection. Please try again.");
      setBusy(false);
    }
  }
  return (
    <div className="narrow">
      <Link className="back" to="/">
        ← Your inspections
      </Link>
      <span className="eyebrow">A new beginning</span>
      <h1>Let’s make it yours.</h1>
      <p>Start with the basics. Then we’ll take it one room at a time.</p>
      <form className="card start-form" onSubmit={submit}>
        <label>
          Renter name
          <input
            name="renter"
            autoComplete="name"
            required
            placeholder="Your full name"
          />
        </label>
        <label>
          Property address
          <input
            name="address"
            autoComplete="street-address"
            required
            placeholder="Street address"
          />
        </label>
        <label>
          Unit (optional)
          <input name="unit" placeholder="Apartment or unit number" />
        </label>
        <p className="caption">
          {api.mode === "http"
            ? "Local development only. Entries are lost when the backend restarts."
            : "Demo only. Entries disappear on refresh."}
        </p>
        <ErrorMessage message={error} />
        <button disabled={busy}>
          {busy ? "Creating…" : "Create inspection →"}
        </button>
      </form>
    </div>
  );
}
function Workspace({ api }: { api: InspectionApi }) {
  const { inspectionId } = useParams();
  const [state, setState] = useState<Inspection | null>(null);
  const [room, setRoom] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState<"photos" | "review" | "summary">("photos");
  const [adding, setAdding] = useState(false);
  const [roomName, setRoomName] = useState("");
  const [analyzing, setAnalyzing] = useState("");
  const mutationInFlight = useRef(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const retryPhoto = useRef<string | null>(null);
  const [uploading, setUploading] = useState("");
  const [contentVersion, setContentVersion] = useState(0);
  const [needsRefresh, setNeedsRefresh] = useState(false);
  async function selectFile(file?: File) {
    if (!file || !state || !api.content || mutationInFlight.current) return;
    if (!["image/jpeg", "image/png"].includes(file.type)) {
      setError(
        "RoomProof currently accepts JPEG/PNG only. HEIC is not supported.",
      );
      return;
    }
    if (file.size > 20971520) {
      setError("Choose an image no larger than 20 MiB.");
      return;
    }
    mutationInFlight.current = true;
    setBusy(true);
    setError("");
    let pid = retryPhoto.current;
    try {
      if (!pid) {
        const next = await api.registerPhoto(state.id, room, {
          original_filename: file.name,
          declared_media_type: file.type,
        });
        // The backend appends this Photo under its repository lock and returns
        // that detached, insertion-ordered snapshot. A stale UI set difference
        // may include OTHER clients' earlier registrations; never select those.
        const registered = next.photos.at(-1);
        if (
          !registered ||
          registered.room_id !== room ||
          registered.inspection_id !== state.id ||
          state.photos.some((p) => p.id === registered.id)
        ) {
          throw new Error("Photo registration could not be identified safely.");
        }
        pid = registered.id;
        setState(next);
      }
      setTab("photos");
      setUploading(pid);
      await api.content.upload(state.id, pid, file);
      setState(await api.get(state.id));
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Photo upload failed. Choose the file again to retry.",
      );
    } finally {
      setUploading("");
      setContentVersion((v) => v + 1);
      setBusy(false);
      mutationInFlight.current = false;
      retryPhoto.current = null;
    }
  }
  async function analyzePhoto(pid: string) {
    if (!state || mutationInFlight.current || needsRefresh) return;
    mutationInFlight.current = true;
    setBusy(true);
    setAnalyzing(pid);
    setError("");
    try {
      const next = await api.analyze(state.id, pid);
      setState(next);
      if (
        next.analyses.filter((a) => a.photo_id === pid).at(-1)?.status ===
        "failed"
      ) {
        setState(await api.get(state.id));
        setError(
          "Analysis failed. State refreshed; no automatic retry was made.",
        );
      }
    } catch {
      try {
        setState(await api.get(state.id));
        setError(
          "Analysis did not complete normally. State refreshed; check its status before retrying.",
        );
      } catch {
        setNeedsRefresh(true);
        setError(
          "Analysis status is unknown. Refresh state before another attempt.",
        );
      }
    } finally {
      mutationInFlight.current = false;
      setBusy(false);
      setAnalyzing("");
    }
  }
  useEffect(() => {
    let active = true;
    api
      .get(inspectionId!)
      .then((v) => {
        if (active) {
          setState(v);
          setRoom(v.rooms[0]?.id ?? "");
        }
      })
      .catch(() => {
        if (active)
          setError(
            "Inspection not found. Return to your inspections to start again.",
          );
      });
    return () => {
      active = false;
    };
  }, [api, inspectionId]);
  async function update(action: () => Promise<Inspection>) {
    if (mutationInFlight.current) return;
    mutationInFlight.current = true;
    setBusy(true);
    setError("");
    try {
      setState(await action());
    } catch {
      setError("This action could not be completed. Please try again.");
    } finally {
      mutationInFlight.current = false;
      setBusy(false);
    }
  }
  if (!state)
    return (
      <>
        <Link to="/">← Your inspections</Link>
        {error ? (
          <ErrorMessage message={error} />
        ) : (
          <p role="status">Loading inspection…</p>
        )}
      </>
    );
  const current = state.rooms.find((r) => r.id === room);
  const photos = state.photos.filter((p) => p.room_id === room),
    findings = state.findings.filter((f) => f.room_id === room);
  const pending = state.findings.filter(
    (f) => f.state === "pending_review",
  ).length;
  const reviewed = state.findings.length - pending;
  const counts = [
    ["Pending review", pending],
    [
      "Confirmed · reportable",
      state.findings.filter(
        (f) => f.state === "confirmed" && f.eligible_for_report,
      ).length,
    ],
    [
      "Confirmed · not reportable",
      state.findings.filter(
        (f) => f.state === "confirmed" && !f.eligible_for_report,
      ).length,
    ],
    ["Rejected", state.findings.filter((f) => f.state === "rejected").length],
  ] as const;
  return (
    <>
      <Link className="back" to="/">
        ← Your inspections
      </Link>
      <div className="workspace-heading">
        <div>
          <span className="eyebrow">Move-in inspection</span>
          <h1>{state.property_details.address}</h1>
          <p>
            {state.property_details.unit
              ? `Unit ${state.property_details.unit} · `
              : ""}
            {state.renter_name}
          </p>
        </div>
        <div className="progress-card">
          <strong>
            {reviewed} of {state.findings.length} suggestions reviewed
          </strong>
          <progress value={reviewed} max={state.findings.length || 1} />
          <span className="caption">AI suggests. You verify.</span>
        </div>
      </div>
      <ErrorMessage message={error} />
      {needsRefresh && (
        <button
          disabled={busy}
          onClick={() =>
            void update(async () => {
              const next = await api.get(state.id);
              setNeedsRefresh(false);
              return next;
            })
          }
        >
          Refresh analysis state
        </button>
      )}
      <input
        ref={fileInput}
        type="file"
        accept="image/jpeg,image/png"
        hidden
        aria-label="Choose room photo"
        onChange={(e) => {
          const file = e.target.files?.[0];
          e.target.value = "";
          void selectFile(file);
        }}
      />
      <div className="workspace">
        <aside>
          <div className="row">
            <h2>Rooms</h2>
            <span className="count">{state.rooms.length}</span>
          </div>
          <nav aria-label="Rooms">
            {state.rooms.map((r) => (
              <button
                className={`room-button ${room === r.id ? "selected" : ""}`}
                key={r.id}
                onClick={() => {
                  setRoom(r.id);
                  setTab("photos");
                }}
                aria-pressed={room === r.id}
              >
                <span>⌑ {r.name}</span>
                <span>→</span>
              </button>
            ))}
          </nav>
          <button className="quiet add-room" onClick={() => setAdding(!adding)}>
            + Add room
          </button>
          {adding && (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                if (!roomName.trim()) return;
                void update(async () => {
                  const v = await api.addRoom(state.id, roomName.trim());
                  setRoom(v.rooms.at(-1)!.id);
                  setTab("photos");
                  setAdding(false);
                  setRoomName("");
                  return v;
                });
              }}
            >
              <label>
                Room name
                <input
                  required
                  value={roomName}
                  onChange={(e) => setRoomName(e.target.value)}
                />
              </label>
              <button disabled={busy}>Add room</button>
            </form>
          )}
          <div className="aside-note">
            A little care now.
            <br />
            <strong>A clearer record later.</strong>
            <p>Check walls, floors, doors, trim, and countertops.</p>
          </div>
        </aside>
        <section className="room-content">
          <div className="section-heading">
            <div>
              <span className="eyebrow">One room at a time</span>
              <h2>{current?.name ?? "Add your first room"}</h2>
            </div>
            {current && (
              <button
                className="secondary"
                disabled={busy}
                onClick={() => {
                  if (api.content) {
                    retryPhoto.current = null;
                    fileInput.current?.click();
                    return;
                  }
                  void update(async () => {
                    const next = await api.registerPhoto(state.id, room, {
                      original_filename: "illustrated-demo.png",
                      declared_media_type: "image/png",
                    });
                    setTab("photos");
                    return next;
                  });
                }}
              >
                {api.content ? "+ Add Photo" : "+ Add demo photo"}
              </button>
            )}
          </div>
          <div className="tabs" aria-label="Workspace views">
            {(["photos", "review", "summary"] as const).map((t) => (
              <button
                key={t}
                aria-pressed={tab === t}
                className={tab === t ? "active" : ""}
                onClick={() => setTab(t)}
              >
                {t === "photos"
                  ? "Photos"
                  : t === "review"
                    ? `Review (${findings.filter((f) => f.state === "pending_review").length})`
                    : "Inspection summary"}
              </button>
            ))}
          </div>
          {tab === "photos" && (
            <>
              <p className="caption">
                {api.content
                  ? "AI suggests. You verify. Review every suggestion before confirming."
                  : "Illustrated examples only. No uploads or AI in this demo."}
              </p>
              {!photos.length ? (
                <div className="empty card">
                  <span>▧</span>
                  <h3>A fresh canvas.</h3>
                  <p>
                    {current
                      ? api.content
                        ? "Add a JPEG/PNG photo to document this room."
                        : "Add a demo photo to explore the review experience."
                      : "Create a room to begin documenting your space."}
                  </p>
                </div>
              ) : (
                <div className="photo-grid">
                  {photos.map((p, index) => {
                    const a = state.analyses
                      .filter((a) => a.photo_id === p.id)
                      .at(-1);
                    if (api.content)
                      return (
                        <PhotoTile
                          key={`${p.id}-${contentVersion}`}
                          photo={p}
                          index={index}
                          content={api.content}
                          analysis={a}
                          busy={busy || needsRefresh}
                          uploading={uploading === p.id}
                          analyzing={analyzing === p.id}
                          onAnalyze={() => void analyzePhoto(p.id)}
                          onReview={() => setTab("review")}
                          onRetryUpload={() => {
                            retryPhoto.current = p.id;
                            fileInput.current?.click();
                          }}
                        />
                      );
                    const status =
                      analyzing === p.id ? "pending" : (a?.status ?? "ready");
                    return (
                      <article className="card photo-card" key={p.id}>
                        <Evidence variant={index % 2 ? "floor" : "wall"} />
                        <div className="photo-body">
                          <div className="row">
                            <h3>Room detail {index + 1}</h3>
                            <Badge state={status} />
                          </div>
                          <p className="caption">
                            {status === "pending"
                              ? "Analyzing example · static demo state"
                              : status === "failed"
                                ? "Example analysis unavailable"
                                : status === "succeeded"
                                  ? "Suggestion ready for your review"
                                  : "Ready for demo analysis"}
                          </p>
                          {status === "succeeded" ? (
                            <button
                              className="secondary"
                              onClick={() => setTab("review")}
                            >
                              Review suggestions →
                            </button>
                          ) : (
                            <button
                              disabled={busy || status === "pending"}
                              onClick={() => {
                                void analyzePhoto(p.id);
                              }}
                            >
                              {status === "pending"
                                ? "Analyzing…"
                                : status === "failed"
                                  ? "Retry demo analysis"
                                  : "Analyze demo photo"}
                            </button>
                          )}
                        </div>
                      </article>
                    );
                  })}
                </div>
              )}
            </>
          )}
          {tab === "review" && (
            <>
              <div className="review-banner">
                ✧{" "}
                <div>
                  <strong>Your judgment makes the difference.</strong>
                  <p>
                    Check each suggestion against its evidence. Confirm what
                    matters, correct what doesn’t.
                  </p>
                </div>
              </div>
              {findings.length ? (
                findings.map((f) => (
                  <FindingCard
                    key={f.id}
                    finding={f}
                    evidenceUrl={api.content?.contentUrl(
                      state.id,
                      f.original_proposal.evidence_photo_ids[0],
                    )}
                    busy={busy}
                    onReview={async (body) => {
                      if (mutationInFlight.current)
                        throw new Error("Operation in progress");
                      mutationInFlight.current = true;
                      setBusy(true);
                      try {
                        setState(await api.review(state.id, f.id, body));
                      } finally {
                        mutationInFlight.current = false;
                        setBusy(false);
                      }
                    }}
                  />
                ))
              ) : (
                <div className="empty card">
                  <h3>No suggestions yet.</h3>
                  <p>Analyze a demo photo to see a finding here.</p>
                </div>
              )}
            </>
          )}
          {tab === "summary" && (
            <>
              <h3>Your review, at a glance</h3>
              <div className="summary-grid">
                {counts.map(([label, n]) => (
                  <div className="card metric" key={label}>
                    <strong>{n}</strong>
                    <span>{label}</span>
                  </div>
                ))}
              </div>
              <div className="card summary-note">
                <h3>
                  {pending
                    ? "A few details still need you."
                    : "You’re all caught up."}
                </h3>
                <p>
                  {pending
                    ? "Review the remaining suggestions in each room."
                    : "All current suggestions have been reviewed. You can continue documenting other rooms."}
                </p>
                <p className="caption">
                  This is a review summary, not a final report. Report
                  generation is planned for a later milestone.
                </p>
              </div>
            </>
          )}
        </section>
      </div>
    </>
  );
}
export default function App({ api }: { api: InspectionApi }) {
  return (
    <>
      <header>
        <Link className="brand" to="/">
          <span className="brand-mark">⌂</span>RoomProof
          <span className="brand-dot">.</span>
        </Link>
        <div className="header-right">
          <span className="demo-pill">
            {api.mode === "http" ? "Local workspace" : "Demo workspace"}
          </span>
          <span className="avatar" aria-label="Demo user">
            RP
          </span>
        </div>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<Home api={api} />} />
          <Route path="/new" element={<NewInspection api={api} />} />
          <Route
            path="/inspections/:inspectionId"
            element={<Workspace api={api} />}
          />
          <Route
            path="*"
            element={
              <div className="empty">
                <h1>Page not found</h1>
                <Link to="/">Return to inspections</Link>
              </div>
            }
          />
        </Routes>
      </main>
      <footer>
        <strong>RoomProof</strong>
        <span>A clearer record. A calmer move.</span>
        <span>
          {api.mode === "http"
            ? "Local development · human review required"
            : "Demo · no real analysis or uploads"}
        </span>
      </footer>
    </>
  );
}
