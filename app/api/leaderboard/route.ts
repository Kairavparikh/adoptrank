import { neon } from "@neondatabase/serverless";
import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const maxDuration = 30;

const windows = new Set([1, 7, 30, 90]);
const sorts = new Set([
  "overall",
  "adoption",
  "maintenance",
  "quality",
  "depth",
  "originality",
  "attention",
  "momentum",
  "stars",
]);
const labels = new Set(["Emerging", "Durable", "Hidden gem", "Overhyped", "At risk"]);

function clean(value: string | null) {
  const result = value?.trim();
  return result || null;
}

function integer(value: string | null, fallback: number) {
  if (value === null) return fallback;
  if (!/^\d+$/.test(value)) return null;
  return Number(value);
}

export async function GET(request: NextRequest) {
  if (!process.env.DATABASE_URL) {
    return NextResponse.json({ error: "Leaderboard database is unavailable." }, { status: 503 });
  }

  const params = request.nextUrl.searchParams;
  const owner = clean(params.get("owner"));
  const language = clean(params.get("language"));
  const license = clean(params.get("license"));
  const status = clean(params.get("status"));
  const windowDays = integer(params.get("window"), 30);
  const requestedSort = params.get("sort") ?? "overall";
  const page = integer(params.get("page"), 1);
  const limit = integer(params.get("limit"), 25);
  if (owner && owner.length > 39) {
    return NextResponse.json({ error: "Owner must be at most 39 characters." }, { status: 400 });
  }
  if (language && language.length > 50) {
    return NextResponse.json({ error: "Language must be at most 50 characters." }, { status: 400 });
  }
  if (license && license.length > 50) {
    return NextResponse.json({ error: "License must be at most 50 characters." }, { status: 400 });
  }
  if (status && !labels.has(status)) {
    return NextResponse.json({ error: "Unsupported status filter." }, { status: 400 });
  }
  if (windowDays === null || !windows.has(windowDays)) {
    return NextResponse.json({ error: "Window must be one of 1, 7, 30, or 90." }, { status: 400 });
  }
  if (!sorts.has(requestedSort)) {
    return NextResponse.json({ error: "Unsupported leaderboard sort." }, { status: 400 });
  }
  if (page === null || page < 1 || page > 10_000) {
    return NextResponse.json({ error: "Page must be an integer from 1 to 10000." }, { status: 400 });
  }
  if (limit === null || limit < 5 || limit > 50) {
    return NextResponse.json({ error: "Limit must be an integer from 5 to 50." }, { status: 400 });
  }
  const offset = (page - 1) * limit;

  try {
    const sql = neon(process.env.DATABASE_URL);
    const [rows, languageRows, licenseRows] = await Promise.all([
      sql.query(
        "select * from leaderboard_repositories($1,$2,$3,$4,$5,$6,$7,$8)",
        [owner, language, license, status, windowDays, requestedSort, limit, offset],
      ),
      sql.query(
        "select distinct language from repositories where not is_archived and language is not null order by language limit 100",
        [],
      ),
      sql.query(
        "select distinct license_spdx from repositories where not is_archived and license_spdx is not null order by license_spdx limit 100",
        [],
      ),
    ]);
    const typedRows = rows as Array<Record<string, unknown>>;
    const total = typedRows.length ? Number(typedRows[0].total_count) : 0;
    const items = typedRows.map((row) => ({
      fullName: row.full_name,
      owner: row.owner,
      name: row.name,
      description: row.description,
      language: row.language,
      license: row.license_spdx,
      topics: row.topics,
      stars: Number(row.stars ?? 0),
      forks: Number(row.forks ?? 0),
      updatedAt: row.github_updated_at,
      score: Number(row.score ?? 0),
      adoptionScore: Number(row.adoption_score ?? 0),
      maintenanceScore: Number(row.maintenance_score ?? 0),
      qualityScore: Number(row.quality_score ?? 0),
      depthScore: Number(row.depth_score ?? 0),
      originalityScore: Number(row.originality_score ?? 0),
      attentionScore: Number(row.attention_score ?? 0),
      confidence: Number(row.confidence ?? 0),
      status: row.label,
      globalRank: Number(row.global_rank),
      rankDelta: row.rank_delta === null ? null : Number(row.rank_delta),
      scoreDelta: row.score_delta === null ? null : Number(row.score_delta),
      dataWatermark: row.data_watermark,
      explanation: row.explanation,
      url: `https://github.com/${row.full_name}`,
    }));

    return NextResponse.json(
      {
        items,
        page,
        limit,
        total,
        totalPages: Math.max(1, Math.ceil(total / limit)),
        dataWatermark: items[0]?.dataWatermark ?? null,
        source: "neon-leaderboard",
        filters: {
          languages: (languageRows as Array<{ language: string }>).map((row) => row.language),
          licenses: (licenseRows as Array<{ license_spdx: string }>).map((row) => row.license_spdx),
          statuses: [...labels],
          windows: [...windows],
          sorts: [...sorts],
        },
      },
      {
        headers: {
          "Cache-Control": "public, s-maxage=60, stale-while-revalidate=300",
        },
      },
    );
  } catch (error) {
    console.error("Leaderboard query failed", error instanceof Error ? error.message : "unknown error");
    return NextResponse.json({ error: "Leaderboard query failed." }, { status: 500 });
  }
}
