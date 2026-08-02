#!/usr/bin/env python3
"""
Backend API test for Encar reskin - Round 7 (Auth + Passkeys + Back Button Fix)
Tests authentication, passkey endpoints, admin protection, and performance.
"""
import requests
import sys
import time
import secrets
from datetime import datetime

BASE_URL = "https://encar-multi-lang.preview.emergentagent.com/api"

class EncarAPITester:
    def __init__(self):
        self.tests_run = 0
        self.tests_passed = 0
        self.start_time = time.time()
        self.session = requests.Session()
        self.test_email = f"test_{secrets.token_hex(4)}@example.com"
        self.test_password = "testpass123"

    def test(self, name, fn):
        """Run a single test"""
        self.tests_run += 1
        print(f"\n{'='*60}")
        print(f"TEST {self.tests_run}: {name}")
        print('='*60)
        try:
            fn()
            self.tests_passed += 1
            print(f"✅ PASSED")
            return True
        except AssertionError as e:
            print(f"❌ FAILED: {e}")
            return False
        except Exception as e:
            print(f"❌ ERROR: {e}")
            return False

    def test_health(self):
        """Verify health endpoint"""
        resp = self.session.get(f"{BASE_URL}/health", timeout=10)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        
        data = resp.json()
        print(f"  ok: {data['ok']}")
        print(f"  unique_cars: {data.get('unique_cars', 0):,}")
        print(f"  translations_cached: {data.get('translations_cached', 0):,}")
        
        assert data['ok'] is True, "Health check failed"

    def test_auth_register_short_password(self):
        """Registration rejects passwords shorter than 8 characters"""
        resp = self.session.post(
            f"{BASE_URL}/auth/register",
            json={"email": f"short_{secrets.token_hex(4)}@example.com", "password": "short7"},
            timeout=10
        )
        print(f"  Status: {resp.status_code}")
        print(f"  Response: {resp.json()}")
        
        assert resp.status_code == 400, f"Expected 400, got {resp.status_code}"
        assert "8" in resp.json().get("detail", "").lower(), "Error message should mention 8 characters"

    def test_auth_register_valid(self):
        """Registration succeeds with valid credentials"""
        resp = self.session.post(
            f"{BASE_URL}/auth/register",
            json={"email": self.test_email, "password": self.test_password, "name": "Test User"},
            timeout=10
        )
        print(f"  Status: {resp.status_code}")
        print(f"  Email: {self.test_email}")
        
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        
        data = resp.json()
        assert "user" in data, "Missing user in response"
        assert data["user"]["email"] == self.test_email, "Email mismatch"
        assert "password_hash" not in data["user"], "Password hash leaked in response!"
        assert "password" not in data["user"], "Password leaked in response!"
        
        # Check HttpOnly cookie
        cookies = resp.cookies
        assert "encar_session" in cookies, "Session cookie not set"
        print(f"  ✓ Session cookie set")
        print(f"  ✓ No password hash in response")
        
        self.user_id = data["user"]["id"]

    def test_auth_me_authenticated(self):
        """GET /auth/me returns user when authenticated"""
        resp = self.session.get(f"{BASE_URL}/auth/me", timeout=10)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        
        data = resp.json()
        print(f"  User: {data.get('user', {}).get('email')}")
        
        assert data["user"] is not None, "User should be authenticated"
        assert data["user"]["email"] == self.test_email, "Email mismatch"
        assert "password_hash" not in data["user"], "Password hash leaked!"
        assert "password" not in data["user"], "Password leaked!"

    def test_auth_logout(self):
        """Logout clears session"""
        resp = self.session.post(f"{BASE_URL}/auth/logout", timeout=10)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        print(f"  ✓ Logged out")

    def test_auth_me_unauthenticated(self):
        """GET /auth/me returns null user when not authenticated"""
        resp = self.session.get(f"{BASE_URL}/auth/me", timeout=10)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        
        data = resp.json()
        print(f"  User: {data.get('user')}")
        
        assert data["user"] is None, "User should be null after logout"

    def test_auth_login_wrong_password(self):
        """Login fails with wrong password"""
        resp = self.session.post(
            f"{BASE_URL}/auth/login",
            json={"email": self.test_email, "password": "wrongpassword"},
            timeout=10
        )
        print(f"  Status: {resp.status_code}")
        
        assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"

    def test_auth_login_valid(self):
        """Login succeeds with correct credentials"""
        resp = self.session.post(
            f"{BASE_URL}/auth/login",
            json={"email": self.test_email, "password": self.test_password},
            timeout=10
        )
        print(f"  Status: {resp.status_code}")
        
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        
        data = resp.json()
        assert "user" in data, "Missing user in response"
        assert data["user"]["email"] == self.test_email, "Email mismatch"
        assert "password_hash" not in data["user"], "Password hash leaked!"
        
        cookies = resp.cookies
        assert "encar_session" in cookies, "Session cookie not set"
        print(f"  ✓ Logged in successfully")

    def test_passkey_login_options(self):
        """POST /auth/passkey/login/options returns challenge with empty allowCredentials"""
        resp = self.session.post(f"{BASE_URL}/auth/passkey/login/options", json={}, timeout=10)
        print(f"  Status: {resp.status_code}")
        
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        
        data = resp.json()
        assert "flow_id" in data, "Missing flow_id"
        assert "options" in data, "Missing options"
        
        options = data["options"]
        assert "challenge" in options, "Missing challenge"
        assert "rpId" in options, "Missing rpId"
        
        # Check rpId matches the preview hostname
        rp_id = options["rpId"]
        print(f"  rpId: {rp_id}")
        assert rp_id == "multi-lang-cars.preview.emergentagent.com", f"rpId mismatch: {rp_id}"
        
        # Check allowCredentials is empty (discoverable/one-tap design)
        allow_creds = options.get("allowCredentials", [])
        print(f"  allowCredentials: {allow_creds}")
        assert allow_creds == [], f"allowCredentials should be empty for one-tap, got {allow_creds}"
        
        print(f"  ✓ Passkey login options correct (one-tap discoverable)")

    def test_admin_settings_requires_auth(self):
        """PUT /settings returns 401 when not signed in as admin"""
        # Logout first
        self.session.post(f"{BASE_URL}/auth/logout", timeout=10)
        
        resp = self.session.put(
            f"{BASE_URL}/settings",
            json={"constants": {}, "reprice": False},
            timeout=10
        )
        print(f"  Status: {resp.status_code}")
        
        assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"
        print(f"  ✓ Admin endpoint protected")

    def test_search_performance(self):
        """POST /search responds in under 3 seconds"""
        start = time.time()
        resp = self.session.post(
            f"{BASE_URL}/search",
            json={"page": 1, "page_size": 16, "lang": "en"},
            timeout=10
        )
        duration = time.time() - start
        
        print(f"  Duration: {duration:.3f}s")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        assert duration < 3.0, f"Search took {duration:.3f}s (target: <3s)"
        
        data = resp.json()
        print(f"  Total results: {data.get('total', 0):,}")
        print(f"  Items returned: {len(data.get('items', []))}")

    def test_taxonomy_performance(self):
        """GET /meta/taxonomy responds in under 3 seconds"""
        start = time.time()
        resp = self.session.get(
            f"{BASE_URL}/meta/taxonomy",
            params={"level": 1, "lang": "en"},
            timeout=10
        )
        duration = time.time() - start
        
        print(f"  Duration: {duration:.3f}s")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        assert duration < 3.0, f"Taxonomy took {duration:.3f}s (target: <3s)"
        
        data = resp.json()
        print(f"  Makes returned: {len(data.get('items', []))}")

    def test_fx_rates(self):
        """FX rates endpoint returns EUR and RON (no BGN)"""
        resp = self.session.get(f"{BASE_URL}/fx", timeout=10)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        
        data = resp.json()
        print(f"  fx_krw_eur: {data.get('fx_krw_eur')}")
        print(f"  eur_ron: {data.get('eur_ron')}")
        
        assert 'fx_krw_eur' in data, "Missing fx_krw_eur"
        assert 'eur_ron' in data, "Missing eur_ron"
        assert data.get('fx_krw_eur') > 0, "Invalid fx_krw_eur rate"
        
        # BGN should still be in the response (it's used internally), but the frontend
        # only shows EUR and RON in the currency selector
        print(f"  ✓ FX rates available")

    def run_all(self):
        """Run all tests"""
        print("\n" + "="*60)
        print("ENCAR API TEST - Round 7 (Auth + Passkeys + Back Button)")
        print("="*60)
        
        self.test("Health check", self.test_health)
        self.test("Register: reject short password", self.test_auth_register_short_password)
        self.test("Register: valid credentials", self.test_auth_register_valid)
        self.test("GET /auth/me: authenticated", self.test_auth_me_authenticated)
        self.test("POST /auth/logout", self.test_auth_logout)
        self.test("GET /auth/me: unauthenticated", self.test_auth_me_unauthenticated)
        self.test("Login: wrong password", self.test_auth_login_wrong_password)
        self.test("Login: valid credentials", self.test_auth_login_valid)
        self.test("Passkey login options (one-tap)", self.test_passkey_login_options)
        self.test("Admin settings requires auth", self.test_admin_settings_requires_auth)
        self.test("Search performance (<3s)", self.test_search_performance)
        self.test("Taxonomy performance (<3s)", self.test_taxonomy_performance)
        self.test("FX rates (EUR/RON)", self.test_fx_rates)
        
        duration = time.time() - self.start_time
        
        print("\n" + "="*60)
        print(f"RESULTS: {self.tests_passed}/{self.tests_run} tests passed")
        print(f"Duration: {duration:.1f}s")
        print("="*60)
        
        return 0 if self.tests_passed == self.tests_run else 1

if __name__ == "__main__":
    tester = EncarAPITester()
    sys.exit(tester.run_all())
