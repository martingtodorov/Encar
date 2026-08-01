#!/usr/bin/env python3
"""
Backend API test for Encar reskin - Round 3 (Native Dropdowns + Full Sync)
Tests API functionality during ongoing 436-page catalogue sync.
"""
import requests
import sys
import time
from datetime import datetime

BASE_URL = "https://encar-proxy-layer.preview.emergentagent.com/api"

class EncarAPITester:
    def __init__(self):
        self.tests_run = 0
        self.tests_passed = 0
        self.start_time = time.time()

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

    def test_health_during_sync(self):
        """Verify health endpoint shows sync progress"""
        resp = requests.get(f"{BASE_URL}/health", timeout=10)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        
        data = resp.json()
        print(f"  ok: {data['ok']}")
        print(f"  listings_total: {data['listings_total']:,}")
        print(f"  unique_cars: {data['unique_cars']:,}")
        print(f"  duplicate_ads_hidden: {data['duplicate_ads_hidden']:,}")
        print(f"  sync.status: {data['sync']['status']}")
        print(f"  sync.pages_done: {data['sync']['pages_done']}/{data['sync']['pages_total']}")
        print(f"  sync.listings_upstream: {data['sync']['listings_upstream']:,}")
        print(f"  encar_stats.backoffs: {data['encar_stats']['backoffs']}")
        print(f"  encar_stats.errors: {data['encar_stats']['errors']}")
        
        assert data['ok'] is True, "Health check failed"
        assert data['listings_total'] > 0, "No listings in database"
        assert data['sync']['status'] in ['running', 'completed'], f"Unexpected sync status: {data['sync']['status']}"
        assert data['encar_stats']['backoffs'] <= 2, f"Too many backoffs: {data['encar_stats']['backoffs']}"
        
        # Store for later comparison
        self.initial_listings = data['listings_total']
        self.sync_pages_done = data['sync']['pages_done']
        self.sync_pages_total = data['sync']['pages_total']

    def test_search_default(self):
        """Search with no filters returns results"""
        resp = requests.post(
            f"{BASE_URL}/search",
            json={"page": 1, "page_size": 10, "lang": "en"},
            timeout=10
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        
        data = resp.json()
        print(f"  total: {data['total']:,}")
        print(f"  items: {len(data['items'])}")
        print(f"  pages: {data['pages']}")
        
        assert data['total'] > 0, "No results returned"
        assert len(data['items']) == 10, f"Expected 10 items, got {len(data['items'])}"
        assert data['pages'] > 0, "No pages"

    def test_taxonomy_level1_makes(self):
        """Taxonomy level 1 returns makes with counts"""
        resp = requests.get(
            f"{BASE_URL}/meta/taxonomy",
            params={"level": 1, "lang": "en"},
            timeout=10
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        
        data = resp.json()
        print(f"  items: {len(data['items'])}")
        
        assert len(data['items']) > 0, "No makes returned"
        
        # Check first few items
        for i, item in enumerate(data['items'][:5]):
            print(f"    {i+1}. {item['label']} ({item['count']})")
            assert 'value' in item, "Missing 'value' field"
            assert 'label' in item, "Missing 'label' field"
            assert 'count' in item, "Missing 'count' field"
            assert item['count'] > 0, f"Zero count for {item['label']}"

    def test_taxonomy_level2_models(self):
        """Taxonomy level 2 returns models for a make"""
        # First get a make
        resp = requests.get(f"{BASE_URL}/meta/taxonomy", params={"level": 1, "lang": "en"}, timeout=10)
        makes = resp.json()['items']
        assert len(makes) > 0, "No makes to test with"
        
        test_make = makes[0]['value']
        print(f"  Testing with make: {test_make}")
        
        resp = requests.get(
            f"{BASE_URL}/meta/taxonomy",
            params={"level": 2, "make": test_make, "lang": "en"},
            timeout=10
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        
        data = resp.json()
        print(f"  models: {len(data['items'])}")
        
        assert len(data['items']) > 0, f"No models for make {test_make}"
        
        for i, item in enumerate(data['items'][:3]):
            print(f"    {i+1}. {item['label']} ({item['count']})")

    def test_taxonomy_level3_submodels(self):
        """Taxonomy level 3 returns submodels (badges)"""
        # Get make and model
        resp = requests.get(f"{BASE_URL}/meta/taxonomy", params={"level": 1, "lang": "en"}, timeout=10)
        makes = resp.json()['items']
        test_make = makes[0]['value']
        
        resp = requests.get(f"{BASE_URL}/meta/taxonomy", params={"level": 2, "make": test_make, "lang": "en"}, timeout=10)
        models = resp.json()['items']
        assert len(models) > 0, "No models to test with"
        test_model = models[0]['value']
        
        print(f"  Testing with make: {test_make}, model: {test_model}")
        
        resp = requests.get(
            f"{BASE_URL}/meta/taxonomy",
            params={"level": 3, "make": test_make, "model": test_model, "lang": "en"},
            timeout=10
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        
        data = resp.json()
        print(f"  submodels: {len(data['items'])}")
        
        # Submodels may be empty for some makes/models
        if len(data['items']) > 0:
            for i, item in enumerate(data['items'][:3]):
                print(f"    {i+1}. {item['label']} ({item['count']})")

    def test_search_with_taxonomy(self):
        """Search filtered by make returns correct results"""
        # Get a make
        resp = requests.get(f"{BASE_URL}/meta/taxonomy", params={"level": 1, "lang": "en"}, timeout=10)
        makes = resp.json()['items']
        test_make = makes[0]['value']
        
        print(f"  Searching for make: {test_make}")
        
        resp = requests.post(
            f"{BASE_URL}/search",
            json={"makes": [test_make], "page": 1, "page_size": 10, "lang": "en"},
            timeout=10
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        
        data = resp.json()
        print(f"  total: {data['total']:,}")
        print(f"  items: {len(data['items'])}")
        
        assert data['total'] > 0, f"No results for make {test_make}"
        assert len(data['items']) > 0, "No items returned"

    def test_car_detail_performance(self):
        """Detail page loads in under 4 seconds"""
        # Get a car ID from search
        resp = requests.post(
            f"{BASE_URL}/search",
            json={"page": 1, "page_size": 1, "lang": "en"},
            timeout=10
        )
        items = resp.json()['items']
        assert len(items) > 0, "No cars to test with"
        
        car_id = items[0]['id']
        print(f"  Testing car ID: {car_id}")
        
        start = time.time()
        resp = requests.get(f"{BASE_URL}/car/{car_id}", params={"lang": "en"}, timeout=10)
        duration = time.time() - start
        
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        
        data = resp.json()
        print(f"  Load time: {duration:.3f}s")
        print(f"  Photos: {len(data.get('photos', []))}")
        print(f"  Has insurance: {data.get('insurance') is not None}")
        print(f"  Has diagnosis: {data.get('diagnosis') is not None}")
        
        assert duration < 4.0, f"Detail page took {duration:.3f}s (target: <4s)"
        assert len(data.get('photos', [])) > 0, "No photos"

    def test_filters_metadata(self):
        """Filters endpoint returns metadata"""
        resp = requests.get(f"{BASE_URL}/meta/filters", params={"lang": "en"}, timeout=10)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        
        data = resp.json()
        print(f"  fuels: {len(data.get('fuels', []))}")
        print(f"  transmissions: {len(data.get('transmissions', []))}")
        print(f"  regions: {len(data.get('regions', []))}")
        
        assert 'fuels' in data, "Missing fuels"
        assert 'transmissions' in data, "Missing transmissions"

    def test_fx_rates(self):
        """FX rates endpoint returns currency data"""
        resp = requests.get(f"{BASE_URL}/fx", timeout=10)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        
        data = resp.json()
        print(f"  fx_krw_eur: {data.get('fx_krw_eur')}")
        print(f"  eur_bgn: {data.get('eur_bgn')}")
        print(f"  eur_ron: {data.get('eur_ron')}")
        print(f"  source: {data.get('source')}")
        
        assert 'fx_krw_eur' in data, "Missing fx_krw_eur"
        assert data.get('fx_krw_eur') > 0, "Invalid fx_krw_eur rate"
        assert 'eur_bgn' in data, "Missing eur_bgn"
        assert 'eur_ron' in data, "Missing eur_ron"

    def test_sync_still_progressing(self):
        """Verify sync is still making progress (or completed)"""
        time.sleep(2)  # Wait a bit
        
        resp = requests.get(f"{BASE_URL}/health", timeout=10)
        data = resp.json()
        
        current_listings = data['listings_total']
        current_pages = data['sync']['pages_done']
        
        print(f"  Initial listings: {self.initial_listings:,}")
        print(f"  Current listings: {current_listings:,}")
        print(f"  Initial pages: {self.sync_pages_done}/{self.sync_pages_total}")
        print(f"  Current pages: {current_pages}/{self.sync_pages_total}")
        
        if data['sync']['status'] == 'completed':
            print(f"  ✓ Sync completed during test run")
        else:
            # Sync should be progressing or at least stable
            assert current_listings >= self.initial_listings, "Listings count decreased"
            print(f"  ✓ Sync still running, listings stable/growing")

    def run_all(self):
        """Run all tests"""
        print("\n" + "="*60)
        print("ENCAR API TEST - Round 3 (Native Dropdowns + Full Sync)")
        print("="*60)
        
        self.test("Health check during sync", self.test_health_during_sync)
        self.test("Search with default params", self.test_search_default)
        self.test("Taxonomy level 1 (makes)", self.test_taxonomy_level1_makes)
        self.test("Taxonomy level 2 (models)", self.test_taxonomy_level2_models)
        self.test("Taxonomy level 3 (submodels)", self.test_taxonomy_level3_submodels)
        self.test("Search with taxonomy filter", self.test_search_with_taxonomy)
        self.test("Car detail performance (<4s)", self.test_car_detail_performance)
        self.test("Filters metadata", self.test_filters_metadata)
        self.test("FX rates", self.test_fx_rates)
        self.test("Sync progress check", self.test_sync_still_progressing)
        
        duration = time.time() - self.start_time
        
        print("\n" + "="*60)
        print(f"RESULTS: {self.tests_passed}/{self.tests_run} tests passed")
        print(f"Duration: {duration:.1f}s")
        print("="*60)
        
        return 0 if self.tests_passed == self.tests_run else 1

if __name__ == "__main__":
    tester = EncarAPITester()
    sys.exit(tester.run_all())
