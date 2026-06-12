"""Quick live test of website_finder — run: python test_ddgs.py"""
import time
from website_finder import find_website

CASES = [
    ("Lou Malnati's Pizzeria", "Chicago", "IL"),
    ("Katz's Delicatessen", "New York", "NY"),
    ("Dierks Waukesha Floral", "Waukesha", "WI"),
]

for name, city, state in CASES:
    r = find_website(name, city, state)
    print(f"{name!r:40} -> {r['website']}  [{r['source']}]  match={r['match_name']}")
    time.sleep(1)
