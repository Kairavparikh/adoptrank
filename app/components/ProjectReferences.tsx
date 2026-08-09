"use client";

import { FormEvent, useState } from "react";

type Result = { full_name: string; url: string; description: string; reason: string; score: number; code_evidence?: string[] };
type Project = { root_name: string; languages: string[]; frameworks: string[]; summary: string };
const examples = [["https://github.com/vercel/next.js", "Add Stripe subscriptions with verified webhook handling"], ["https://github.com/fastapi/fastapi", "Add Redis-backed rate limiting and retry-safe background jobs"]];

export default function ProjectReferences() {
  const [repositoryUrl, setRepositoryUrl] = useState(""); const [feature, setFeature] = useState("");
  const [project, setProject] = useState<Project | null>(null); const [results, setResults] = useState<Result[]>([]);
  const [error, setError] = useState(""); const [loading, setLoading] = useState(false);
  async function submit(event: FormEvent) {
    event.preventDefault(); setError(""); setLoading(true);
    try {
      const response = await fetch("/api/project-reference", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ repositoryUrl, feature }) });
      const payload = await response.json() as { error?: string; project?: Project; results?: Result[] };
      if (!response.ok) throw new Error(payload.error ?? "Reference search failed.");
      setProject(payload.project ?? null); setResults(payload.results ?? []);
    } catch (caught) { setProject(null); setResults([]); setError(caught instanceof Error ? caught.message : "Reference search failed."); } finally { setLoading(false); }
  }
  function applyExample(url: string, nextFeature: string) { setRepositoryUrl(url); setFeature(nextFeature); setError(""); }
  return <section className="project-reference-page"><div className="project-reference-hero"><span className="section-kicker">Project-aware discovery</span><h1>Find references<br />for <em>your project.</em></h1><p>Enter a public GitHub project and the feature you want to add. AdoptRank reads only its public metadata and manifests, then finds real implementations that fit.</p></div><div className="project-reference-shell"><form className="project-reference-form" onSubmit={submit}><label><span>Your public GitHub project</span><input value={repositoryUrl} onChange={(event) => setRepositoryUrl(event.target.value)} placeholder="https://github.com/you/your-project" aria-label="Your public GitHub project" /></label><label><span>Feature to add</span><textarea value={feature} onChange={(event) => setFeature(event.target.value)} placeholder="Add Stripe subscriptions with idempotent webhook retries" aria-label="Feature to add" /></label><button type="submit" disabled={loading}>{loading ? "Inspecting and ranking…" : "Find implementation references →"}</button><p className="project-privacy">Public repositories only in the browser. For a private/local project, use <code>adoptrank find &quot;…&quot; --path .</code>; source stays local.</p></form><div className="project-examples"><span>Try an example</span>{examples.map(([url, text]) => <button key={text} type="button" onClick={() => applyExample(url, text)}><b>{url.replace("https://github.com/", "")}</b><small>{text}</small></button>)}</div>{error && <div className="project-error">{error}</div>}{project && <section className="project-profile"><div><span className="section-kicker">Detected project profile</span><h2>{project.root_name}</h2><p>{project.summary}</p></div><div className="project-chips">{[...project.languages, ...project.frameworks].slice(0, 10).map((item) => <span key={item}>{item}</span>)}</div></section>}{results.length > 0 && <section className="project-results"><div className="project-results-head"><div><span className="section-kicker">Compatible implementation references</span><h2>What similar projects do</h2></div><span>{results.length} ranked repositories</span></div>{results.map((result, index) => <article key={result.full_name} className="project-result"><b>{String(index + 1).padStart(2, "0")}</b><div><h3>{result.full_name}</h3><p>{result.description}</p><p className="project-reason"><span>Why it fits</span>{result.reason}</p><div className="project-evidence">{(result.code_evidence ?? []).slice(0, 3).map((path) => <code key={path}>{path}</code>)}</div></div><aside><strong>{Math.round(70 + 29 / (1 + Math.exp(-result.score)))}</strong><small>fit score</small><a href={result.url} target="_blank" rel="noreferrer">Open GitHub ↗</a></aside></article>)}</section>}</div></section>;
}
