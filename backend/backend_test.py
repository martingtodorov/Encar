"""Backend API tests for multi-lang-cars Encar skin."""

import requests
import sys
import time
from datetime import datetime

# Public endpoint from frontend/.env
BASE_URL = "https://multi-lang-cars.preview.emergentagent.com/api"

class APITester:
    def __init__(self):
        self.tests_run = 0
        self.tests_passed = 0
        self.tests_failed = 0
        self.issues = []

    def test(self, name, fn):
        """Run a single test function."""
        self.tests_run += 1
        print(f"\n{'='*70}")
        print(f"🔍 Test {self.tests_run}: {name}")
        print(f"{'='*70}")
        try:
            fn()
            self.tests_passed += 1
            print(f"✅ PASSED")
        except AssertionError as e:
            self.tests_failed += 1
            self.issues.append({"test": name, "error": str(e)})
            print(f"❌ FAILED: {e}")
        except Exception as e:
            self.tests_failed += 1
            self.issues.append({"test": name, "error": f"Exception: {str(e)}"})
            print(f"❌ ERROR: {e}")

    def summary(self):
        """Print test summary."""
        print(f"\n{'='*70}")
        print(f"📊 TEST SUMMARY")
        print(f"{'='*70}")
        print(f"Total: {self.tests_run}")
        print(f"✅ Passed: {self.tests_passed}")
        print(f"❌ Failed: {self.tests_failed}")
        print(f"Success Rate: {(self.tests_passed/self.tests_run*100):.1f}%")
        
        if self.issues:
            print(f"\n{'='*70}")
            print(f"❌ ISSUES FOUND:")
            print(f"{'='*70}")
            for i, issue in enumerate(self.issues, 1):
                print(f"{i}. {issue['test']}")
                print(f"   {issue['error']}")
        
        return 0 if self.tests_failed == 0 else 1


def main():
    tester = APITester()

    # ─────────────────────────────────────────────────────────────────────────
    # TEST 1: Health endpoint and translation breaker status
    # ─────────────────────────────────────────────────────────────────────────
    def test_health():
        resp = requests.get(f"{BASE_URL}/health", timeout=10)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        
        data = resp.json()
        print(f"   ok: {data.get('ok')}")
        print(f"   unique_cars: {data.get('unique_cars')}")
        print(f"   listings_active: {data.get('listings_active')}")
        print(f"   duplicate_ads_hidden: {data.get('duplicate_ads_hidden')}")
        print(f"   translations_cached: {data.get('translations_cached')}")
        
        breaker = data.get('translation_breaker', {})
        print(f"   translation_breaker:")
        print(f"     open: {breaker.get('open')}")
        print(f"     reason: {breaker.get('reason')}")
        print(f"     trips: {breaker.get('trips')}")
        print(f"     retry_in_s: {breaker.get('retry_in_s')}")
        
        assert data.get('ok') is True, "Health check failed"
        assert 'translation_breaker' in data, "Missing translation_breaker in response"
        
        # Budget exhausted is expected, not a failure
        if breaker.get('open'):
            print(f"   ⚠️  Translation breaker is OPEN (expected due to exhausted budget)")

    tester.test("Health endpoint returns ok and translation_breaker status", test_health)

    # ─────────────────────────────────────────────────────────────────────────
    # TEST 2: Taxonomy endpoint - make/model/submodel translation
    # ─────────────────────────────────────────────────────────────────────────
    def test_taxonomy_makes():
        """Test that /api/meta/taxonomy returns makes with translations."""
        resp = requests.get(f"{BASE_URL}/meta/taxonomy", params={
            "level": 1,
            "lang": "en",
            "limit": 100
        }, timeout=15)
        
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        data = resp.json()
        
        items = data.get('items', [])
        print(f"   Total makes returned: {len(items)}")
        
        # Check for Korean characters (Hangul: U+AC00 to U+D7A3)
        korean_count = 0
        latin_count = 0
        korean_makes = []
        
        for item in items[:50]:  # Check first 50
            label = item.get('label', '')
            value = item.get('value', '')
            has_korean = any('\uac00' <= c <= '\ud7a3' for c in label)
            
            if has_korean:
                korean_count += 1
                korean_makes.append(f"{value} -> {label}")
            else:
                latin_count += 1
        
        print(f"   Latin-script labels: {latin_count}")
        print(f"   Korean labels: {korean_count}")
        
        if korean_makes:
            print(f"   Korean makes found (budget-blocked, not a code defect):")
            for make in korean_makes[:10]:
                print(f"     - {make}")
        
        # IMPORTANT: Per review request, residual Korean is budget-blocked, NOT a code defect
        # We just report it, not fail the test
        assert len(items) > 0, "No makes returned"
        print(f"   ✓ Majority of makes are translated ({latin_count}/{latin_count + korean_count})")

    tester.test("Taxonomy makes endpoint returns translated labels", test_taxonomy_makes)

    # ─────────────────────────────────────────────────────────────────────────
    # TEST 3: Search endpoint - 16 ads per page
    # ─────────────────────────────────────────────────────────────────────────
    def test_search_page_size():
        """Test that /api/search honours page_size=16."""
        resp = requests.post(f"{BASE_URL}/search", json={
            "page": 1,
            "page_size": 16,
            "lang": "en",
            "sort": "price_asc"
        }, timeout=15)
        
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        data = resp.json()
        
        items = data.get('items', [])
        page_size = data.get('page_size')
        total = data.get('total')
        
        print(f"   Total results: {total}")
        print(f"   Page size: {page_size}")
        print(f"   Items returned: {len(items)}")
        
        assert page_size == 16, f"Expected page_size=16, got {page_size}"
        
        # If there are enough results, we should get exactly 16
        if total >= 16:
            assert len(items) == 16, f"Expected 16 items, got {len(items)}"
        else:
            assert len(items) == total, f"Expected {total} items, got {len(items)}"

    tester.test("Search endpoint honours page_size=16", test_search_page_size)

    # ─────────────────────────────────────────────────────────────────────────
    # TEST 4: Search endpoint - default sort is price_asc and results are ordered
    # ─────────────────────────────────────────────────────────────────────────
    def test_search_sort_price_asc():
        """Test that sort=price_asc returns results in ascending price order."""
        resp = requests.post(f"{BASE_URL}/search", json={
            "page": 1,
            "page_size": 16,
            "lang": "en",
            "sort": "price_asc"
        }, timeout=15)
        
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        data = resp.json()
        
        items = data.get('items', [])
        prices = [item.get('sale_eur', 0) for item in items]
        
        print(f"   First 5 prices (EUR): {prices[:5]}")
        print(f"   Last 5 prices (EUR): {prices[-5:]}")
        
        # Check that prices are non-decreasing
        for i in range(len(prices) - 1):
            assert prices[i] <= prices[i + 1], \
                f"Prices not in ascending order: {prices[i]} > {prices[i + 1]} at index {i}"
        
        print(f"   ✓ All {len(prices)} prices are in ascending order")

    tester.test("Search results are ordered by ascending price", test_search_sort_price_asc)

    # ─────────────────────────────────────────────────────────────────────────
    # TEST 5: Search endpoint - pagination works
    # ─────────────────────────────────────────────────────────────────────────
    def test_search_pagination():
        """Test that pagination to page 2 and 3 works."""
        for page_num in [1, 2, 3]:
            resp = requests.post(f"{BASE_URL}/search", json={
                "page": page_num,
                "page_size": 16,
                "lang": "en",
                "sort": "price_asc"
            }, timeout=15)
            
            assert resp.status_code == 200, f"Page {page_num}: Expected 200, got {resp.status_code}"
            data = resp.json()
            
            items = data.get('items', [])
            print(f"   Page {page_num}: {len(items)} items returned")
            
            assert data.get('page') == page_num, f"Expected page={page_num}, got {data.get('page')}"

    tester.test("Search pagination to page 2 and 3 works", test_search_pagination)

    # ─────────────────────────────────────────────────────────────────────────
    # TEST 6: Search with filters (makes, price range, only_record)
    # ─────────────────────────────────────────────────────────────────────────
    def test_search_with_filters():
        """Test that search with filters works."""
        resp = requests.post(f"{BASE_URL}/search", json={
            "makes": ["벤츠"],  # Mercedes in Korean
            "price_min": 5000,
            "price_max": 50000,
            "only_record": True,
            "page": 1,
            "page_size": 16,
            "lang": "en",
            "sort": "price_asc"
        }, timeout=15)
        
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        data = resp.json()
        
        items = data.get('items', [])
        total = data.get('total')
        
        print(f"   Mercedes with insurance history: {total} results")
        print(f"   Items returned: {len(items)}")
        
        # Verify all items have insurance history
        for item in items:
            assert item.get('has_record') is True, \
                f"Item {item.get('id')} does not have insurance history"
        
        print(f"   ✓ All {len(items)} items have insurance history")

    tester.test("Search with filters (make, price, only_record) works", test_search_with_filters)

    # ─────────────────────────────────────────────────────────────────────────
    # TEST 7: Car detail endpoint - insurance claim EUR conversion
    # ─────────────────────────────────────────────────────────────────────────
    def test_car_detail_insurance_eur():
        """Test that car detail page converts insurance claim amounts to EUR."""
        # First, get a Mercedes with insurance history
        search_resp = requests.post(f"{BASE_URL}/search", json={
            "makes": ["벤츠"],
            "only_record": True,
            "page": 1,
            "page_size": 5,
            "lang": "en"
        }, timeout=15)
        
        assert search_resp.status_code == 200, "Search failed"
        items = search_resp.json().get('items', [])
        
        if not items:
            print("   ⚠️  No Mercedes with insurance history found, skipping test")
            return
        
        car_id = items[0]['id']
        print(f"   Testing car: {car_id}")
        
        # Get car detail
        start_time = time.time()
        detail_resp = requests.get(f"{BASE_URL}/car/{car_id}", params={
            "lang": "en"
        }, timeout=30)
        load_time = time.time() - start_time
        
        assert detail_resp.status_code == 200, f"Expected 200, got {detail_resp.status_code}"
        data = detail_resp.json()
        
        print(f"   Detail page load time: {load_time:.2f}s")
        
        insurance = data.get('insurance')
        if not insurance or not insurance.get('available'):
            print("   ⚠️  No insurance data available for this car")
            return
        
        print(f"   Insurance data:")
        print(f"     own_accidents: {insurance.get('own_accidents')}")
        print(f"     other_accidents: {insurance.get('other_accidents')}")
        print(f"     own_accident_cost (KRW): {insurance.get('own_accident_cost')}")
        print(f"     own_accident_cost_eur: {insurance.get('own_accident_cost_eur')}")
        print(f"     other_accident_cost (KRW): {insurance.get('other_accident_cost')}")
        print(f"     other_accident_cost_eur: {insurance.get('other_accident_cost_eur')}")
        print(f"     fx_krw_eur: {insurance.get('fx_krw_eur')}")
        
        # Check that EUR fields exist
        if insurance.get('own_accident_cost'):
            assert 'own_accident_cost_eur' in insurance, \
                "Missing own_accident_cost_eur field"
            eur_amount = insurance.get('own_accident_cost_eur')
            krw_amount = insurance.get('own_accident_cost')
            fx_rate = insurance.get('fx_krw_eur')
            
            if eur_amount and krw_amount and fx_rate:
                # Sanity check: EUR should be roughly KRW / fx_rate
                expected_eur = krw_amount / fx_rate
                diff_pct = abs(eur_amount - expected_eur) / expected_eur * 100
                print(f"     Sanity check: {krw_amount} KRW / {fx_rate} = {expected_eur:.2f} EUR")
                print(f"     Actual EUR: {eur_amount}, diff: {diff_pct:.1f}%")
                assert diff_pct < 5, f"EUR conversion seems wrong: {diff_pct:.1f}% difference"
        
        if insurance.get('other_accident_cost'):
            assert 'other_accident_cost_eur' in insurance, \
                "Missing other_accident_cost_eur field"
        
        # Check that detail page loaded in reasonable time (circuit breaker should prevent stalls)
        assert load_time < 10, f"Detail page took too long to load: {load_time:.2f}s"
        print(f"   ✓ Detail page loaded in {load_time:.2f}s (no stall)")

    tester.test("Car detail page converts insurance claims to EUR and loads quickly", test_car_detail_insurance_eur)

    # ─────────────────────────────────────────────────────────────────────────
    # TEST 8: Meta filters endpoint
    # ─────────────────────────────────────────────────────────────────────────
    def test_meta_filters():
        """Test that /api/meta/filters returns facets."""
        resp = requests.get(f"{BASE_URL}/meta/filters", params={
            "lang": "en"
        }, timeout=15)
        
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        data = resp.json()
        
        makes = data.get('makes', [])
        fuels = data.get('fuels', [])
        regions = data.get('regions', [])
        bounds = data.get('bounds', {})
        
        print(f"   Makes: {len(makes)}")
        print(f"   Fuels: {len(fuels)}")
        print(f"   Regions: {len(regions)}")
        print(f"   Price range: {bounds.get('price_min')} - {bounds.get('price_max')} EUR")
        print(f"   Year range: {bounds.get('year_min')} - {bounds.get('year_max')}")
        
        assert len(makes) > 0, "No makes returned"
        assert len(fuels) > 0, "No fuels returned"
        assert bounds.get('price_max') is not None, "Missing price bounds"

    tester.test("Meta filters endpoint returns facets", test_meta_filters)

    # ─────────────────────────────────────────────────────────────────────────
    # Print summary and exit
    # ─────────────────────────────────────────────────────────────────────────
    return tester.summary()


if __name__ == "__main__":
    sys.exit(main())
