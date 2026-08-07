import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("ships the AdoptRank product contract", async () => {
  const [page, layout, searchRoute] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/api/search/route.ts", import.meta.url), "utf8"),
  ]);

  assert.match(page, /Find open source/);
  assert.match(page, /Evidence, not opinion/);
  assert.match(page, /adoptrank find/);
  assert.match(layout, /AdoptRank/);
  assert.match(searchRoute, /Postgres|postgres|DATABASE_URL/);
  assert.doesNotMatch(page, /codex-preview|Your site is taking shape/i);
});
