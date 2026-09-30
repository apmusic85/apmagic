import os
import secrets
import hashlib
import base64
import json
from urllib.parse import urlencode
import requests
from flask import Flask, redirect, request, session
from concurrent.futures import ThreadPoolExecutor, as_completed

app = Flask(__name__)

# --- CONFIG ---
KEYSTRING = os.getenv("ETSY_KEYSTRING")
CLIENT_ID = KEYSTRING  # Links your Keystring directly to the login parameters
SHARED_SECRET = os.getenv("ETSY_SHARED_SECRET")
CALLBACK_URL = os.getenv("ETSY_CALLBACK_URL", "https://artplusmusic.store")
SHOP_ID = os.getenv("ETSY_SHOP_ID", "66416115")
app.secret_key = os.getenv("FLASK_SECRET_KEY", "change-this-in-render")

# Forces the browser to persist cookie variables across Render redirects
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_HTTPONLY=True
)

GROUPS = [
    "All",
    "Tees/T-shirts",
    "Hats",
    "shoes - men",
    "Framed Art Prints",
    "Backpack(s)",
    "Custom",
    "shoes - women",
    "Fanny",
    "other",
]

KEYWORD_GROUPS = {
    "Tees/T-shirts": ["Tees/T-shirts"],
    "Hats": ["Hats"],
    "shoes - men": ["shoes - men"],
    "Framed Art Prints": ["Framed Art Prints"],
    "Backpack(s)": ["Backpack(s)"],
    "Custom": ["Custom"],
    "shoes - women": ["shoes - women"],
    "Fanny": ["Fanny"],
}

ORDERED_COLUMNS = [
    "listing_id",
    "state",
    "shop_section_id",
    "title",
    "price",
    "quantity",
    "sku",
    "description",
    "tags",
    "materials",
    "style",
    "shipping_profile_id",
    "return_policy_id",
    "processing_min",
    "processing_max",
    "taxonomy_id",
    "who_made",
    "when_made",
    "is_supply",
    "item_length",
    "item_width",
    "item_height",
    "item_dimensions_unit",
    "item_weight",
    "item_weight_unit",
    "is_customizable",
    "is_personalizable",
    "is_private",
    "non_taxable",
    "is_taxable",
    "listing_type",
    "should_auto_renew",
]

# --- HELPERS ---
def assign_group(listing: dict) -> str:
    skus_raw = listing.get("skus", [])
    skus_string_list = [str(s) for s in skus_raw] if isinstance(skus_raw, list) else []
    
    blob = (
        (listing.get("title") or "")
        + " "
        + (listing.get("description") or "")
        + " "
        + " ".join(listing.get("tags") or [])
        + " "
        + " ".join(skus_string_list)
    )
    for group_name, keywords in KEYWORD_GROUPS.items():
        for kw in keywords:
            if kw and kw in blob:
                return group_name
    return "other"

def parse_bool(value: str):
    v = value.strip().lower()
    if v in ("true", "1", "yes", "y"):
        return True
    if v in ("false", "0", "no", "n"):
        return False
    return None

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

# --- ROUTES ---
@app.route("/")
def home():
    return """
    <html>
    <head><title>APMagic Etsy Drafts Matrix</title></head>
    <body>
        <h1>APMagic Etsy Drafts Bulk Manager</h1>
        <p><a href="/login">Login with Etsy Account</a></p>
        <p><a href="/listings">Open Drafts Spreadsheet Matrix</a></p>
    </body>
    </html>
    """

@app.route("/login")
def login():
    verifier = secrets.token_urlsafe(64)
    session["code_verifier"] = verifier

    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).decode().rstrip("=")

    state = secrets.token_urlsafe(32)
    session["oauth_state"] = state
    url = (
        "https://etsy.com"
        "?response_type=code"
        f"&client_id={CLIENT_ID}"
        f"&redirect_uri={CALLBACK_URL}"
        "&scope=listings_r%20listings_w%20shops_r"
        f"&state={state}"
        f"&code_challenge={challenge}"
        "&code_challenge_method=S256"
    )
    return redirect(url)

@app.route("/callback")
def callback():
    code = request.args.get("code")
    state = request.args.get("state")
    verifier = session.get("code_verifier")
    saved_state = session.get("oauth_state")

    if not verifier:
        return "Missing verifier in session"
    if not saved_state or state != saved_state:
        return "Invalid state descriptor match"

    token_response = requests.post(
        "https://etsy.com",
        data={
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "redirect_uri": CALLBACK_URL,
            "code": code,
            "code_verifier": verifier,
        },
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "x-api-key": KEYSTRING,
        },
    )

    token_data = token_response.json()
    if "access_token" not in token_data:
        return f"<pre>{json.dumps(token_data, indent=2)}</pre>"

    session["access_token"] = token_data["access_token"]
    return redirect("/listings")

@app.route("/listings", methods=["GET"])
def listings():
    access_token = session.get("access_token")
    if not access_token:
        return redirect("/login")

    active_group = request.args.get("group", "All")
    if active_group not in GROUPS:
        active_group = "All"

    draft_listings = fetch_draft_listings(access_token)

    if active_group != "All":
        filtered = [l for l in draft_listings if assign_group(l) == active_group]
    else:
        filtered = draft_listings

    html = []
    html.append("<html><head><title>Etsy Bulk Drafts Matrix</title>")
    html.append(
        "<style>"
        "body{font-family:Arial, sans-serif;font-size:13px;}"
        "table{border-collapse:collapse;font-size:11px;}"
        "th,td{border:1px solid #ccc;padding:4px;}"
        "input,select,textarea{font-size:12px;}"
        "</style>"
    )
    html.append("</head><body>")
    html.append("<h1>Etsy Bulk Drafts Inventory Matrix</h1>")
    html.append('<p><a href="/login">Refresh Authentication</a></p>')

    # FILTER BUTTON GRID
    html.append("<div style='margin-bottom:20px;'>")
    html.append("<label><strong>Product Group Filter :</strong></label>&nbsp;")
    for g in GROUPS:
        active_cls = (
            "background-color:#007bff;color:white;padding:6px 12px;margin-right:6px;border:none;border-radius:4px;cursor:pointer;"
            if g == active_group
            else "background-color:#e0e0e0;color:black;padding:6px 12px;margin-right:6px;border:none;border-radius:4px;cursor:pointer;"
        )
        html.append(f"<button style='{active_cls}' onclick=\"location.href='/listings?group={g}'\">{g}</button>")
    html.append("</div>")

    # MASS COMMAND PANEL
    html.append("<div style='margin:20px 0; padding:15px; border:1px solid #ccc; border-radius:6px;'>")
    html.append(f"<p style='margin-top:0; font-size:14px;'><strong>Mass Edit Command Box (Targeting {len(filtered)} Drafts):</strong></p>")
    html.append("<form method='POST' action='/bulk_update' style='display:flex; align-items:center; gap:10px;'>")
    html.append(f"<input type='hidden' name='group' value='{active_group}'/>")

    html.append("<select name='edit_target' style='width:220px; padding:4px;' required>")
    for field in ORDERED_COLUMNS:
        if field not in ["listing_id", "state"]:
            html.append(f"<option value='{field}'>{field}</option>")
    html.append("</select>")

    html.append("<input type='text' name='insert_value' placeholder='Enter modification value...' style='width:400px; padding:4px;' required />")
    html.append("<input type='submit' value='Apply Changes to Drafts' style='padding:6px 12px; background:#007bff; color:white; border:none; border-radius:4px; cursor:pointer;'/>")
    html.append("</form>")
    html.append("</div>")

    # SPREADSHEET DATAGRID
    html.append(f"<p>Showing Draft Rows 1 - {len(filtered)}</p>")
    html.append("<div style='overflow-x:auto; max-height:600px; border:1px solid #ccc;'>")
    html.append("<table><thead><tr><th>Row #</th>")
    for col in ORDERED_COLUMNS:
        html.append(f"<th>{col}</th>")
    html.append("</tr></thead><tbody>")

    for index, listing in enumerate(filtered, start=1):
        html.append(f"<tr><td><strong>{index}</strong></td>")
        for col in ORDERED_COLUMNS:
            if col == "sku":
                skus = listing.get("skus")
                val = str(skus) if isinstance(skus, list) and skus else str(listing.get("sku", ""))
            else:
                raw_val = listing.get(col, "")
                if col == "price" and isinstance(raw_val, dict):
                    amount = float(raw_val.get("amount", 0))
                    divisor = float(raw_val.get("divisor", 1) or 1)
                    val = f"${amount / divisor:.2f}"
                elif isinstance(raw_val, (list, dict)):
                    val = json.dumps(raw_val)
                else:
                    val = str(raw_val)
                    
            html.append(f"<td title='{val}'>{val}</td>")
        html.append("</tr>")

    html.append("</tbody></table></div></body></html>")
    return "\n".join(html)

@app.route("/bulk_update", methods=["POST"])
def bulk_update():
    access_token = session.get("access_token")
    if not access_token:
        return "Authentication access expired. Please re-login.", 401

    active_group = request.form.get("group", "All")
    edit_target = request.form.get("edit_target")
    insert_value = request.form.get("insert_value", "").strip()
    
    if not edit_target or insert_value == "":
        return redirect(f"/listings?group={active_group}")

    drafts = fetch_draft_listings(access_token)
    targets = []
    for l in drafts:
        if active_group == "All" or assign_group(l) == active_group:
            listing_id = l.get("listing_id")
            if listing_id:
                targets.append(listing_id)

    # Clean data type casting validation loops
    if edit_target in ["price", "item_length", "item_width", "item_height", "item_weight"]:
        try:
            val_to_send = float(insert_value)
        except ValueError:
            return f"Format Error: '{edit_target}' requires numeric inputs.", 400
    elif edit_target in ["quantity", "processing_min", "processing_max", "taxonomy_id", "shipping_profile_id", "return_policy_id", "shop_section_id"]:
        try:
            val_to_send = int(insert_value)
        except ValueError:
            return f"Format Error: '{edit_target}' requires an integer value.", 400
    elif edit_target in ["is_customizable", "is_personalizable", "is_private", "is_supply", "non_taxable", "is_taxable", "should_auto_renew"]:
        val_to_send = parse_bool(insert_value)
        if val_to_send is None:
            return "Format Error: Field requires a boolean choice (true/false, yes/no).", 400
    elif edit_target in ["tags", "materials", "style"]:
        val_to_send = [x.strip() for x in insert_value.split(",") if x.strip()]
    else:
        val_to_send = insert_value

    payload = {}
    if edit_target == "sku":
        payload["skus"] = [str(val_to_send)]
    else:
        payload[edit_target] = val_to_send

    success_count = 0
    failure_logs = []

    # Processes all 50 items concurrently in under 1 second to beat Render timeouts
    with ThreadPoolExecutor(max_workers=15) as executor:
        futures = {executor.submit(update_single_listing, lid, access_token, payload): lid for lid in targets}
        for future in as_completed(futures):
            res_data = future.result()
            if res_data["status"] == "success":
                success_count += 1
            else:
                failure_logs.append(f"ID {res_data['id']}: {res_data['msg']}")

    if failure_logs:
        return (
            f"<h3>Bulk Matrix Sync Summary</h3>"
            f"<p>Success items: {success_count}. Failures: {len(failure_logs)}.</p>"
            f"<pre>{json.dumps(failure_logs, indent=2)}</pre>"
            f"<p><a href='/listings?group={active_group}'>Return to Spreadsheet</a></p>"
        )

    return redirect(f"/listings?group={active_group}")

if __name__ == "__main__":
    app.run(debug=True)

