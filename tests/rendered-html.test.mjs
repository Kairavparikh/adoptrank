import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("ships the AdoptRank product contract", async () => {
  const [page, layout, searchRoute, leaderboard, leaderboardRoute, cli] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/api/search/route.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/components/Leaderboard.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/api/leaderboard/route.ts", import.meta.url), "utf8"),
    readFile(new URL("../backend/src/adoptrank_backend/cli.py", import.meta.url), "utf8"),
  ]);

  assert.match(page, /Find open source/);
  assert.match(page, /Leaderboard/);
  assert.match(page, /Evidence, not opinion/);
  assert.match(page, /adoptrank find/);
  assert.match(layout, /AdoptRank/);
  assert.match(searchRoute, /Postgres|postgres|DATABASE_URL/);
  assert.match(searchRoute, /RANKER_API_URL/);
  assert.match(searchRoute, /pytorch/);
  assert.match(searchRoute, /export async function POST/);
  assert.match(searchRoute, /project_context/);
  assert.match(leaderboard, /GitHub username or organization/);
  assert.match(leaderboard, /Measure adoption over/);
  assert.match(leaderboardRoute, /leaderboard_repositories/);
  assert.match(leaderboardRoute, /owner/);
  assert.match(cli, /commands\.add_parser\("leaderboard"\)/);
  assert.match(cli, /https:\/\/adoptrank\.vercel\.app/);
  assert.doesNotMatch(page, /codex-preview|Your site is taking shape/i);
});
