import { neon } from "@neondatabase/serverless";
import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

const fallbackIds = [
  "salesforce/merlion",
  "yzhao062/pyod",
  "seldonio/alibi-detect",
  "online-ml/river",
  "feast-dev/feast",
  "nautechsystems/nautilus_trader",
];

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
        signal: AbortSignal.timeout(8_000),
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
