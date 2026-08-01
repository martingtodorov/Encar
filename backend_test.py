"""Backend API testing for Encar localized skin.

Tests all critical endpoints with timing measurements for the detail page bug fix.
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
        self.results = []

    def test(self, name, method, endpoint, expected_status=200, data=None, params=None, 
             headers=None, measure_time=False):
        """Run a single API test with optional timing."""
        url = f"{BASE_URL}{endpoint}"
        self.tests_run += 1
        
        print(f"\n🔍 Testing {name}...")
        start = time.time()
        
        try:
            if method == 'GET':
                response = requests.get(url, params=params, headers=headers, timeout=30)
            elif method == 'POST':
                response = requests.post(url, json=data, params=params, headers=headers, timeout=30)
            
            elapsed = time.time() - start
            success = response.status_code == expected_status
            
            if success:
                self.tests_passed += 1
                if measure_time:
                    print(f"✅ Passed - Status: {response.status_code} - Time: {elapsed:.3f}s")
                else:
                    print(f"✅ Passed - Status: {response.status_code}")
                
                result = {
                    "test": name,
                    "status": "PASS",
                    "status_code": response.status_code,
                    "time": elapsed
                }
                self.results.append(result)
                return True, response.json() if response.content else {}, elapsed
            else:
                print(f"❌ Failed - Expected {expected_status}, got {response.status_code}")
                print(f"   Response: {response.text[:200]}")
                result = {
                    "test": name,
                    "status": "FAIL",
                    "expected": expected_status,
                    "actual": response.status_code,
                    "time": elapsed
                }
                self.results.append(result)
                return False, {}, elapsed
                
        except Exception as e:
            elapsed = time.time() - start
            print(f"❌ Failed - Error: {str(e)}")
            result = {
                "test": name,
                "status": "ERROR",
                "error": str(e),
                "time": elapsed
            }
            self.results.append(result)
            return False, {}, elapsed

    def print_summary(self):
        """Print test summary."""
        print(f"\n{'='*60}")
        print(f"📊 TEST SUMMARY")
        print(f"{'='*60}")
        print(f"Total tests: {self.tests_run}")
        print(f"Passed: {self.tests_passed}")
        print(f"Failed: {self.tests_run - self.tests_passed}")
        print(f"Success rate: {(self.tests_passed/self.tests_run*100):.1f}%")
        print(f"{'='*60}\n")


def main():
    tester = EncarAPITester()
    
    print("="*60)
    print("ENCAR BACKEND API TESTS")
    print("="*60)
    
    # 1. Health check
    success, health_data, _ = tester.test("Health Check", "GET", "/health")
    if success:
        print(f"   Listings total: {health_data.get('listings_total', 0)}")
        print(f"   Unique cars: {health_data.get('unique_cars', 0)}")
        print(f"   Translations cached: {health_data.get('translations_cached', 0)}")
    
    # 2. FX rates
    tester.test("FX Rates", "GET", "/fx")
    
    # 3. Search with default params
    search_body = {
        "q": "",
        "makes": [],
        "models": [],
        "badges": [],
        "badge_details": [],
        "fuels": [],
        "regions": [],
        "transmissions": [],
        "sort": "newest",
        "page": 1,
        "page_size": 10,
        "lang": "bg"
    }
    success, search_data, _ = tester.test("Search - Default", "POST", "/search", 
                                          data=search_body)
    
    car_id = None
    if success and search_data.get('items'):
        print(f"   Found {search_data.get('total', 0)} total cars")
        print(f"   Returned {len(search_data.get('items', []))} items")
        car_id = search_data['items'][0]['id']
        print(f"   First car ID: {car_id}")
    
    # 4. Taxonomy level 1 (makes)
    tester.test("Taxonomy - Level 1 (Makes)", "GET", "/meta/taxonomy", 
                params={"level": 1, "lang": "bg"})
    
    # 5. Taxonomy level 2 (models for a make)
    # Get a make from search results first
    if success and search_data.get('items'):
        first_make = search_data['items'][0].get('manufacturer')
        if first_make:
            tester.test(f"Taxonomy - Level 2 (Models for {first_make})", "GET", 
                       "/meta/taxonomy", 
                       params={"level": 2, "make": first_make, "lang": "bg"})
    
    # 6. Filters metadata
    tester.test("Filters Metadata", "GET", "/meta/filters", params={"lang": "bg"})
    
    # 7. CRITICAL: Car detail page - FIRST LOAD (cold cache)
    # This is the PRIMARY BUG being tested
    if car_id:
        print("\n" + "="*60)
        print("🔥 PRIMARY BUG TEST: Car Detail Page Load Time")
        print("="*60)
        
        # Cold load (first time)
        success, detail_data, cold_time = tester.test(
            f"Car Detail - COLD LOAD (ID: {car_id})", 
            "GET", 
            f"/car/{car_id}",
            params={"lang": "bg", "refresh": "true"},
            measure_time=True
        )
        
        if success:
            print(f"\n   📸 Photos: {detail_data.get('photo_count', 0)}")
            print(f"   🛡️  Insurance: {'Available' if detail_data.get('insurance') else 'N/A'}")
            print(f"   📋 Inspection: {'Available' if detail_data.get('inspection') else 'N/A'}")
            print(f"   🔧 Diagnosis: {'Available' if detail_data.get('diagnosis') else 'N/A'}")
            print(f"   💰 Price quote: {'Available' if detail_data.get('quote') else 'N/A'}")
            print(f"   📝 Description pending: {detail_data.get('description_pending', False)}")
            
            # Warm load (cached)
            time.sleep(0.5)
            success2, detail_data2, warm_time = tester.test(
                f"Car Detail - WARM LOAD (ID: {car_id})", 
                "GET", 
                f"/car/{car_id}",
                params={"lang": "bg"},
                measure_time=True
            )
            
            print(f"\n   ⏱️  TIMING ANALYSIS:")
            print(f"   Cold load: {cold_time:.3f}s (target: <4s)")
            print(f"   Warm load: {warm_time:.3f}s (target: near-instant)")
            
            if cold_time > 4.0:
                print(f"   ⚠️  WARNING: Cold load exceeds 4s target!")
            else:
                print(f"   ✅ Cold load within target")
            
            if warm_time > 0.5:
                print(f"   ⚠️  WARNING: Warm load is slow (should be <0.5s)")
            else:
                print(f"   ✅ Warm load is fast")
    
    # 8. Pricing quote
    tester.test("Pricing Quote", "GET", "/pricing/quote", 
                params={"price_krw": 98760000})
    
    # 9. Search with filters
    filtered_search = {
        **search_body,
        "price_min": 5000,
        "price_max": 20000,
        "year_min": 2018,
        "sort": "price_asc",
        "page_size": 10
    }
    success, filtered_data, _ = tester.test("Search - With Filters", "POST", "/search", 
                                            data=filtered_search)
    if success:
        print(f"   Filtered results: {filtered_data.get('total', 0)} cars")
    
    # 10. Search with transmission filter
    trans_search = {
        **search_body,
        "transmissions": ["수동"],
        "page_size": 10
    }
    success, trans_data, _ = tester.test("Search - Manual Transmission", "POST", "/search", 
                                         data=trans_search)
    if success:
        print(f"   Manual cars: {trans_data.get('total', 0)} (expected ~75)")
    
    # 11. Test pagination
    page2_search = {**search_body, "page": 2, "page_size": 10}
    tester.test("Search - Page 2", "POST", "/search", data=page2_search)
    
    # 12. Test different sort orders
    tester.test("Search - Sort by Price Ascending", "POST", "/search", 
                data={**search_body, "sort": "price_asc", "page_size": 10})
    
    tester.test("Search - Sort by Price Descending", "POST", "/search", 
                data={**search_body, "sort": "price_desc", "page_size": 10})
    
    tester.test("Search - Sort by Mileage", "POST", "/search", 
                data={**search_body, "sort": "mileage_asc", "page_size": 10})
    
    # Print summary
    tester.print_summary()
    
    # Return exit code
    return 0 if tester.tests_passed == tester.tests_run else 1


if __name__ == "__main__":
    sys.exit(main())
