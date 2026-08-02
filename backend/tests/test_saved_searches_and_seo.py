"""Tests for saved-searches sync (PUT/GET/merge), robots.txt / sitemap.xml,
and language redirects."""
import os
import uuid
import pytest
import requests

def _load_env():
    envp = "/app/frontend/.env"
    if os.path.exists(envp):
        with open(envp) as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    return line.split("=", 1)[1].strip()
    return os.environ.get("REACT_APP_BACKEND_URL", "")


BASE_URL = _load_env().rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL not configured"
ADMIN_EMAIL = "admin@encarskin.com"
ADMIN_PASS = "AdminTest2026!"


@pytest.fixture
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture
def authed(client):
    r = client.post(f"{BASE_URL}/api/auth/login",
                    json={"email": ADMIN_EMAIL, "password": ADMIN_PASS})
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return client


# ---------- Saved searches CRUD & merge -------------------------------------
class TestSavedSearches:
    def test_get_initial(self, authed):
        r = authed.get(f"{BASE_URL}/api/auth/saved-searches")
        assert r.status_code == 200
        assert "items" in r.json()

    def test_put_and_persist(self, authed):
        sid = f"TEST_{uuid.uuid4().hex[:10]}"
        payload = {"items": [{
            "id": sid,
            "name": "TEST search",
            "query": "year_min=2020&only_inspection=1",
            "seen_total": 42,
            "alerts": False,
            "created_at": "2026-01-01T00:00:00Z",
        }]}
        r = authed.put(f"{BASE_URL}/api/auth/saved-searches", json=payload)
        assert r.status_code == 200
        items = r.json()["items"]
        assert any(it["id"] == sid for it in items)
        found = next(it for it in items if it["id"] == sid)
        assert found["query"] == "year_min=2020&only_inspection=1"
        assert found["seen_total"] == 42
        assert found["name"] == "TEST search"

        # GET verifies persistence
        g = authed.get(f"{BASE_URL}/api/auth/saved-searches")
        assert g.status_code == 200
        assert any(it["id"] == sid for it in g.json()["items"])

        # /auth/me includes saved_searches
        me = authed.get(f"{BASE_URL}/api/auth/me").json()["user"]
        assert "saved_searches" in me
        assert any(it["id"] == sid for it in me["saved_searches"])

    def test_dedupe_and_cap(self, authed):
        sid = f"TEST_{uuid.uuid4().hex[:10]}"
        payload = {"items": [
            {"id": sid, "name": "A", "query": "q=a"},
            {"id": sid, "name": "dup", "query": "q=a"},  # duplicate id, dropped
        ]}
        r = authed.put(f"{BASE_URL}/api/auth/saved-searches", json=payload)
        assert r.status_code == 200
        matches = [it for it in r.json()["items"] if it["id"] == sid]
        assert len(matches) == 1

    def test_merge_folds_local_into_account(self, authed):
        # first PUT one item (server side)
        sid_a = f"TEST_A_{uuid.uuid4().hex[:8]}"
        authed.put(f"{BASE_URL}/api/auth/saved-searches", json={"items": [
            {"id": sid_a, "name": "server", "query": "q=server"}
        ]})
        # merge in a "local" item with a different query
        sid_b = f"TEST_B_{uuid.uuid4().hex[:8]}"
        r = authed.post(f"{BASE_URL}/api/auth/saved-searches/merge", json={"items": [
            {"id": sid_b, "name": "local", "query": "q=local"}
        ]})
        assert r.status_code == 200
        items = r.json()["items"]
        queries = [it["query"] for it in items]
        assert "q=server" in queries
        assert "q=local" in queries

    def test_merge_no_duplicate_query(self, authed):
        sid = f"TEST_M_{uuid.uuid4().hex[:8]}"
        q = f"q=merge_{uuid.uuid4().hex[:6]}"
        # put server side
        authed.put(f"{BASE_URL}/api/auth/saved-searches", json={"items": [
            {"id": sid, "name": "srv", "query": q}
        ]})
        # merge same query with different id -> should NOT duplicate
        r = authed.post(f"{BASE_URL}/api/auth/saved-searches/merge", json={"items": [
            {"id": sid + "_dup", "name": "loc", "query": q}
        ]})
        assert r.status_code == 200
        items = [it for it in r.json()["items"] if it["query"] == q]
        assert len(items) == 1, f"query duplicated: {items}"

    def test_cleanup(self, authed):
        # remove TEST_ items to keep the account tidy
        cur = authed.get(f"{BASE_URL}/api/auth/saved-searches").json()["items"]
        keep = [it for it in cur if not it["id"].startswith("TEST_")]
        r = authed.put(f"{BASE_URL}/api/auth/saved-searches", json={"items": keep})
        assert r.status_code == 200

    def test_auth_required(self, client):
        r = client.get(f"{BASE_URL}/api/auth/saved-searches")
        assert r.status_code == 401


# ---------- SEO endpoints ---------------------------------------------------
class TestSEOEndpoints:
    def test_robots(self, client):
        r = client.get(f"{BASE_URL}/robots.txt")
        assert r.status_code == 200
        assert len(r.text.strip()) > 0

    def test_sitemap(self, client):
        r = client.get(f"{BASE_URL}/sitemap.xml")
        assert r.status_code == 200
        body = r.text
        assert "<urlset" in body or "<sitemapindex" in body
        # sitemap should reference /bg, /ro, /en
        assert "/bg" in body
        assert "/ro" in body
        assert "/en" in body


# ---------- Language redirect (frontend routing served through same host) ---
class TestLangRedirect:
    def test_bare_root_serves_html(self, client):
        # SPA is served by the frontend host — verify that root returns HTML and
        # that /bg /ro /en all resolve too. Client-side redirect happens in JS,
        # so we just verify the HTML shell is served (200).
        r = client.get(f"{BASE_URL}/")
        assert r.status_code == 200
        assert "<div id=\"root\"" in r.text or "<div id='root'" in r.text

    @pytest.mark.parametrize("path", ["/bg", "/ro", "/en", "/en/saved",
                                       "/en/how-it-works", "/en/searches"])
    def test_prefixed_paths_serve_shell(self, client, path):
        r = client.get(f"{BASE_URL}{path}")
        assert r.status_code == 200
        assert "root" in r.text
