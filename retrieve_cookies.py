# run with uv run --with browser_cookie3 python retrieve_cookies.py
import json
import browser_cookie3

BROWSERS = [
    browser_cookie3.chrome,
    browser_cookie3.chromium,
    browser_cookie3.vivaldi,
    browser_cookie3.brave,
    browser_cookie3.opera,
    browser_cookie3.edge,
    browser_cookie3.firefox,
]

domain = "oreilly.com"
all_cookies = {}


print(f"Retrieving browser cookies for {domain}\n")

for loader in BROWSERS:
    name = loader.__name__
    try:
        print(f"Trying {name}...")
        cj = loader(domain_name=domain)
        for cookie in cj:
            all_cookies[cookie.name] = cookie.value
        print(f"  - Loaded {len(cj)} cookies")

        if all_cookies:
            break
    except Exception as e:
        print(f"  - {name} failed: {e}")

with open("cookies.json", "w") as f:
    json.dump(all_cookies, f, indent=2)

print(f"\nFinished. Total cookies collected: {len(all_cookies)}")
