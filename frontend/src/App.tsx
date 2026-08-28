import { startTransition, useEffect, useMemo, useState } from "react";
import {
  fetchLeadFilterOptions,
  fetchLeads,
  runCrm,
  submitHumanDecision,
  type CrmAction,
  type CrmBatchRunResponse,
  type CrmRunResponse,
  type HumanDecision,
  type LeadFilters,
  type LeadProfile,
} from "./api";

const ACTIONS: { id: CrmAction; label: string; blurb: string }[] = [
  {
    id: "outreach",
    label: "Outreach",
    blurb: "Qualify, draft, critique — you approve before send",
  },
  {
    id: "update",
    label: "Update",
    blurb: "RAG churn analysis — multi-select OK",
  },
  {
    id: "summarize",
    label: "Summarize",
    blurb: "Profile + chat briefing — one lead only",
  },
];

function allowsMulti(action: CrmAction) {
  return action === "outreach" || action === "update";
}

const EMPTY_FILTERS: LeadFilters = {
  game_genre_preference: [],
  status: [],
  churn_risk_level: [],
};

export default function App() {
  const [action, setAction] = useState<CrmAction>("outreach");
  const [filterOptions, setFilterOptions] = useState<LeadFilters>(EMPTY_FILTERS);
  const [filterId, setFilterId] = useState("");
  const [filterEmail, setFilterEmail] = useState("");
  const [filterGenre, setFilterGenre] = useState("");
  const [filterStatus, setFilterStatus] = useState("");
  const [filterChurn, setFilterChurn] = useState("");
  const [leadCatalog, setLeadCatalog] = useState<LeadProfile[]>([]);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [batch, setBatch] = useState<CrmBatchRunResponse | null>(null);
  const [loadingLeads, setLoadingLeads] = useState(false);
  const [running, setRunning] = useState(false);
  const [decidingThread, setDecidingThread] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const multi = allowsMulti(action);

  useEffect(() => {
    document.title = "Agentic CRM";
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function loadOptions() {
      try {
        const options = await fetchLeadFilterOptions();
        if (!cancelled) setFilterOptions(options);
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof Error ? err.message : "Failed to load filter options",
          );
        }
      }
    }
    void loadOptions();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const hasFilter = Boolean(
      filterId.trim() ||
        filterEmail.trim() ||
        filterGenre ||
        filterStatus ||
        filterChurn,
    );

    if (!hasFilter) {
      setLeadCatalog([]);
      setSelectedIds([]);
      setLoadingLeads(false);
      return;
    }

    const handle = window.setTimeout(async () => {
      setLoadingLeads(true);
      setError(null);
      try {
        const rows = await fetchLeads({
          limit: 200,
          id: filterId || undefined,
          email: filterEmail || undefined,
          game_genre_preference: filterGenre || undefined,
          status: filterStatus || undefined,
          churn_risk_level: filterChurn || undefined,
        });
        if (cancelled) return;
        startTransition(() => {
          setLeadCatalog(rows);
          setSelectedIds((prev) => {
            const visible = new Set(rows.map((r) => r.id));
            const kept = prev.filter((id) => visible.has(id));
            if (!allowsMulti(action)) {
              if (kept.length > 0) return [kept[0]];
              return [];
            }
            return kept;
          });
        });
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load leads");
        }
      } finally {
        if (!cancelled) setLoadingLeads(false);
      }
    }, 200);

    return () => {
      cancelled = true;
      window.clearTimeout(handle);
    };
  }, [filterId, filterEmail, filterGenre, filterStatus, filterChurn, action]);

  const selectedLeads = useMemo(
    () => leadCatalog.filter((l) => selectedIds.includes(l.id)),
    [leadCatalog, selectedIds],
  );

  function toggleLead(id: string) {
    if (!multi) {
      setSelectedIds([id]);
      return;
    }
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );
  }

  function selectAllShown() {
    if (!multi) return;
    setSelectedIds(leadCatalog.map((l) => l.id));
  }

  function clearSelection() {
    setSelectedIds([]);
  }

  const allShownSelected =
    multi &&
    leadCatalog.length > 0 &&
    leadCatalog.every((l) => selectedIds.includes(l.id));

  function onActionChange(next: CrmAction) {
    setAction(next);
    setBatch(null);
    setError(null);
    if (!allowsMulti(next)) {
      setSelectedIds((prev) => (prev[0] ? [prev[0]] : []));
    }
  }

  async function onRun() {
    setError(null);
    setRunning(true);
    setBatch(null);
    try {
      const ids = selectedIds;
      if (ids.length === 0) {
        throw new Error(
          multi
            ? "Select at least one lead for outreach/update."
            : "Select one lead for summarize.",
        );
      }
      if (!multi && ids.length !== 1) {
        throw new Error("Summarize accepts exactly one lead.");
      }

      const response = await runCrm(ids, action);
      startTransition(() => setBatch(response));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Pipeline failed");
    } finally {
      setRunning(false);
    }
  }

  async function onHumanDecision(threadId: string, decision: HumanDecision) {
    setError(null);
    setDecidingThread(threadId);
    try {
      const updated = await submitHumanDecision(threadId, decision);
      startTransition(() => {
        setBatch((prev) => {
          if (!prev) return prev;
          const results = prev.results.map((r) =>
            r.thread_id === threadId ? updated : r,
          );
          return {
            ...prev,
            results,
            pending_approvals: results.filter((r) => r.awaiting_human_approval)
              .length,
          };
        });
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Decision failed");
    } finally {
      setDecidingThread(null);
    }
  }

  return (
    <div className="relative min-h-screen overflow-x-hidden text-ink">
      {/* Atmospheric stage */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            "radial-gradient(ellipse 90% 70% at 0% -10%, #fb7185 0%, transparent 50%), radial-gradient(ellipse 80% 60% at 100% 0%, #22d3ee 0%, transparent 48%), radial-gradient(ellipse 70% 50% at 50% 100%, #fbbf24 0%, transparent 55%), linear-gradient(165deg, #082f49 0%, #0f766e 42%, #134e4a 100%)",
        }}
      />
      <div
        aria-hidden
        className="blob pointer-events-none absolute -left-24 top-10 size-[28rem] rounded-full opacity-40 blur-3xl"
        style={{
          background: "radial-gradient(circle, #fb7185 0%, transparent 70%)",
        }}
      />
      <div
        aria-hidden
        className="blob-delay pointer-events-none absolute -right-16 top-40 size-[26rem] rounded-full opacity-35 blur-3xl"
        style={{
          background: "radial-gradient(circle, #22d3ee 0%, transparent 70%)",
        }}
      />
      <div
        aria-hidden
        className="blob-delay-2 pointer-events-none absolute bottom-10 left-1/3 size-[22rem] rounded-full opacity-30 blur-3xl"
        style={{
          background: "radial-gradient(circle, #fbbf24 0%, transparent 70%)",
        }}
      />
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-[0.14]"
        style={{
          backgroundImage:
            "url(\"data:image/svg+xml,%3Csvg width='72' height='72' viewBox='0 0 72 72' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='none' fill-rule='evenodd'%3E%3Cg fill='%23ffffff' fill-opacity='0.55'%3E%3Cpath d='M36 34v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zm0-30V0h-2v4h-4v2h4v4h2V6h4V4h-4zM6 34v-4H4v4H0v2h4v4h2v-4h4v-2H6zM6 4V0H4v4H0v2h4v4h2V6h4V4H6z'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E\")",
        }}
      />

      <main className="relative mx-auto flex min-h-screen max-w-5xl flex-col px-5 py-10 sm:px-8 sm:py-14">
        <header className="anim-rise mb-10 sm:mb-14">
          <p className="mb-3 inline-block bg-gradient-to-r from-amber via-cyan to-coral bg-clip-text text-xs font-bold uppercase tracking-[0.28em] text-transparent">
            Live agent desk
          </p>
          <p className="font-display text-5xl font-extrabold tracking-tight text-gradient-brand sm:text-6xl md:text-7xl">
            Agentic CRM
          </p>
          <p className="mt-4 max-w-xl text-lg text-white/85 sm:text-xl">
            IGaming Lead Outreach
          </p>
        </header>

        <section className="anim-rise-delay-1 surface-glass p-6 sm:p-8">
          <div className="grid gap-3 sm:grid-cols-3">
            {ACTIONS.map((item) => {
              const active = action === item.id;
              const tone =
                item.id === "outreach"
                  ? "action-outreach"
                  : item.id === "update"
                    ? "action-update"
                    : "action-summarize";
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => onActionChange(item.id)}
                  className={`${tone} group relative overflow-hidden px-4 py-5 text-left transition duration-300 ${
                    active
                      ? "text-white shadow-lg shadow-night/20"
                      : "bg-white/80 text-ink hover:-translate-y-0.5 hover:shadow-md"
                  }`}
                  style={
                    active
                      ? {
                          background: `linear-gradient(135deg, var(--action-accent), color-mix(in srgb, var(--action-accent) 70%, #0f172a))`,
                        }
                      : { border: "1px solid color-mix(in srgb, var(--action-accent) 35%, white)" }
                  }
                >
                  <span
                    aria-hidden
                    className="absolute -right-4 -top-4 size-16 rounded-full opacity-30 blur-xl transition group-hover:opacity-60"
                    style={{ background: "var(--action-accent)" }}
                  />
                  <span className="font-display relative block text-lg font-bold">
                    {item.label}
                  </span>
                  <span
                    className={`relative mt-1 block text-sm ${active ? "text-white/85" : "text-ink-soft"}`}
                  >
                    {item.blurb}
                  </span>
                </button>
              );
            })}
          </div>

          <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <label className="flex flex-col gap-2">
              <span className="text-xs font-bold uppercase tracking-[0.14em] text-teal-deep">
                ID
              </span>
              <input
                value={filterId}
                onChange={(e) => setFilterId(e.target.value)}
                placeholder="e.g. L101"
                className="border-2 border-line bg-white/90 px-3 py-2.5 outline-none transition focus:border-cyan focus:ring-2 focus:ring-cyan/30"
              />
            </label>

            <label className="flex flex-col gap-2">
              <span className="text-xs font-bold uppercase tracking-[0.14em] text-coral-deep">
                Email
              </span>
              <input
                value={filterEmail}
                onChange={(e) => setFilterEmail(e.target.value)}
                placeholder="email address"
                className="border-2 border-line bg-white/90 px-3 py-2.5 outline-none transition focus:border-coral focus:ring-2 focus:ring-coral/30"
              />
            </label>

            <label className="flex flex-col gap-2">
              <span className="text-xs font-bold uppercase tracking-[0.14em] text-amber-deep">
                Game genre
              </span>
              <select
                value={filterGenre}
                onChange={(e) => setFilterGenre(e.target.value)}
                className="border-2 border-line bg-white/90 px-3 py-2.5 outline-none transition focus:border-amber focus:ring-2 focus:ring-amber/30"
              >
                <option value="">All genres</option>
                {filterOptions.game_genre_preference.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>

            <label className="flex flex-col gap-2">
              <span className="text-xs font-bold uppercase tracking-[0.14em] text-cyan-deep">
                Status
              </span>
              <select
                value={filterStatus}
                onChange={(e) => setFilterStatus(e.target.value)}
                className="border-2 border-line bg-white/90 px-3 py-2.5 outline-none transition focus:border-cyan focus:ring-2 focus:ring-cyan/30"
              >
                <option value="">All statuses</option>
                {filterOptions.status.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>

            <label className="flex flex-col gap-2">
              <span className="text-xs font-bold uppercase tracking-[0.14em] text-coral-deep">
                Churn risk
              </span>
              <select
                value={filterChurn}
                onChange={(e) => setFilterChurn(e.target.value)}
                className="border-2 border-line bg-white/90 px-3 py-2.5 outline-none transition focus:border-coral focus:ring-2 focus:ring-coral/30"
              >
                <option value="">All risk levels</option>
                {filterOptions.churn_risk_level.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-3">
              <p className="rounded-sm bg-night/90 px-3 py-1.5 text-sm font-semibold text-cyan">
                {loadingLeads
                  ? "Loading leads…"
                  : `${selectedIds.length} selected · ${leadCatalog.length} from filter`}
              </p>
              {multi && leadCatalog.length > 0 ? (
                <button
                  type="button"
                  onClick={allShownSelected ? clearSelection : selectAllShown}
                  className="border-2 border-teal bg-white px-3 py-1.5 text-sm font-bold text-teal-deep transition hover:bg-teal hover:text-white"
                >
                  {allShownSelected
                    ? "Clear selection"
                    : `Select all from filter (${leadCatalog.length})`}
                </button>
              ) : null}
            </div>
            <button
              type="button"
              onClick={onRun}
              disabled={running || selectedIds.length === 0}
              className="anim-shimmer bg-gradient-to-r from-coral via-amber to-cyan px-6 py-3 text-sm font-extrabold uppercase tracking-wide text-night shadow-lg shadow-coral/30 transition hover:brightness-110 disabled:opacity-45"
            >
              {running
                ? "Running agents…"
                : multi
                  ? `Run for ${selectedIds.length} lead(s)`
                  : "Run pipeline"}
            </button>
          </div>

          <div className="mt-4 max-h-72 overflow-y-auto border-2 border-teal/25 bg-gradient-to-b from-white to-mist/80">
            {multi && leadCatalog.length > 0 ? (
              <label className="flex cursor-pointer items-center gap-3 border-b border-line bg-gradient-to-r from-cyan/15 to-amber/15 px-4 py-2.5">
                <input
                  type="checkbox"
                  checked={allShownSelected}
                  ref={(el) => {
                    if (el) {
                      el.indeterminate =
                        selectedIds.length > 0 && !allShownSelected;
                    }
                  }}
                  onChange={() =>
                    allShownSelected ? clearSelection() : selectAllShown()
                  }
                  className="size-4 accent-coral"
                />
                <span className="text-sm font-bold text-teal-deep">
                  Select all from filter ({leadCatalog.length})
                </span>
              </label>
            ) : null}
            {leadCatalog.map((item) => {
              const checked = selectedIds.includes(item.id);
              return (
                <label
                  key={item.id}
                  className={`flex cursor-pointer items-center gap-3 border-b border-line/80 px-4 py-3 last:border-b-0 transition ${
                    checked
                      ? "bg-gradient-to-r from-coral/15 via-amber/10 to-cyan/15"
                      : "hover:bg-teal/5"
                  }`}
                >
                  <input
                    type={multi ? "checkbox" : "radio"}
                    name="lead-select"
                    checked={checked}
                    onChange={() => toggleLead(item.id)}
                    className="size-4 accent-teal-deep"
                  />
                  <span className="min-w-16 font-extrabold text-coral-deep">
                    {item.id}
                  </span>
                  <span className="flex-1 font-semibold text-ink">{item.name}</span>
                  <span className="hidden text-sm text-ink-soft md:inline">
                    {item.email}
                  </span>
                  <span className="hidden rounded-sm bg-night/90 px-2 py-0.5 text-xs font-semibold text-lime lg:inline">
                    {item.status} · {item.churn_risk_level}
                  </span>
                </label>
              );
            })}
            {!loadingLeads && leadCatalog.length === 0 ? (
              <p className="px-4 py-8 text-center text-sm font-medium text-ink-soft">
                {filterId.trim() ||
                filterEmail.trim() ||
                filterGenre ||
                filterStatus ||
                filterChurn
                  ? "No leads match these filters."
                  : "Set a filter to light up the lead list."}
              </p>
            ) : null}
          </div>

          {selectedLeads.length > 0 ? (
            <p className="mt-3 text-sm font-medium text-teal-deep">
              Selected:{" "}
              {selectedLeads.map((l) => `${l.id} (${l.name})`).join(", ")}
            </p>
          ) : null}

          {error ? (
            <p className="mt-6 border-2 border-coral/50 bg-coral/10 px-4 py-3 text-sm font-semibold text-coral-deep">
              {error}
            </p>
          ) : null}
        </section>

        {batch ? (
          <BatchResultPanel
            batch={batch}
            decidingThread={decidingThread}
            onHumanDecision={onHumanDecision}
          />
        ) : null}
      </main>
    </div>
  );
}

function Meta({
  label,
  value,
}: {
  label: string;
  value?: string | number | null;
}) {
  return (
    <div>
      <dt className="text-xs font-semibold uppercase tracking-[0.14em] text-ink-soft">
        {label}
      </dt>
      <dd className="mt-1 text-base text-ink">{value ?? "—"}</dd>
    </div>
  );
}

function BatchResultPanel({
  batch,
  decidingThread,
  onHumanDecision,
}: {
  batch: CrmBatchRunResponse;
  decidingThread: string | null;
  onHumanDecision: (threadId: string, decision: HumanDecision) => void;
}) {
  const pending = batch.pending_approvals ?? 0;
  return (
    <section className="anim-rise-delay-2 mt-10 space-y-6">
      <p className="inline-flex items-center gap-2 bg-gradient-to-r from-amber via-coral to-cyan px-3 py-1.5 text-xs font-extrabold uppercase tracking-[0.16em] text-night">
        Results · {batch.action} · {batch.count} lead(s)
        {pending > 0 ? ` · ${pending} awaiting your approval` : ""}
      </p>
      {batch.results.map((result) => (
        <ResultPanel
          key={result.thread_id || result.lead_id}
          result={result}
          decidingThread={decidingThread}
          onHumanDecision={onHumanDecision}
        />
      ))}
    </section>
  );
}

function ResultPanel({
  result,
  decidingThread,
  onHumanDecision,
}: {
  result: CrmRunResponse;
  decidingThread: string | null;
  onHumanDecision: (threadId: string, decision: HumanDecision) => void;
}) {
  const awaiting =
    Boolean(result.awaiting_human_approval) && Boolean(result.thread_id);
  const busy = decidingThread === result.thread_id;

  return (
    <div
      className={`surface-glass overflow-hidden p-6 sm:p-8 ${
        awaiting ? "ring-2 ring-amber" : ""
      }`}
    >
      <div
        aria-hidden
        className="mb-4 h-1.5 w-full rounded-sm bg-gradient-to-r from-coral via-amber to-cyan"
      />
      <p className="font-display text-xl font-extrabold text-teal-deep">
        {result.lead_name}{" "}
        <span className="text-base font-semibold text-coral-deep">
          ({result.lead_id})
        </span>
      </p>

      {result.action === "outreach" ? (
        <div className="mt-4 space-y-4">
          <p className="rounded-sm bg-coral/10 px-3 py-2 text-ink">
            Score{" "}
            <span className="font-extrabold text-coral-deep">
              {result.qualification_score}/100
            </span>
            {result.qualification_reasoning
              ? ` — ${result.qualification_reasoning}`
              : ""}
          </p>
          {result.outreach_subject ? (
            <>
              <h3 className="font-display text-lg font-bold text-cyan-deep">
                {result.outreach_subject}
              </h3>
              <p className="whitespace-pre-wrap leading-relaxed text-ink">
                {result.outreach_body}
              </p>
            </>
          ) : null}

          {awaiting ? (
            <div className="space-y-3 border-2 border-amber bg-gradient-to-br from-amber/20 to-coral/10 p-4">
              <p className="text-sm font-extrabold uppercase tracking-wide text-amber-deep">
                Human approval needed
              </p>
              <p className="text-sm font-semibold text-ink">
                Critic approved this draft. Approve to send, or reject to stop.
              </p>
              {result.critic_feedback ? (
                <p className="text-sm text-ink-soft">
                  Critic: {result.critic_feedback}
                </p>
              ) : null}
              <div className="flex flex-wrap gap-3">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() =>
                    result.thread_id &&
                    onHumanDecision(result.thread_id, "approve")
                  }
                  className="bg-gradient-to-r from-teal to-cyan px-4 py-2.5 text-sm font-extrabold text-white shadow-md transition hover:brightness-110 disabled:opacity-50"
                >
                  {busy ? "Working…" : "Approve & send"}
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() =>
                    result.thread_id &&
                    onHumanDecision(result.thread_id, "reject")
                  }
                  className="border-2 border-coral bg-white px-4 py-2.5 text-sm font-extrabold text-coral-deep transition hover:bg-coral hover:text-white disabled:opacity-50"
                >
                  Reject
                </button>
              </div>
            </div>
          ) : (
            <p className="text-sm font-medium text-ink-soft">
              Critic: {result.is_approved ? "approved" : "not approved"}
              {result.human_approved === true
                ? " · You: approved"
                : result.human_approved === false
                  ? " · You: rejected"
                  : ""}{" "}
              · Email: {result.email_status || "n/a"} · Revisions:{" "}
              {result.revision_attempts}
            </p>
          )}
        </div>
      ) : null}

      {result.action === "update" ? (
        <div className="mt-4 grid gap-3 sm:grid-cols-3">
          <div className="bg-amber/15 p-3">
            <Meta label="Sentiment" value={result.sentiment} />
          </div>
          <div className="bg-coral/15 p-3">
            <Meta label="Churn risk" value={result.churn_risk} />
          </div>
          <div className="bg-cyan/15 p-3 sm:col-span-1">
            <Meta label="Recurring issues" value={result.recurring_issues} />
          </div>
          <p className="mt-1 whitespace-pre-wrap leading-relaxed text-ink sm:col-span-3">
            {result.summary}
          </p>
        </div>
      ) : null}

      {result.action === "summarize" ? (
        <pre className="mt-4 whitespace-pre-wrap border-l-4 border-cyan bg-cyan/10 p-4 font-body text-base leading-relaxed text-ink">
          {result.user_summary || "No summary returned."}
        </pre>
      ) : null}
    </div>
  );
}
