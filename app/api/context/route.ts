import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const maxDuration = 60;

type ContextBody = {
  query?: unknown;
  token_budget?: unknown;
  limit?: unknown;
  project_context?: unknown;
};

export async function POST(request: NextRequest) {
  let body: ContextBody;
  try {
    body = await request.json() as ContextBody;
  } catch {
    return NextResponse.json({ error: "The request body must be valid JSON." }, { status: 400 });
  }

  const query = typeof body.query === "string" ? body.query.trim() : "";
  if (query.length < 2 || query.length > 500) {
    return NextResponse.json({ error: "Query length must be between 2 and 500 characters." }, { status: 400 });
  }
  const requestedBudget = typeof body.token_budget === "number" ? Math.trunc(body.token_budget) : 2000;
  const tokenBudget = Math.max(200, Math.min(20_000, requestedBudget));
  const requestedLimit = typeof body.limit === "number" ? Math.trunc(body.limit) : 5;
  const limit = Math.max(1, Math.min(10, requestedLimit));

  if (!process.env.RANKER_API_URL) {
    return NextResponse.json({ error: "The hosted context ranker is not configured." }, { status: 503 });
  }

  try {
    const rankerUrl = new URL("/v1/context", process.env.RANKER_API_URL);
    const response = await fetch(rankerUrl, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        ...(process.env.RANKER_API_KEY ? { "x-adoptrank-key": process.env.RANKER_API_KEY } : {}),
      },
      body: JSON.stringify({
        query,
        token_budget: tokenBudget,
        limit,
        project_context: body.project_context ?? null,
      }),
      signal: AbortSignal.timeout(55_000),
      cache: "no-store",
    });
    if (!response.ok) throw new Error(`ranker returned ${response.status}`);
    return NextResponse.json(await response.json());
  } catch (error) {
    console.error("Context evidence ranker failed", error instanceof Error ? error.message : "unknown error");
    return NextResponse.json(
      { error: "External code evidence is temporarily unavailable." },
      { status: 503, headers: { "Retry-After": "30" } },
    );
  }
}
