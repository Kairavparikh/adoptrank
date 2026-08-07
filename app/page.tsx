"use client";

import { FormEvent, useMemo, useState } from "react";

type Repo = {
  id: string;
  name: string;
  owner: string;
  description: string;
  reason: string;
  language: string;
  license: string;
  updated: string;
  match: number;
  adoption: "Emerging" | "Durable" | "Hidden gem" | "At risk";
  adoptionDelta: string;
  stars: string;
  dependents: string;
  evidence: string[];
  strengths: string[];
  concern: string;
  tags: string[];
  spark: number[];
};

const repositories: Repo[] = [
  {
    id: "salesforce/merlion",
    name: "Merlion",
    owner: "salesforce",
    description: "An end-to-end machine learning framework for time-series intelligence.",
    reason: "Best overall fit for production time-series anomaly detection with tested forecasting and streaming workflows.",
    language: "Python",
    license: "Apache-2.0",
    updated: "2 days ago",
    match: 94,
    adoption: "Durable",
    adoptionDelta: "+18% / 90d",
    stars: "4.2k",
    dependents: "312",
    evidence: ["merlion/models/anomaly/", "merlion/evaluate/anomaly.py", "tests/anomaly/"],
    strengths: ["Time-series native", "Online detectors", "Evaluation suite"],
    concern: "Larger installation than a single-model library",
    tags: ["bitcoin", "anomaly", "time series", "streaming", "python", "forecasting"],
    spark: [18, 24, 21, 32, 38, 41, 55, 62, 68, 78],
  },
  {
    id: "yzhao062/pyod",
    name: "PyOD",
    owner: "yzhao062",
    description: "A comprehensive Python library for detecting outlying objects in multivariate data.",
    reason: "Mature, lightweight collection of anomaly algorithms with broad adoption and consistent APIs.",
    language: "Python",
    license: "BSD-2-Clause",
    updated: "5 days ago",
    match: 89,
    adoption: "Durable",
    adoptionDelta: "+9% / 90d",
    stars: "9.4k",
    dependents: "1.8k",
    evidence: ["pyod/models/", "examples/", "pyod/test/"],
    strengths: ["45+ algorithms", "Consistent API", "Lightweight"],
    concern: "Streaming data needs feature-window adaptation",
    tags: ["anomaly", "outlier", "python", "machine learning", "bitcoin"],
    spark: [30, 34, 37, 42, 46, 51, 55, 58, 64, 69],
  },
  {
    id: "seldonio/alibi-detect",
    name: "Alibi Detect",
    owner: "SeldonIO",
    description: "Algorithms for outlier, adversarial and drift detection.",
    reason: "Strong choice when anomaly detection must expand into drift monitoring for deployed ML systems.",
    language: "Python",
    license: "Apache-2.0",
    updated: "8 days ago",
    match: 85,
    adoption: "Emerging",
    adoptionDelta: "+24% / 90d",
    stars: "2.5k",
    dependents: "219",
    evidence: ["alibi_detect/od/", "alibi_detect/cd/", "examples/"],
    strengths: ["Drift detection", "TensorFlow + PyTorch", "Production APIs"],
    concern: "Heavier dependency footprint",
    tags: ["anomaly", "drift", "python", "pytorch", "monitoring", "time series"],
    spark: [12, 16, 18, 26, 30, 38, 47, 58, 70, 84],
  },
  {
    id: "online-ml/river",
    name: "River",
    owner: "online-ml",
    description: "Online machine learning for data streams in Python.",
    reason: "Best fit when every observation must update the model without retraining on a full batch.",
    language: "Python",
    license: "BSD-3-Clause",
    updated: "Yesterday",
    match: 82,
    adoption: "Hidden gem",
    adoptionDelta: "+31% / 90d",
    stars: "5.4k",
    dependents: "164",
    evidence: ["river/anomaly/", "river/drift/", "river/time_series/"],
    strengths: ["True online learning", "Low memory", "Streaming metrics"],
    concern: "Smaller ecosystem than batch ML libraries",
    tags: ["streaming", "anomaly", "online", "python", "bitcoin", "machine learning"],
    spark: [8, 11, 17, 20, 29, 35, 46, 60, 75, 92],
  },
  {
    id: "feast-dev/feast",
    name: "Feast",
    owner: "feast-dev",
    description: "An open-source feature store for production machine learning.",
    reason: "Strong production feature-store foundation with batch and online serving integrations.",
    language: "Python",
    license: "Apache-2.0",
    updated: "Today",
    match: 78,
    adoption: "Durable",
    adoptionDelta: "+14% / 90d",
    stars: "6.3k",
    dependents: "782",
    evidence: ["sdk/python/feast/", "infra/", "examples/"],
    strengths: ["Online serving", "Point-in-time joins", "Provider ecosystem"],
    concern: "Infrastructure overhead for small projects",
    tags: ["feature store", "streaming", "python", "machine learning", "data"],
    spark: [25, 30, 36, 39, 45, 54, 61, 67, 73, 82],
  },
  {
    id: "nautechsystems/nautilus_trader",
    name: "NautilusTrader",
    owner: "nautechsystems",
    description: "A high-performance algorithmic trading platform and event-driven backtester.",
    reason: "Excellent fit for event-driven trading systems that need production and backtest parity.",
    language: "Rust / Python",
    license: "LGPL-3.0",
    updated: "Today",
    match: 76,
    adoption: "Emerging",
    adoptionDelta: "+42% / 90d",
    stars: "16.8k",
    dependents: "96",
    evidence: ["crates/", "nautilus_trader/", "tests/integration_tests/"],
    strengths: ["Event driven", "Rust core", "Live/backtest parity"],
    concern: "Copyleft license requires review",
    tags: ["bitcoin", "trading", "order book", "rust", "python", "backtesting"],
    spark: [6, 10, 15, 23, 32, 45, 57, 71, 83, 97],
  },
];

const examples = [
  "Bitcoin anomaly detection in Python",
  "Streaming feature store",
  "Rust order-book engine",
];

function scoreFor(repo: Repo, query: string) {
  const words = query.toLowerCase().split(/\W+/).filter((word) => word.length > 2);
  const matched = words.filter((word) =>
    [...repo.tags, repo.name, repo.description].join(" ").toLowerCase().includes(word),
  ).length;
  const semanticBoost = words.length ? (matched / words.length) * 14 : 0;
  return Math.min(99, Math.round(repo.match - 5 + semanticBoost));
}

function MiniChart({ values }: { values: number[] }) {
  const points = values.map((value, index) => `${index * 11.1},${42 - value * 0.34}`).join(" ");
  return (
    <svg className="sparkline" viewBox="0 0 100 45" role="img" aria-label="Adoption growth over 90 days">
      <polyline points={points} fill="none" stroke="currentColor" strokeWidth="2.5" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

export default function Home() {
  const [query, setQuery] = useState("Bitcoin anomaly detection in Python");
  const [activeQuery, setActiveQuery] = useState("Bitcoin anomaly detection in Python");
  const [view, setView] = useState<"search" | "discover" | "method" | "compare">("search");
  const [selected, setSelected] = useState<string>(repositories[0].id);
  const [compared, setCompared] = useState<string[]>([]);
  const [serverOrder, setServerOrder] = useState<string[]>([]);
  const [dataSource, setDataSource] = useState<"preview" | "postgres">("preview");
  const [searching, setSearching] = useState(false);

  const ranked = useMemo(() => {
    const order = new Map(serverOrder.map((id, index) => [id.toLowerCase(), index]));
    return [...repositories].sort((a, b) => {
      const aIndex = order.get(a.id.toLowerCase());
      const bIndex = order.get(b.id.toLowerCase());
      if (aIndex !== undefined || bIndex !== undefined) return (aIndex ?? 10_000) - (bIndex ?? 10_000);
      return scoreFor(b, activeQuery) - scoreFor(a, activeQuery);
    });
  }, [activeQuery, serverOrder]);
  const selectedRepo = repositories.find((repo) => repo.id === selected) ?? ranked[0];

  async function searchApi(nextQuery: string) {
    setSearching(true);
    try {
      const response = await fetch(`/api/search?q=${encodeURIComponent(nextQuery)}`);
      if (!response.ok) throw new Error("Search request failed");
      const payload = (await response.json()) as { ids?: string[]; source?: "preview" | "postgres" };
      setServerOrder(payload.ids ?? []);
      setDataSource(payload.source ?? "preview");
    } catch {
      setServerOrder([]);
      setDataSource("preview");
    } finally {
      setSearching(false);
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!query.trim()) return;
    const nextQuery = query.trim();
    const first = [...repositories].sort((a, b) => scoreFor(b, nextQuery) - scoreFor(a, nextQuery))[0];
    setActiveQuery(nextQuery);
    setSelected(first?.id ?? repositories[0].id);
    setView("search");
    void searchApi(nextQuery);
  }

  function runExample(example: string) {
    const first = [...repositories].sort((a, b) => scoreFor(b, example) - scoreFor(a, example))[0];
    setQuery(example);
    setActiveQuery(example);
    setSelected(first?.id ?? repositories[0].id);
    setView("search");
    void searchApi(example);
  }

  function toggleCompare(id: string) {
    setCompared((current) =>
      current.includes(id) ? current.filter((item) => item !== id) : current.length < 3 ? [...current, id] : current,
    );
  }

  return (
    <main>
      <nav className="nav-shell" aria-label="Primary navigation">
        <button className="brand" onClick={() => setView("search")} aria-label="AdoptRank home">
          <span className="brand-mark">A</span>
          <span>AdoptRank</span>
        </button>
        <div className="nav-tabs">
          <button className={view === "search" ? "active" : ""} onClick={() => setView("search")}>Search</button>
          <button className={view === "discover" ? "active" : ""} onClick={() => setView("discover")}>Discover</button>
          <button className={view === "method" ? "active" : ""} onClick={() => setView("method")}>How it works</button>
        </div>
        <a className="cli-pill" href="#terminal"><span className="status-dot" /> CLI preview</a>
      </nav>

      {view === "search" && (
        <>
          <section className="hero">
            <div className="eyebrow"><span /> Search beyond stars</div>
            <h1>Find open source<br />that <em>actually fits.</em></h1>
            <p>Describe what you are building. AdoptRank reads the code, tracks real adoption, and finds repositories that belong in your project.</p>
            <form className="search-box" onSubmit={submit}>
              <span className="search-icon" aria-hidden="true">⌕</span>
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                aria-label="Describe the repository you need"
                placeholder="What do you want to build?"
              />
              <button type="submit" disabled={searching}>{searching ? "Ranking evidence…" : "Find repositories"} <span>→</span></button>
            </form>
            <div className="examples">
              <span>Try</span>
              {examples.map((example) => <button key={example} onClick={() => runExample(example)}>{example}</button>)}
            </div>
          </section>

          <section className="results-section">
            <div className="results-head">
              <div>
                <span className="section-kicker">Ranked for your intent</span>
                <h2>{activeQuery}</h2>
              </div>
              <div className="freshness"><span className="live-pulse" /> {dataSource === "postgres" ? "Live from Postgres" : "Preview data · pgvector ready"}</div>
            </div>

            <div className="results-layout">
              <div className="result-list">
                {ranked.slice(0, 4).map((repo, index) => {
                  const score = scoreFor(repo, activeQuery);
                  return (
                    <article key={repo.id} className={`repo-card ${selected === repo.id ? "selected" : ""}`} onClick={() => setSelected(repo.id)}>
                      <div className="rank-number">{String(index + 1).padStart(2, "0")}</div>
                      <div className="repo-main">
                        <div className="repo-title-row">
                          <div>
                            <span className="owner">{repo.owner} /</span>
                            <h3>{repo.name}</h3>
                          </div>
                          <span className={`signal ${repo.adoption.toLowerCase().replace(" ", "-")}`}>{repo.adoption}</span>
                        </div>
                        <p className="repo-description">{repo.description}</p>
                        <p className="reason"><span>Why</span>{repo.reason}</p>
                        <div className="repo-meta">
                          <span><i className="lang-dot" /> {repo.language}</span>
                          <span>{repo.license}</span>
                          <span>Updated {repo.updated}</span>
                          <a href={`https://github.com/${repo.id}`} target="_blank" rel="noreferrer" onClick={(event) => event.stopPropagation()}>Open GitHub ↗</a>
                        </div>
                      </div>
                      <div className="score-block">
                        <strong>{score}</strong><span>fit score</span>
                        <button className={compared.includes(repo.id) ? "compare active" : "compare"} onClick={(event) => { event.stopPropagation(); toggleCompare(repo.id); }}>
                          {compared.includes(repo.id) ? "✓ Added" : "+ Compare"}
                        </button>
                      </div>
                    </article>
                  );
                })}
              </div>

              <aside className="evidence-panel">
                <div className="panel-top">
                  <span className="section-kicker">Evidence, not opinion</span>
                  <span className="verified">✓ Code indexed</span>
                </div>
                <h3>Why {selectedRepo.name} ranks here</h3>
                <p className="panel-summary">{selectedRepo.reason}</p>

                <div className="evidence-score">
                  <div><span>Functional fit</span><strong>{scoreFor(selectedRepo, activeQuery)}%</strong></div>
                  <div className="meter"><i style={{ width: `${scoreFor(selectedRepo, activeQuery)}%` }} /></div>
                </div>

                <div className="evidence-grid">
                  <div className="evidence-stat">
                    <span>Adoption</span><strong>{selectedRepo.adoptionDelta}</strong>
                    <MiniChart values={selectedRepo.spark} />
                  </div>
                  <div className="evidence-stat"><span>Dependents</span><strong>{selectedRepo.dependents}</strong><small>verified packages</small></div>
                  <div className="evidence-stat"><span>Attention</span><strong>{selectedRepo.stars}</strong><small>GitHub stars</small></div>
                </div>

                <div className="code-evidence">
                  <span>Implementation evidence</span>
                  {selectedRepo.evidence.map((path) => <code key={path}>{path}<b>↗</b></code>)}
                </div>
                <div className="strengths">
                  {selectedRepo.strengths.map((strength) => <span key={strength}>✓ {strength}</span>)}
                </div>
                <div className="concern"><span>Watch</span>{selectedRepo.concern}</div>
                <a className="primary-link" href={`https://github.com/${selectedRepo.id}`} target="_blank" rel="noreferrer">Inspect repository <span>↗</span></a>
              </aside>
            </div>
          </section>

          <section className="terminal-section" id="terminal">
            <div className="terminal-copy">
              <span className="section-kicker light">Built for where you work</span>
              <h2>One search.<br />Your project’s context.</h2>
              <p>The CLI reads dependency files and runtime metadata locally, then reranks results for the codebase in front of you. Your source stays on your machine.</p>
              <div className="privacy-row"><span>Local analysis</span><span>Secret filtering</span><span>No auto-execution</span></div>
            </div>
            <div className="terminal-window">
              <div className="terminal-bar"><span /><span /><span /><b>~/bitcoin-engine</b></div>
              <div className="terminal-body">
                <p><i>$</i> adoptrank find <em>&quot;streaming anomaly detection&quot;</em></p>
                <div className="scan"><span>✓</span> Detected Python 3.12 · pandas · PyTorch</div>
                <div className="terminal-result">
                  <b>01</b><div><strong>online-ml/river</strong><a href="https://github.com/online-ml/river" target="_blank" rel="noreferrer">github.com/online-ml/river ↗</a><p>Best fit for online updates and your current dependency graph.</p></div><mark>96</mark>
                </div>
                <div className="terminal-result muted"><b>02</b><div><strong>salesforce/Merlion</strong><p>Stronger evaluation suite, but a heavier install.</p></div><mark>91</mark></div>
                <p className="terminal-command"><i>$</i> adoptrank explain online-ml/river <span>█</span></p>
              </div>
            </div>
          </section>
        </>
      )}

      {view === "discover" && <Discover onSelect={(repo) => { setSelected(repo.id); setActiveQuery(repo.tags.slice(0, 3).join(" ")); setView("search"); }} />}
      {view === "method" && <Method />}
      {view === "compare" && <Compare repos={[...new Set([...compared, ...ranked.map((repo) => repo.id)])].slice(0, 3).map((id) => repositories.find((repo) => repo.id === id)).filter((repo): repo is Repo => Boolean(repo))} onBack={() => setView("search")} />}

      {compared.length > 0 && (
        <div className="compare-tray">
          <div><strong>{compared.length} selected</strong><span>{compared.map((id) => repositories.find((repo) => repo.id === id)?.name).join(" · ")}</span></div>
          <button onClick={() => setCompared([])}>Clear</button>
          <button className="compare-now" onClick={() => setView("compare")}>Compare evidence →</button>
        </div>
      )}
      <footer><div className="brand"><span className="brand-mark">A</span><span>AdoptRank</span></div><p>Open-source discovery, backed by evidence.</p><span>Preview index · Updated continuously</span></footer>
    </main>
  );
}

function Discover({ onSelect }: { onSelect: (repo: Repo) => void }) {
  return (
    <section className="subpage discover-page">
      <div className="subpage-hero"><span className="section-kicker">Ecosystem intelligence</span><h1>See adoption<br /><em>before the hype.</em></h1><p>Continuously refreshed rankings distinguish genuine usage from temporary attention.</p></div>
      <div className="category-grid">
        {(["Emerging", "Durable", "Hidden gem"] as const).map((category) => (
          <div className="category" key={category}>
            <div className="category-head"><div><span>{category === "Emerging" ? "↗" : category === "Durable" ? "◆" : "✦"}</span><h2>{category}</h2></div><p>{category === "Emerging" ? "Adoption is accelerating" : category === "Durable" ? "Used and maintained over time" : "Usage ahead of attention"}</p></div>
            {repositories.filter((repo) => repo.adoption === category).map((repo, index) => (
              <button className="mini-repo" key={repo.id} onClick={() => onSelect(repo)}><b>{index + 1}</b><div><strong>{repo.owner}/{repo.name}</strong><span>{repo.language} · {repo.adoptionDelta}</span></div><MiniChart values={repo.spark} /><i>→</i></button>
            ))}
          </div>
        ))}
      </div>
      <div className="attention-gap"><div><span className="section-kicker light">The attention–adoption gap</span><h2>Stars show interest.<br />Dependencies show commitment.</h2></div><p>AdoptRank measures package usage, returning contributors, release health, code evidence, and security response. Every label can be traced back to its source and timestamp.</p></div>
    </section>
  );
}

function Method() {
  return (
    <section className="subpage method-page">
      <div className="subpage-hero"><span className="section-kicker">Transparent by design</span><h1>A ranking you can<br /><em>inspect and challenge.</em></h1><p>No single AI verdict. Every result is assembled from retrieval, real adoption, code evidence, and compatibility.</p></div>
      <div className="pipeline">
        {[ ["01", "Retrieve", "BM25 finds exact terms. Embeddings recover conceptual matches."], ["02", "Read the code", "AST analysis verifies functions, tests, interfaces, and examples."], ["03", "Measure adoption", "Dependency growth, releases, contributors, and maintenance over time."], ["04", "Rerank for you", "Language, runtime, license, and local dependencies shape final fit."] ].map(([number, title, text]) => <article key={number}><span>{number}</span><h2>{title}</h2><p>{text}</p></article>)}
      </div>
      <div className="model-card"><div><span className="section-kicker light">Model contract</span><h2>LLMs explain.<br />Evidence ranks.</h2></div><div className="formula"><span>Final fit</span><p><b>functional relevance</b> + sustained adoption + project compatibility + maintenance <i>− risk</i></p></div></div>
      <div className="benchmark"><div><span>Evaluation</span><strong>NDCG@10</strong><b>0.84</b><small>target</small></div><div><span>Candidate recall</span><strong>Recall@20</strong><b>95%</b><small>target</small></div><div><span>Forecast</span><strong>30 / 90 day</strong><b>2×</b><small>baselines</small></div><p>Targets for the first trained release. The preview currently demonstrates the product contract and ranking interface.</p></div>
    </section>
  );
}

function Compare({ repos, onBack }: { repos: Repo[]; onBack: () => void }) {
  return (
    <section className="subpage compare-page">
      <div className="compare-header">
        <button onClick={onBack}>← Back to results</button>
        <span className="section-kicker">Side-by-side evidence</span>
        <h1>Compare what matters.</h1>
        <p>Scores are useful; inspectable differences make the decision.</p>
      </div>
      <div className="comparison-table">
        <div className="comparison-row heading"><span>Repository</span>{repos.map((repo) => <div key={repo.id}><small>{repo.owner} /</small><strong>{repo.name}</strong><a href={`https://github.com/${repo.id}`} target="_blank" rel="noreferrer">Open GitHub ↗</a></div>)}</div>
        <div className="comparison-row"><span>Project fit</span>{repos.map((repo) => <strong key={repo.id} className="fit-value">{repo.match >= 90 ? "Strong" : repo.match >= 80 ? "Good" : "Partial"}</strong>)}</div>
        <div className="comparison-row"><span>Adoption</span>{repos.map((repo) => <div key={repo.id}><strong>{repo.adoption}</strong><small>{repo.adoptionDelta}</small></div>)}</div>
        <div className="comparison-row"><span>Verified dependents</span>{repos.map((repo) => <strong key={repo.id}>{repo.dependents}</strong>)}</div>
        <div className="comparison-row"><span>Implementation</span>{repos.map((repo) => <div key={repo.id}>{repo.strengths.map((item) => <small className="check" key={item}>✓ {item}</small>)}</div>)}</div>
        <div className="comparison-row concern-row"><span>Main concern</span>{repos.map((repo) => <p key={repo.id}>{repo.concern}</p>)}</div>
      </div>
      <p className="comparison-note">AdoptRank compares evidence available at the same data watermark. Missing signals reduce confidence instead of becoming zero.</p>
    </section>
  );
}
