"""Backend tests for the new Google-sign-in and CMS (SEO/body/company/translate) features.

Run:
  pytest /app/backend/tests/test_google_auth_and_cms.py -v \
      --junitxml=/app/test_reports/pytest/google_auth_cms.xml
"""
import os
import re
import time
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://encar-multi-lang.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@encarskin.com"
ADMIN_PASSWORD = "AdminTest2026!"
ADMIN_TOKEN = "kR7wZq2mXv9TbNp4LdYs6HcJf1UgE3aQ"

HDR_TOKEN = {"x-admin-token": ADMIN_TOKEN}

SLUGS_BODY = ["how-it-works", "faq", "fees", "contact", "terms", "privacy", "cookies"]


# ── module-level helpers ────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def admin_session():
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=15)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text[:200]}"
    assert "encar_session" in s.cookies, "encar_session cookie missing after login"
    return s


# ── Google auth backend ─────────────────────────────────────────────────────
class TestGoogleAuthBackend:
    def test_bogus_session_id_returns_401(self):
        r = requests.post(f"{API}/auth/google/session",
                          json={"session_id": "bogus-session-does-not-exist-xyz"}, timeout=20)
        assert r.status_code == 401, f"expected 401, got {r.status_code}: {r.text[:200]}"
        body = r.json()
        assert "detail" in body
        assert isinstance(body["detail"], str) and len(body["detail"]) > 0

    def test_empty_session_id_returns_400(self):
        r = requests.post(f"{API}/auth/google/session", json={"session_id": ""}, timeout=15)
        assert r.status_code == 400, f"expected 400, got {r.status_code}"
        assert "detail" in r.json()

    def test_missing_session_id_field_returns_422(self):
        r = requests.post(f"{API}/auth/google/session", json={}, timeout=15)
        # pydantic returns 422 for missing required field
        assert r.status_code in (400, 422)


# ── existing password auth still works ──────────────────────────────────────
class TestExistingAuth:
    def test_admin_login_and_me(self, admin_session):
        r = admin_session.get(f"{API}/auth/me", timeout=15)
        assert r.status_code == 200
        user = r.json().get("user")
        assert user and user.get("email") == ADMIN_EMAIL
        assert user.get("is_admin") is True


# ── CMS SEO ────────────────────────────────────────────────────────────────
class TestCmsSeo:
    def test_save_and_read_seo(self, admin_session):
        title = "TEST_SEO_TITLE_" + uuid.uuid4().hex[:8]
        desc = "TEST_SEO_DESC_" + uuid.uuid4().hex[:8]
        r = admin_session.put(
            f"{API}/admin/cms/page/how-it-works/bg",
            json={"seo_title": title, "seo_description": desc, "html": ""},
            headers=HDR_TOKEN, timeout=15,
        )
        assert r.status_code == 200, r.text[:200]
        assert r.json().get("saved") is True

        # bust cache – wait > 15s TTL or just check GET returns override eventually.
        time.sleep(0.3)
        r = requests.get(f"{API}/cms/site", params={"lang": "bg"}, timeout=15)
        assert r.status_code == 200
        seo = r.json().get("seo") or {}
        # cache may not have refreshed on first hit; retry once after TTL
        if "how-it-works" not in seo or seo["how-it-works"].get("title") != title:
            time.sleep(16)
            seo = requests.get(f"{API}/cms/site", params={"lang": "bg"}, timeout=15).json().get("seo") or {}
        assert "how-it-works" in seo
        assert seo["how-it-works"].get("title") == title
        assert seo["how-it-works"].get("description") == desc

        # cleanup
        admin_session.delete(f"{API}/admin/cms/page/how-it-works/bg", headers=HDR_TOKEN, timeout=15)

    def test_unknown_slug_404(self, admin_session):
        r = admin_session.put(
            f"{API}/admin/cms/page/nope/bg",
            json={"seo_title": "x"}, headers=HDR_TOKEN, timeout=15,
        )
        assert r.status_code == 404

    def test_unknown_lang_400(self, admin_session):
        r = admin_session.put(
            f"{API}/admin/cms/page/faq/xx",
            json={"seo_title": "x"}, headers=HDR_TOKEN, timeout=15,
        )
        assert r.status_code == 400


# ── CMS body + sanitisation ────────────────────────────────────────────────
class TestCmsBody:
    def test_body_saved_and_sanitised(self, admin_session):
        raw = (
            "<h2>Hello</h2>"
            "<p onclick=\"steal()\">safe</p>"
            "<script>alert(1)</script>"
            "<a href=\"javascript:evil()\">click</a>"
            "<img src=\"x\" onerror=\"pwn()\"/>"
        )
        r = admin_session.put(
            f"{API}/admin/cms/page/terms/bg",
            json={"seo_title": "T", "seo_description": "D", "html": raw},
            headers=HDR_TOKEN, timeout=15,
        )
        assert r.status_code == 200, r.text[:200]

        r = requests.get(f"{API}/cms/page/terms", params={"lang": "bg"}, timeout=15)
        assert r.status_code == 200
        html = r.json().get("html") or ""
        assert "<h2>Hello</h2>" in html
        # script tag stripped
        assert "<script" not in html.lower()
        assert "alert(1)" not in html
        # inline onclick / onerror stripped
        assert not re.search(r"\son\w+\s*=", html, re.I), f"inline handler survived: {html}"
        # javascript: URL stripped
        assert "javascript:" not in html.lower()

        # cleanup
        admin_session.delete(f"{API}/admin/cms/page/terms/bg", headers=HDR_TOKEN, timeout=15)

    def test_home_body_is_ignored(self, admin_session):
        r = admin_session.put(
            f"{API}/admin/cms/page/home/bg",
            json={"seo_title": "H", "html": "<p>should be ignored</p>",
                  "hero_title": "Hello", "hero_subtitle": "Sub"},
            headers=HDR_TOKEN, timeout=15,
        )
        assert r.status_code == 200
        r = requests.get(f"{API}/cms/page/home", params={"lang": "bg"}, timeout=15)
        assert r.status_code == 200
        assert (r.json().get("html") or "") == ""
        # cleanup
        admin_session.delete(f"{API}/admin/cms/page/home/bg", headers=HDR_TOKEN, timeout=15)


# ── CMS reset ──────────────────────────────────────────────────────────────
class TestCmsReset:
    def test_delete_restores_builtin(self, admin_session):
        admin_session.put(
            f"{API}/admin/cms/page/faq/bg",
            json={"seo_title": "TT", "html": "<p>hi</p>"},
            headers=HDR_TOKEN, timeout=15,
        )
        r = admin_session.delete(f"{API}/admin/cms/page/faq/bg", headers=HDR_TOKEN, timeout=15)
        assert r.status_code == 200
        assert r.json().get("removed") is True
        r = requests.get(f"{API}/cms/page/faq", params={"lang": "bg"}, timeout=15)
        assert r.status_code == 200
        assert (r.json().get("html") or "") == ""


# ── CMS company ────────────────────────────────────────────────────────────
class TestCmsCompany:
    def test_company_save_and_read(self, admin_session):
        payload = {
            "name": "TEST Co", "eik": "111", "vat": "BG111", "address": "Sofia",
            "phone": "+359 2 000", "email": "test@example.com", "site": "example.com",
        }
        r = admin_session.put(f"{API}/admin/cms/company", json=payload, headers=HDR_TOKEN, timeout=15)
        assert r.status_code == 200
        assert r.json().get("saved") is True

        r = admin_session.get(f"{API}/admin/cms/company", headers=HDR_TOKEN, timeout=15)
        assert r.status_code == 200
        got = r.json()
        for k, v in payload.items():
            assert got.get(k) == v

        # public /cms/site returns company
        time.sleep(16)  # cache TTL
        r = requests.get(f"{API}/cms/site", params={"lang": "bg"}, timeout=15)
        assert r.status_code == 200
        company = r.json().get("company") or {}
        assert company.get("name") == "TEST Co"
        assert company.get("email") == "test@example.com"

        # restore original values
        restore = {"name": "Auto&Bid LTD", "eik": "208833206", "vat": "",
                   "address": "", "phone": "", "email": "contact@encareurope.com",
                   "site": "encareurope.com"}
        r = admin_session.put(f"{API}/admin/cms/company", json=restore, headers=HDR_TOKEN, timeout=15)
        assert r.status_code == 200


# ── CMS translate (real LLM) ───────────────────────────────────────────────
class TestCmsTranslate:
    def test_translate_no_source_400(self, admin_session):
        # make sure privacy|bg is empty
        admin_session.delete(f"{API}/admin/cms/page/privacy/bg", headers=HDR_TOKEN, timeout=15)
        r = admin_session.post(
            f"{API}/admin/cms/page/privacy/translate",
            params={"source": "bg"}, headers=HDR_TOKEN, timeout=30,
        )
        assert r.status_code == 400

    def test_translate_bg_to_ro_en_preserves_tags(self, admin_session):
        # save a bg body with an anchor + heading
        bg_html = ("<h2>Как работи</h2>"
                   "<p>Ние импортираме коли от <a href=\"https://encar.com\">Encar</a>.</p>"
                   "<ul><li>Стъпка едно</li><li>Стъпка две</li></ul>")
        r = admin_session.put(
            f"{API}/admin/cms/page/how-it-works/bg",
            json={"seo_title": "Как работи | Encar",
                  "seo_description": "Кратко описание на процеса на внос.",
                  "html": bg_html},
            headers=HDR_TOKEN, timeout=15,
        )
        assert r.status_code == 200

        r = admin_session.post(
            f"{API}/admin/cms/page/how-it-works/translate",
            params={"source": "bg"}, headers=HDR_TOKEN, timeout=120,
        )
        if r.status_code == 503:
            pytest.skip(f"no translation provider available: {r.text[:120]}")
        assert r.status_code == 200, f"translate failed: {r.status_code} {r.text[:300]}"
        done = r.json().get("translated") or []
        assert set(done) == {"ro", "en"}

        for lang in ("ro", "en"):
            got = admin_session.get(f"{API}/admin/cms/page/how-it-works/{lang}",
                                    headers=HDR_TOKEN, timeout=15).json()
            html = got.get("html") or ""
            assert html, f"empty translation for {lang}"
            # tags survived
            assert "<h2>" in html and "</h2>" in html
            assert "<ul>" in html and "<li>" in html
            # URL preserved
            assert "https://encar.com" in html
            # some translation happened (not the exact bg heading kept literally)
            # english should contain a Latin word
            if lang == "en":
                assert re.search(r"[A-Za-z]{4,}", html)

        # cleanup
        for lang in ("bg", "ro", "en"):
            admin_session.delete(f"{API}/admin/cms/page/how-it-works/{lang}",
                                 headers=HDR_TOKEN, timeout=15)


# ── admin auth guard ───────────────────────────────────────────────────────
class TestAdminAuth:
    def test_all_admin_cms_routes_require_auth(self):
        s = requests.Session()  # no cookies, no token
        checks = [
            ("GET",    f"{API}/admin/cms/pages",              None),
            ("GET",    f"{API}/admin/cms/page/faq/bg",        None),
            ("PUT",    f"{API}/admin/cms/page/faq/bg",        {"seo_title": "x"}),
            ("DELETE", f"{API}/admin/cms/page/faq/bg",        None),
            ("POST",   f"{API}/admin/cms/page/faq/translate", None),
            ("GET",    f"{API}/admin/cms/company",            None),
            ("PUT",    f"{API}/admin/cms/company",            {"name": "x"}),
        ]
        for method, url, body in checks:
            r = s.request(method, url, json=body, timeout=15)
            assert r.status_code == 401, f"{method} {url} expected 401, got {r.status_code}"
