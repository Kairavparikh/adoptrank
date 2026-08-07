import { neon } from "@neondatabase/serverless";
import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const maxDuration = 60;

const fallbackIds = [
  "salesforce/merlion",
  "yzhao062/pyod",
  "seldonio/alibi-detect",
  "online-ml/river",
  "feast-dev/feast",
  "nautechsystems/nautilus_trader",
];

type ProjectContext = {
  root_name?: string;
  languages?: string[];
  frameworks?: string[];
  dependencies?: string[];
  symbols?: string[];
  summary?: string;
};

type ContextSearchBody = {
  query?: unknown;
  limit?: unknown;
  project_context?: ProjectContext | null;
};

async function callRanker(payload: { query: string; limit: number; project_context?: ProjectContext | null }) {
  if (!process.env.RANKER_API_URL) throw new Error("The hosted ranker is not configured");
  const rankerUrl = new URL("/v1/search", process.env.RANKER_API_URL);
  const response = await fetch(rankerUrl, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      ...(process.env.RANKER_API_KEY ? { "x-adoptrank-key": process.env.RANKER_API_KEY } : {}),
    },
    body: JSON.stringify(payload),
    signal: AbortSignal.timeout(55_000),
    cache: "no-store",
  });
  if (!response.ok) throw new Error(`ranker returned ${response.status}`);
  return response.json() as Promise<{
    results: Array<{ full_name: string }>;
    model_version: string;
    data_watermark: string | null;
  }>;
}

export async function POST(request: NextRequest) {
  let body: ContextSearchBody;
  try {
    body = await request.json() as ContextSearchBody;
  } catch {
    return NextResponse.json({ error: "The request body must be valid JSON." }, { status: 400 });
  }
  const query = typeof body.query === "string" ? body.query.trim() : "";
  if (query.length < 2 || query.length > 500) {
    return NextResponse.json({ error: "Query length must be between 2 and 500 characters." }, { status: 400 });
  }
  const requestedLimit = typeof body.limit === "number" ? body.limit : 10;
  const limit = Math.max(1, Math.min(25, Math.trunc(requestedLimit)));
  try {
    const payload = await callRanker({
      query,
      limit,
      project_context: body.project_context ?? null,
    });
    return NextResponse.json({
      ...payload,
      ids: payload.results.map((result) => result.full_name),
      source: "pytorch",
      freshness: payload.data_watermark,
      modelVersion: payload.model_version,
    });
  } catch (error) {
    console.error("Contextual PyTorch ranker failed", error instanceof Error ? error.message : "unknown error");
    return NextResponse.json(
      { error: "Contextual ranking is temporarily unavailable." },
      { status: 503, headers: { "Retry-After": "30" } },
    );
  }
}

export async function GET(request: NextRequest) {
  const query = request.nextUrl.searchParams.get("q")?.trim();
  if (!query) return NextResponse.json({ error: "A search query is required." }, { status: 400 });

  if (process.env.RANKER_API_URL) {
    try {
      const rankerUrl = new URL("/v1/search", process.env.RANKER_API_URL);
      rankerUrl.searchParams.set("query", query);
      rankerUrl.searchParams.set("limit", "20");
      const response = await fetch(rankerUrl, {
        headers: process.env.RANKER_API_KEY ? { "x-adoptrank-key": process.env.RANKER_API_KEY } : {},
        // Leave five seconds for the proxy to serialize a response after a
        // scale-to-zero GPU cold start. Warm requests normally finish much sooner.
        signal: AbortSignal.timeout(55_000),
        cache: "no-store",
      });
      if (!response.ok) throw new Error(`ranker returned ${response.status}`);
      const payload = await response.json() as {
        results: Array<{ full_name: string }>;
        model_version: string;
        data_watermark: string | null;
      };
      return NextResponse.json({
        ids: payload.results.map((result) => result.full_name),
        results: payload.results,
        source: "pytorch",
        freshness: payload.data_watermark,
        modelVersion: payload.model_version,
      });
    } catch (error) {
      console.error("PyTorch ranker failed", error instanceof Error ? error.message : "unknown error");
    }
  }

  if (!process.env.DATABASE_URL) {
    return NextResponse.json({ ids: fallbackIds, source: "preview", freshness: null });
  }

  try {
    const sql = neon(process.env.DATABASE_URL);
    const rows = await sql.query(
      "select full_name, rank_score, observed_at from search_repositories($1, $2)",
      [query, 20],
    ) as Array<{ full_name: string; rank_score: number; observed_at: string | null }>;

    return NextResponse.json({
      ids: rows.map((row) => row.full_name),
      source: "postgres",
      freshness: rows[0]?.observed_at ?? null,
    });
  } catch (error) {
    console.error("Postgres search failed", error instanceof Error ? error.message : "unknown error");
    return NextResponse.json({ ids: fallbackIds, source: "preview", freshness: null });
  }
}
