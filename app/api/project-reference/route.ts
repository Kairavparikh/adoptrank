import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const maxDuration = 60;

type ProjectContext = {
  root_name: string;
  languages: string[];
  frameworks: string[];
  dependencies: string[];
  symbols: string[];
  summary: string;
};

type ProjectReferenceRequest = { feature?: unknown; repositoryUrl?: unknown };

const MANIFEST_PATHS = ["package.json", "pyproject.toml", "requirements.txt", "Cargo.toml", "go.mod"];
const FRAMEWORKS = new Set([
  "next", "nextjs", "react", "fastapi", "django", "flask", "express", "nestjs", "spring",
  "rails", "laravel", "torch", "pytorch", "tensorflow", "spark", "kafka", "redis",
]);

function parseGitHubRepository(value: string): { owner: string; repo: string } | null {
  try {
    const url = new URL(value);
    if (url.hostname !== "github.com") return null;
    const [owner, repo] = url.pathname.split("/").filter(Boolean);
    if (!owner || !repo || !/^[\w.-]+$/.test(owner) || !/^[\w.-]+$/.test(repo)) return null;
    return { owner, repo: repo.replace(/\.git$/, "") };
  } catch { return null; }
}

function dependenciesFromManifest(path: string, content: string): string[] {
  if (path === "package.json") {
    try {
      const parsed = JSON.parse(content) as { dependencies?: Record<string, string>; devDependencies?: Record<string, string> };
      return [...Object.keys(parsed.dependencies ?? {}), ...Object.keys(parsed.devDependencies ?? {})];
    } catch { return []; }
  }
  if (path === "requirements.txt") return content.split("\n").map((line) => line.split(/[<>=!~[ ]/)[0].trim()).filter(Boolean);
  if (path === "go.mod") return content.match(/^\s*([\w./-]+)\s+v[\w.+-]+/gm)?.map((line) => line.trim().split(/\s+/)[0]) ?? [];
  if (path === "Cargo.toml") return content.match(/^\s*([\w-]+)\s*=\s*["{]/gm)?.map((line) => line.split("=")[0].trim()) ?? [];
  return content.match(/^\s*([\w-]+)(?:\[[^\]]*\])?\s*(?:[<>=!~].*)?$/gm)?.map((line) => line.trim().split(/[<>=!~[ ]/)[0]) ?? [];
}

async function githubJson<T>(path: string): Promise<T> {
  const response = await fetch(`https://api.github.com${path}`, {
    headers: {
      accept: "application/vnd.github+json", "user-agent": "adoptrank-project-reference",
      ...(process.env.GITHUB_TOKEN ? { authorization: `Bearer ${process.env.GITHUB_TOKEN}` } : {}),
    }, signal: AbortSignal.timeout(10_000), cache: "no-store",
  });
  if (!response.ok) throw new Error(`GitHub returned ${response.status}`);
  return response.json() as Promise<T>;
}

async function inspectPublicRepository(owner: string, repo: string): Promise<ProjectContext> {
  const [metadata, languages, manifests] = await Promise.all([
    githubJson<{ name: string; description: string | null }>(`/repos/${owner}/${repo}`),
    githubJson<Record<string, number>>(`/repos/${owner}/${repo}/languages`),
    Promise.all(MANIFEST_PATHS.map(async (path) => {
      try {
        const file = await githubJson<{ content?: string; encoding?: string }>(`/repos/${owner}/${repo}/contents/${path}`);
        if (file.encoding !== "base64" || !file.content) return [];
        return dependenciesFromManifest(path, Buffer.from(file.content, "base64").toString("utf8").slice(0, 50_000));
      } catch { return []; }
    })),
  ]);
  const dependencies = [...new Set(manifests.flat())].slice(0, 100);
  const frameworks = dependencies.filter((dependency) => FRAMEWORKS.has(dependency.toLowerCase().replace(/^@/, "")));
  const languageNames = Object.keys(languages).slice(0, 8);
  return {
    root_name: metadata.name, languages: languageNames, frameworks, dependencies, symbols: [],
    summary: `Public GitHub project ${owner}/${repo}: ${metadata.description ?? "No repository description."} Languages: ${languageNames.join(", ") || "unknown"}.`,
  };
}

async function rank(feature: string, projectContext: ProjectContext) {
  if (!process.env.RANKER_API_URL) throw new Error("The hosted ranker is not configured");
  const endpoint = new URL("/v1/search", process.env.RANKER_API_URL);
  const response = await fetch(endpoint, {
    method: "POST", headers: { "content-type": "application/json", ...(process.env.RANKER_API_KEY ? { "x-adoptrank-key": process.env.RANKER_API_KEY } : {}) },
    body: JSON.stringify({ query: feature, limit: 8, project_context: projectContext }), signal: AbortSignal.timeout(55_000), cache: "no-store",
  });
  if (!response.ok) throw new Error(`ranker returned ${response.status}`);
  return response.json();
}

export async function POST(request: NextRequest) {
  let body: ProjectReferenceRequest;
  try { body = await request.json() as ProjectReferenceRequest; } catch { return NextResponse.json({ error: "The request body must be valid JSON." }, { status: 400 }); }
  const feature = typeof body.feature === "string" ? body.feature.trim() : "";
  const repositoryUrl = typeof body.repositoryUrl === "string" ? body.repositoryUrl.trim() : "";
  const repository = parseGitHubRepository(repositoryUrl);
  if (feature.length < 4 || feature.length > 500) return NextResponse.json({ error: "Describe the feature in 4–500 characters." }, { status: 400 });
  if (!repository) return NextResponse.json({ error: "Enter a public GitHub repository URL, such as https://github.com/vercel/next.js." }, { status: 400 });
  try {
    const project = await inspectPublicRepository(repository.owner, repository.repo);
    return NextResponse.json({ project, ...(await rank(feature, project)) });
  } catch (error) {
    console.error("Project reference search failed", error instanceof Error ? error.message : "unknown error");
    return NextResponse.json({ error: "We could not inspect that public repository or rank references right now." }, { status: 503, headers: { "Retry-After": "30" } });
  }
}
