import os
from urllib.parse import urlencode
import requests

KEYSTRING = os.getenv("ETSY_KEYSTRING")
SHOP_ID = os.getenv("ETSY_SHOP_ID", "66416115")

def fetch_draft_listings(access_token: str):
    all_results = []
    page = 1
    while True:
        params = {
            "limit": 100,
            "offset": (page - 1) * 100,
            "state": "draft"
        }
        url = f"https://etsy.com{SHOP_ID}/listings?{urlencode(params)}"
        r = requests.get(
            url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "x-api-key": KEYSTRING,
            },
        )
        if r.status_code != 200:
            break
            
        data = r.json()
        results = data.get("results", [])
        if not results:
            break
        all_results.extend(results)
        if len(results) < 100:
            break
        page += 1
    return all_results

def update_single_listing(listing_id, access_token, payload):
    url = f"https://etsy.com{listing_id}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "x-api-key": KEYSTRING,
        "Content-Type": "application/json",
    }
    try:
        res = requests.put(url, json=payload, headers=headers, timeout=5)
        if res.status_code == 200:
            return {"status": "success", "id": listing_id}
        else:
            return {"status": "fail", "id": listing_id, "msg": f"Status {res.status_code} - {res.text}"}
    except Exception as e:
        return {"status": "fail", "id": listing_id, "msg": str(e)}
