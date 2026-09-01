"""Backend tests for description translation streaming + AI usage/budget/report admin routes.

Covers review request iteration 44:
  * SSE description translation for 3+ Korean listings, 4 languages, fluent output, no Hangul
  * Cache path: 2nd request served fast, does NOT write a new ai_calls row
  * ai_calls metering (ok + failed rows recorded with cost/tokens/error)
  * /admin/ai-usage shape + auth
  * PUT /admin/ai-budget clamps + persists
  * POST /admin/ai-report/send stores doc + returns 200 even if email fails
  * Regression: normal search still works, records description kind in ai_calls

NOTE: single-class layout is deliberate. `--dist loadscope` pins the whole class to ONE
xdist worker, which serialises the streaming calls so we don't accidentally rate-limit
Gemini with parallel requests from two workers.
"""
import json
import os
import time

import httpx
import pymongo
import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
ADMIN_HDR = {"x-admin-token": ADMIN_TOKEN}

# listings that have Korean detail.contents.text
KOREAN_LISTINGS = ["42379471", "42379220", "41834945", "42345245"]
LANGS = ["bg", "en", "ro", "pl"]


# ---------- helpers ----------

def _has_hangul(s):
    return any("\uac00" <= ch <= "\ud7a3" for ch in s or "")


def _stream_translate(listing_id, lang, timeout=120):
    url = f"{BASE_URL}/api/car/{listing_id}/translate-description/stream?lang={lang}"
    chunks, done, err = [], False, None
    t0 = time.monotonic()
    with httpx.stream("GET", url, timeout=timeout) as r:
        assert r.status_code == 200, f"stream {listing_id}/{lang} -> {r.status_code}"
        for raw in r.iter_lines():
            if not raw or not raw.startswith("data:"):
                continue
            payload = json.loads(raw[5:].strip())
            if "chunk" in payload:
                chunks.append(payload["chunk"])
            elif payload.get("done"):
                done = True
                break
            elif payload.get("error"):
                err = payload["error"]
                break
    return chunks, done, err, time.monotonic() - t0


def _stream_with_retry(listing_id, lang, tries=2):
    """Rate limits/parallel test noise can transient-fail Gemini; retry once."""
    last = ("", None, "no attempt", 0)
    for i in range(tries):
        chunks, done, err, el = _stream_translate(listing_id, lang)
        if done and not err:
            return chunks, done, err, el
        last = (chunks, done, err, el)
        time.sleep(4 + i * 3)
    return last


def _db():
    c = pymongo.MongoClient(os.environ["MONGO_URL"])
    return c[os.environ["DB_NAME"]]


# ============================================================================
# Backed by ONE class so `--dist loadscope` serialises the streaming calls.
# ============================================================================

class TestAiIter44:
    """End-to-end suite for the iteration-44 review request."""

    # ---------- description streaming ----------

    def test_A1_cached_listing_streams_translated_text(self):
        chunks, done, err, elapsed = _stream_translate("42379471", "bg")
        assert done and not err, f"no done frame for cached listing: err={err}"
        full = "".join(chunks)
        assert full, "no chunks received"
        assert not _has_hangul(full), (
            f"Bulgarian output still contains Hangul: {full[:200]}")

    @pytest.mark.parametrize("listing_id,lang", [
        (lid, l) for lid in KOREAN_LISTINGS[1:] for l in LANGS])
    def test_A2_fresh_translations_all_langs(self, listing_id, lang):
        chunks, done, err, elapsed = _stream_with_retry(listing_id, lang)
        assert done and not err, (
            f"stream failed listing={listing_id} lang={lang} err={err}")
        full = "".join(chunks)
        assert len(full) > 20, (
            f"suspiciously short output ({len(full)} chars) for "
            f"{listing_id}/{lang}: {full!r}")
        assert not _has_hangul(full), (
            f"Hangul leaked into {lang} translation of {listing_id}: {full[:200]}")

    def test_A3_cache_second_request_fast_no_new_ai_call(self):
        """Iter 44 spec: 2nd request must return in <3s and NOT add an ai_calls row."""
        db = _db()
        # warm the cache
        _stream_with_retry("42379220", "bg")
        time.sleep(1.0)
        before = db.ai_calls.count_documents({})
        chunks, done, err, elapsed = _stream_translate("42379220", "bg")
        # metering write is fire-and-forget → wait a bit before recount
        time.sleep(1.5)
        after = db.ai_calls.count_documents({})
        assert done and not err
        assert elapsed < 3.0, f"cached second request was slow: {elapsed:.2f}s"
        assert after == before, (
            f"cache miss on 2nd request: ai_calls grew {before} -> {after}")

    # ---------- ai_calls metering ----------

    def test_B1_ai_calls_has_recent_description_rows(self):
        db = _db()
        # ensure at least one description call happened
        _stream_with_retry("41834945", "en")
        time.sleep(1.5)
        docs = list(db.ai_calls.find({"kind": "description"}).sort("ts", -1).limit(30))
        assert docs, "no ai_calls rows with kind=description"
        ok_rows = [d for d in docs if d.get("ok")]
        assert ok_rows, "no successful description ai_calls rows found"
        r = ok_rows[0]
        for k in ("ts", "day", "provider", "model", "kind", "lang", "in_tokens",
                  "out_tokens", "cost_usd", "ok", "ms"):
            assert k in r, f"missing field {k} in ai_calls doc: {list(r)}"
        assert r["in_tokens"] > 0
        assert r["out_tokens"] > 0
        assert r["cost_usd"] > 0
        assert r["ok"] is True

    def test_B2_failed_rows_have_error_string(self):
        # ANTHROPIC_API_KEY is invalid in preview so failed anthropic rows exist
        db = _db()
        docs = list(db.ai_calls.find({"ok": False}).limit(5))
        assert docs, "no failed ai_calls rows to check (unexpected in preview)"
        for r in docs:
            assert r.get("error"), f"failed row missing error string: {r}"

    # ---------- admin /ai-usage ----------

    def test_C1_ai_usage_requires_admin(self):
        assert requests.get(f"{BASE_URL}/api/admin/ai-usage?days=7").status_code == 401
        assert requests.get(f"{BASE_URL}/api/admin/ai-usage?days=7",
                            headers={"x-admin-token": "nope"}).status_code == 401

    @pytest.mark.parametrize("days", [7, 30, 90])
    def test_C2_ai_usage_shape_billing_unavailable(self, days):
        r = requests.get(f"{BASE_URL}/api/admin/ai-usage?days={days}", headers=ADMIN_HDR)
        assert r.status_code == 200
        d = r.json()
        assert d["days"] == days
        assert isinstance(d["budget_usd"], (int, float))
        # ANTHROPIC_ADMIN_KEY not set in preview
        assert d["billing"]["available"] is False
        for key in ("reports", "today", "week", "month", "period", "series",
                    "by_kind", "by_model", "errors", "breaker", "cache"):
            assert key in d, f"missing {key}"
        assert len(d["series"]) == days
        for c in ("phrases", "descriptions", "description_lines"):
            assert c in d["cache"]
        for row in d["series"]:
            assert "day" in row and "calls" in row and "cost" in row

    # ---------- admin /ai-budget ----------

    def test_D1_budget_requires_admin(self):
        r = requests.put(f"{BASE_URL}/api/admin/ai-budget", json={"daily_usd": 7.5})
        assert r.status_code == 401

    def test_D2_budget_persists_and_clamps(self):
        r = requests.put(f"{BASE_URL}/api/admin/ai-budget",
                         json={"daily_usd": 7.5}, headers=ADMIN_HDR)
        assert r.status_code == 200, r.text
        assert r.json()["daily_usd"] == 7.5
        got = requests.get(f"{BASE_URL}/api/admin/ai-usage?days=7",
                           headers=ADMIN_HDR).json()
        assert got["budget_usd"] == 7.5
        # clamp upper
        assert requests.put(f"{BASE_URL}/api/admin/ai-budget", json={"daily_usd": 5000},
                            headers=ADMIN_HDR).json()["daily_usd"] == 1000
        # clamp lower
        assert requests.put(f"{BASE_URL}/api/admin/ai-budget", json={"daily_usd": 0.001},
                            headers=ADMIN_HDR).json()["daily_usd"] == 0.5
        # restore
        assert requests.put(f"{BASE_URL}/api/admin/ai-budget", json={"daily_usd": 5},
                            headers=ADMIN_HDR).json()["daily_usd"] == 5.0

    # ---------- admin /ai-report/send ----------

    def test_E1_report_requires_admin(self):
        assert requests.post(f"{BASE_URL}/api/admin/ai-report/send").status_code == 401

    def test_E2_report_send_stores_and_returns_200(self):
        r = requests.post(f"{BASE_URL}/api/admin/ai-report/send", headers=ADMIN_HDR)
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ("day", "cost_est", "calls", "by_kind", "by_model"):
            assert k in d, f"missing {k}"
        # verify Mongo has the doc
        assert _db().ai_reports.find_one({"_id": d["day"]}), "report doc not persisted"
        # verify ai-usage surfaces it
        got = requests.get(f"{BASE_URL}/api/admin/ai-usage?days=7",
                           headers=ADMIN_HDR).json()
        assert d["day"] in [r["day"] for r in got["reports"]]

    # ---------- Regression: normal search still works ----------

    def test_F1_search_returns_translated_rows(self):
        r = requests.post(f"{BASE_URL}/api/search", json={
            "lang": "bg", "page": 1, "page_size": 6, "sort": "newest"
        })
        assert r.status_code == 200, r.text
        body = r.json()
        items = body.get("items") or body.get("rows") or body.get("cars") or []
        assert items, f"empty search results: keys={list(body)[:10]}"
        row = items[0]
        assert any(k.endswith("_t") for k in row.keys()), (
            f"no *_t translated fields: {list(row)[:20]}")

    def test_F2_ai_calls_contains_description_kind(self):
        kinds = _db().ai_calls.distinct("kind")
        assert "description" in kinds, f"description kind missing: {kinds}"
