"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

type LeaderboardItem = {
  fullName: string;
  owner: string;
  name: string;
  description: string;
  language: string;
  license: string;
  topics: string[];
  stars: number;
  forks: number;
  updatedAt: string | null;
  score: number;
  adoptionScore: number;
  maintenanceScore: number;
  qualityScore: number;
  depthScore: number;
  originalityScore: number;
  attentionScore: number;
  confidence: number;
  status: string;
  globalRank: number;
  rankDelta: number | null;
  scoreDelta: number | null;
  dataWatermark: string;
  url: string;
};

type LeaderboardPayload = {
  items: LeaderboardItem[];
  page: number;
  limit: number;
  total: number;
  totalPages: number;
  dataWatermark: string | null;
  source: string;
  filters: {
    languages: string[];
    licenses: string[];
    statuses: string[];
  };
};

const statusDescriptions: Record<string, string> = {
  Emerging: "Adoption is accelerating",
  Durable: "Healthy usage and maintenance",
  "Hidden gem": "Adoption leads attention",
  Overhyped: "Attention leads real usage",
  "At risk": "Maintenance is declining",
};

const emptyPayload: LeaderboardPayload = {
  items: [],
  page: 1,
  limit: 25,
  total: 0,
  totalPages: 1,
  dataWatermark: null,
  source: "neon-leaderboard",
  filters: { languages: [], licenses: [], statuses: Object.keys(statusDescriptions) },
};

function formatNumber(value: number) {
  return new Intl.NumberFormat("en", { notation: value >= 10_000 ? "compact" : "standard", maximumFractionDigits: 1 }).format(value);
}

function score(value: number) {
  return Math.round(Math.max(0, Math.min(1, value)) * 100);
}

function movement(delta: number | null) {
  if (delta === null) return <span className="rank-new">new</span>;
  if (delta > 0) return <span className="rank-up">↑ {delta}</span>;
  if (delta < 0) return <span className="rank-down">↓ {Math.abs(delta)}</span>;
  return <span className="rank-flat">—</span>;
}

export default function Leaderboard() {
  const [payload, setPayload] = useState<LeaderboardPayload>(emptyPayload);
  const [ownerDraft, setOwnerDraft] = useState("");
  const [owner, setOwner] = useState("");
  const [language, setLanguage] = useState("");
  const [license, setLicense] = useState("");
  const [status, setStatus] = useState("");
  const [windowDays, setWindowDays] = useState(30);
  const [sort, setSort] = useState("overall");
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError("");
    const params = new URLSearchParams({
      window: String(windowDays),
      sort,
      page: String(page),
      limit: "25",
    });
    if (owner) params.set("owner", owner);
    if (language) params.set("language", language);
    if (license) params.set("license", license);
    if (status) params.set("status", status);
    try {
      const response = await fetch(`/api/leaderboard?${params}`, { signal, cache: "no-store" });
      if (!response.ok) throw new Error(`Leaderboard returned ${response.status}`);
      setPayload(await response.json() as LeaderboardPayload);
    } catch (reason) {
      if (reason instanceof DOMException && reason.name === "AbortError") return;
      setError("The live leaderboard could not be loaded. Please retry.");
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [language, license, owner, page, sort, status, windowDays]);

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => void load(controller.signal), 0);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [load]);

  function applyOwner(event: FormEvent) {
    event.preventDefault();
    setPage(1);
    setOwner(ownerDraft.trim());
  }

  function resetFilters() {
    setOwnerDraft("");
    setOwner("");
    setLanguage("");
    setLicense("");
    setStatus("");
    setWindowDays(30);
    setSort("overall");
    setPage(1);
  }

  const hasFilters = Boolean(owner || language || license || status || windowDays !== 30 || sort !== "overall");

  return (
    <section className="leaderboard-page">
      <header className="leaderboard-hero">
        <div>
          <div className="eyebrow"><span /> Updated from real adoption signals</div>
          <h1>The open-source<br /><em>adoption leaderboard.</em></h1>
          <p>See what developers are adopting—not merely starring. Filter the entire index or rank repositories from one GitHub user or organization.</p>
        </div>
        <div className="leaderboard-summary" aria-label="Leaderboard summary">
          <div><strong>{formatNumber(payload.total)}</strong><span>matching repositories</span></div>
          <div><strong>{windowDays}d</strong><span>adoption window</span></div>
          <div><strong>1h</strong><span>refresh cadence</span></div>
        </div>
      </header>

      <div className="leaderboard-shell">
        <form className="leaderboard-filters" onSubmit={applyOwner}>
          <label className="owner-filter">
            <span>GitHub username or organization</span>
            <div><b>@</b><input value={ownerDraft} onChange={(event) => setOwnerDraft(event.target.value)} placeholder="openai" maxLength={39} /><button>Apply</button></div>
          </label>
          <label><span>Language</span><select value={language} onChange={(event) => { setLanguage(event.target.value); setPage(1); }}><option value="">All languages</option>{payload.filters.languages.map((item) => <option key={item}>{item}</option>)}</select></label>
          <label><span>License</span><select value={license} onChange={(event) => { setLicense(event.target.value); setPage(1); }}><option value="">All licenses</option>{payload.filters.licenses.map((item) => <option key={item}>{item}</option>)}</select></label>
          <label><span>Status</span><select value={status} onChange={(event) => { setStatus(event.target.value); setPage(1); }}><option value="">All signals</option>{payload.filters.statuses.map((item) => <option key={item}>{item}</option>)}</select></label>
          <label><span>Rank by</span><select value={sort} onChange={(event) => { setSort(event.target.value); setPage(1); }}><option value="overall">Overall</option><option value="adoption">Adoption</option><option value="momentum">Rank momentum</option><option value="maintenance">Maintenance</option><option value="quality">Code quality</option><option value="depth">Technical depth</option><option value="originality">Originality</option><option value="attention">Attention</option><option value="stars">Stars</option></select></label>
          {hasFilters && <button type="button" className="reset-filters" onClick={resetFilters}>Reset filters</button>}
        </form>

        <div className="window-row">
          <span>Measure adoption over</span>
          {[1, 7, 30, 90].map((days) => <button key={days} className={windowDays === days ? "active" : ""} onClick={() => { setWindowDays(days); setPage(1); }}>{days === 1 ? "24 hours" : `${days} days`}</button>)}
          <div className="leaderboard-watermark"><span className="live-pulse" />{payload.dataWatermark ? `Observed ${new Date(payload.dataWatermark).toLocaleString()}` : "Awaiting snapshot"}</div>
        </div>

        {error && <div className="leaderboard-error" role="alert">{error}<button onClick={() => void load()}>Retry</button></div>}

        <div className={`leaderboard-table ${loading ? "loading" : ""}`} aria-busy={loading}>
          <div className="leaderboard-table-head"><span>Rank</span><span>Repository</span><span>Signal</span><span>Adoption</span><span>Health</span><span>Overall</span></div>
          {loading && !payload.items.length && Array.from({ length: 8 }, (_, index) => <div className="leaderboard-skeleton" key={index} />)}
          {!loading && !payload.items.length && <div className="leaderboard-empty"><strong>No repositories match these filters.</strong><p>Try removing a filter or checking the exact GitHub owner name.</p><button onClick={resetFilters}>Show the overall leaderboard</button></div>}
          {payload.items.map((item) => (
            <a className="leaderboard-row" href={item.url} target="_blank" rel="noreferrer" key={item.fullName}>
              <div className="leaderboard-rank"><strong>{String(item.globalRank).padStart(3, "0")}</strong>{movement(item.rankDelta)}</div>
              <div className="leaderboard-repo"><div><strong>{item.owner}<i>/</i>{item.name}</strong><span>{item.language} · {item.license}</span></div><p>{item.description || "No repository description provided."}</p><div className="leaderboard-tags">{item.topics.slice(0, 3).map((topic) => <span key={topic}>{topic}</span>)}<b>★ {formatNumber(item.stars)}</b></div></div>
              <div><span className={`leaderboard-status ${item.status.toLowerCase().replaceAll(" ", "-")}`}>{item.status}</span><small>{statusDescriptions[item.status]}</small></div>
              <div className="leaderboard-metric"><strong>{score(item.adoptionScore)}</strong><span>growth</span><i><b style={{ width: `${score(item.adoptionScore)}%` }} /></i></div>
              <div className="leaderboard-metric"><strong>{score((item.maintenanceScore + item.qualityScore) / 2)}</strong><span>maintainability</span><i><b style={{ width: `${score((item.maintenanceScore + item.qualityScore) / 2)}%` }} /></i></div>
              <div className="leaderboard-overall"><strong>{score(item.score)}</strong><span>score</span><small>{score(item.confidence)}% confidence</small></div>
            </a>
          ))}
        </div>

        <div className="leaderboard-pagination">
          <span>Page {payload.page} of {payload.totalPages}</span>
          <div><button disabled={payload.page <= 1 || loading} onClick={() => setPage((current) => Math.max(1, current - 1))}>← Previous</button><button disabled={payload.page >= payload.totalPages || loading} onClick={() => setPage((current) => current + 1)}>Next →</button></div>
        </div>
      </div>
    </section>
  );
}
