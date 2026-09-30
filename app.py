import os
import secrets
import hashlib
import base64
import json
from urllib.parse import urlencode
import requests
from flask import Flask, redirect, request, session

app = Flask(__name__)

# --- CONFIG ---
KEYSTRING = os.getenv("ETSY_KEYSTRING")

# Etsy OAuth Client ID
CLIENT_ID = os.getenv("CLIENT_ID", KEYSTRING)

SHARED_SECRET = os.getenv("ETSY_SHARED_SECRET")

CALLBACK_URL = os.getenv(
    "CALLBACK_URL",
    "https://apmagic.artplusmusic.store/callback"
)

SHOP_ID = os.getenv("ETSY_SHOP_ID", "66416115")

app.secret_key = os.getenv(
    "FLASK_SECRET_KEY",
    "change-this-in-render"
)


STATE_OPTIONS = [
    "draft",
    "active",
    "inactive",
    "sold_out",
    "expired",
    "edit",
    "removed",
]

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
    blob = (
        (listing.get("title") or "")
        + " "
        + (listing.get("description") or "")
        + " "
        + "".join(listing.get("tags", []) or [])
        + " "
        + " ".join(listing.get("skus", []) or [])
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


def fetch_all_listings(access_token: str, state: str | None = None):
    all_results = []
    page = 1
    while True:
        params = {
            "limit": 100,
            "offset": (page - 1) * 100,
        }

        if state:
            params["state"] = state

        url = f"https://api.etsy.com/v3/application/shops/{SHOP_ID}/listings?{urlencode(params)}"
        r = requests.get(
            url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "x-api-key": f"{KEYSTRING}:{SHARED_SECRET}",
            },
        )
        data = r.json()
        results = data.get("results", [])
        if not results:
            break
        all_results.extend(results)
        if len(results) < 100:
            break
        page += 1
    return all_results


# --- ROUTES ---
@app.route("/")
def home():
    return """
    <html>
    <head><title>APMagic Etsy Bulk Inventory Manager</title></head>
    <body>
        <h1>APMagic Etsy Bulk Inventory Manager</h1>
        <p><a href="/login">Login with Etsy</a></p>
        <p><a href="/listings">Go to Matrix</a></p>
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
        "https://www.etsy.com/oauth/connect"
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
        return "Invalid state"

    token_response = requests.post(
        "https://api.etsy.com/v3/public/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "redirect_uri": CALLBACK_URL,
            "code": code,
            "code_verifier": verifier,
        },
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "x-api-key": f"{KEYSTRING}:{SHARED_SECRET}",
        },
    )

    token_data = token_response.json()

    if "access_token" not in token_data:
        return f"<pre>{json.dumps(token_data, indent=2)}</pre>"

    access_token = token_data["access_token"]
    session["access_token"] = access_token
    return redirect("/listings")


@app.route("/listings", methods=["GET"])
def listings():
    access_token = session.get("access_token")
    if not access_token:
        return redirect("/login")

    working_state = request.args.get("state", "draft")
    if working_state not in STATE_OPTIONS:
        working_state = "draft"

    active_group = request.args.get("group", "All")
    if active_group not in GROUPS:
        active_group = "All"

    all_results = fetch_all_listings(access_token, working_state)

    enriched = []
    for l in all_results:
        state = l.get("state", "")
        group = assign_group(l)
        enriched.append((l, state, group))

    state_filtered = [item for item in enriched if item[1] == working_state]

    if active_group != "All":
        filtered = [item for item in state_filtered if item[2] == active_group]
    else:
        filtered = state_filtered

    html = []
    html.append("<html><head><title>Etsy Bulk Inventory Manager</title>")
    html.append(
        "<style>"
        "body{font-family:Arial, sans-serif;font-size:13px;}"
        "table{border-collapse:collapse;font-size:11px;}"
        "th,td{border:1px solid #ccc;padding:4px;}"
        "input,select,textarea{font-size:12px;}"
        "</style>"
    )
    html.append("</head><body>")
    html.append("<h1>Etsy Bulk Inventory Manager</h1>")
    html.append('<p><a href="/login">Re-login with Etsy</a></p>')

    # STATE FILTER BUTTON GRID
    html.append("<div style='margin-bottom:15px;'>")
    html.append("<label><strong>Listing State Filter :</strong></label>&nbsp;")
    for s in STATE_OPTIONS:
        active_cls = (
            "background-color:#007bff;color:white;padding:6px 12px;margin-right:6px;"
            "border:none;border-radius:4px;cursor:pointer;"
            if s == working_state
            else "background-color:#e0e0e0;color:black;padding:6px 12px;margin-right:6px;"
            "border:none;border-radius:4px;cursor:pointer;"
        )
        html.append(
            f"<button style='{active_cls}'"
            f" onclick=\"location.href='/listings?state={s}&group={active_group}'\">{s.upper()}</button>"
        )
    html.append("</div>")

    # GROUP CATEGORY BUTTON GRID
    html.append("<div style='margin-bottom:20px;'>")
    html.append("<label><strong>Product Group Filter :</strong></label>&nbsp;")
    for g in GROUPS:
        active_cls = (
            "background-color:#007bff;color:white;padding:6px 12px;margin-right:6px;"
            "border:none;border-radius:4px;cursor:pointer;"
            if g == active_group
            else "background-color:#e0e0e0;color:black;padding:6px 12px;margin-right:6px;"
            "border:none;border-radius:4px;cursor:pointer;"
        )
        html.append(
            f"<button style='{active_cls}'"
            f" onclick=\"location.href='/listings?state={working_state}&group={g}'\">{g}</button>"
        )

    html.append("</div>")

    # MASS ACTION PANEL
    html.append(
        "<div class='action-panel' "
        "style='margin:20px 0; padding:15px; border:1px solid #ccc; border-radius:6px;'>"
    )
    html.append(
        f"<p style='margin-top:0; font-size:14px;'>"
        f"<strong>+ Mass Action Command (Targeting {len(filtered)} items in view):</strong></p>"
    )

    html.append(
        "<form method='POST' action='/bulk_update' "
        "style='display:flex; align-items:center; gap:10px;'>"
    )
    html.append(f"<input type='hidden' name='state' value='{working_state}'/>")
    html.append(f"<input type='hidden' name='group' value='{active_group}'/>")

    html.append("<select name='edit_target' style='width:220px; padding:4px;' required>")
    for field in ORDERED_COLUMNS:
        if field != "listing_id":
            html.append(f"<option value='{field}'>{field}</option>")
    html.append("</select>")

    html.append(
        "<input type='text' name='insert_value' "
        "placeholder='Blank Insertion Box (Enter changes here) ... '"
        "style='width:400px; padding:4px;' required />"
    )

    html.append(
        "<input type='submit' value='Submit and Sync' "
        "style='padding:6px 12px; background:#007bff; color:white; "
        "border:none; border-radius:4px; cursor:pointer;'/>"
    )
    html.append("</form>")
    html.append("</div>")

    # DENSE DATA LAYOUT GRID
    html.append(f"<p>Showing Rows 1 - {len(filtered)}</p>")
    html.append("<div style='overflow-x:auto; max-height:600px; border:1px solid #ccc;'>")
    html.append("<table><thead><tr>")
    html.append("<th>Row #</th>")
    for col in ORDERED_COLUMNS:
        html.append(f"<th>{col}</th>")
    html.append("</tr></thead><tbody>")

    for index, item in enumerate(filtered, start=1):
        listing, state, group = item
        html.append(f"<tr><td><strong>{index}</strong></td>")
        for col in ORDERED_COLUMNS:
            if col == "sku":
                skus = listing.get("skus")
                if isinstance(skus, list) and skus:
                    val = skus[0]
                else:
                    val = ""
            else:
                val = listing.get(col, "")
            if col == "price":
                if isinstance(val, dict):
                    amount = float(val.get("amount", 0))
                    divisor = float(val.get("divisor", 1) or 1)
                    val = f"${amount / divisor:.2f}"
                elif isinstance(val, (list, dict)):
                    val = json.dumps(val)
            html.append(f"<td title='{val}'>{val}</td>")
        html.append("</tr>")

    html.append("</tbody></table></div>")
    html.append("</body></html>")
    return "\n".join(html)


@app.route("/bulk_update", methods=["POST"])
def bulk_update():
    access_token = session.get("access_token")
    if not access_token:
        return "Authentication access expired. Please re-login.", 401

    working_state = request.form.get("state", "draft")
    active_group = request.form.get("group", "All")
    edit_target = request.form.get("edit_target")
    insert_value = request.form.get("insert_value", "").strip()
    if not edit_target or insert_value == "":
        return redirect(f"/listings?state={working_state}&group={active_group}")

    all_results = fetch_all_listings(access_token, working_state)

    targets = []
    for l in all_results:
        if l.get("state", "") == working_state:
            if active_group == "All" or assign_group(l) == active_group:
                listing_id = l.get("listing_id")
                if listing_id:
                    targets.append(listing_id)

    # Type casting
    if edit_target in ["price", "item_length", "item_width", "item_height", "item_weight"]:
        try:
            val_to_send = float(insert_value)
        except ValueError:
            return f"Format Error: Column '{edit_target}' requires a numeric value.", 400
    elif edit_target in [
        "quantity",
        "processing_min",
        "processing_max",
        "taxonomy_id",
        "shipping_profile_id",
        "return_policy_id",
        "shop_section_id",
    ]:
        try:
            val_to_send = int(insert_value)
        except ValueError:
            return f"Format Error: Column '{edit_target}' requires an integer value.", 400
    elif edit_target in [
        "is_customizable",
        "is_personalizable",
        "is_private",
        "is_supply",
        "non_taxable",
        "is_taxable",
        "should_auto_renew",
    ]:
        val_to_send = parse_bool(insert_value)
        if val_to_send is None:
            return "Format Error: Field requires a boolean choice (true/false, yes/no).", 400
    elif edit_target in ["tags", "materials", "style"]:
        val_to_send = [x.strip() for x in insert_value.split(",") if x.strip()]
    else:
        val_to_send = insert_value

    success_count = 0
    failure_logs = []

    for listing_id in targets:
        url = f"https://api.etsy.com/v3/application/listings/{listing_id}"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "x-api-key": f"{KEYSTRING}:{SHARED_SECRET}",
            "Content-Type": "application/json",
        }

        payload = {}

        if edit_target == "title":
            payload["title"] = val_to_send
        elif edit_target == "description":
            payload["description"] = val_to_send
        elif edit_target == "state":
            payload["state"] = val_to_send
        elif edit_target == "quantity":
            payload["quantity"] = val_to_send
        elif edit_target == "shop_section_id":
            payload["shop_section_id"] = val_to_send
        elif edit_target == "tags":
            payload["tags"] = val_to_send
        elif edit_target == "materials":
            payload["materials"] = val_to_send
        elif edit_target == "style":
            payload["style"] = val_to_send
        elif edit_target == "shipping_profile_id":
            payload["shipping_profile_id"] = val_to_send
        elif edit_target == "return_policy_id":
            payload["return_policy_id"] = val_to_send
        elif edit_target == "processing_min":
            payload["processing_min"] = val_to_send
        elif edit_target == "processing_max":
            payload["processing_max"] = val_to_send
        elif edit_target == "taxonomy_id":
            payload["taxonomy_id"] = val_to_send
        elif edit_target == "who_made":
            payload["who_made"] = val_to_send
        elif edit_target == "when_made":
            payload["when_made"] = val_to_send
        elif edit_target == "is_supply":
            payload["is_supply"] = val_to_send
        elif edit_target == "item_length":
            payload["item_length"] = val_to_send
        elif edit_target == "item_width":
            payload["item_width"] = val_to_send
        elif edit_target == "item_height":
            payload["item_height"] = val_to_send
        elif edit_target == "item_dimensions_unit":
            payload["item_dimensions_unit"] = val_to_send
        elif edit_target == "item_weight":
            payload["item_weight"] = val_to_send
        elif edit_target == "item_weight_unit":
            payload["item_weight_unit"] = val_to_send
        elif edit_target == "is_customizable":
            payload["is_customizable"] = val_to_send
        elif edit_target == "is_personalizable":
            payload["is_personalizable"] = val_to_send
        elif edit_target == "is_private":
            payload["is_private"] = val_to_send
        elif edit_target == "non_taxable":
            payload["non_taxable"] = val_to_send
        elif edit_target == "is_taxable":
            payload["is_taxable"] = val_to_send
        elif edit_target == "listing_type":
            payload["listing_type"] = val_to_send
        elif edit_target == "should_auto_renew":
            payload["should_auto_renew"] = val_to_send
        elif edit_target == "price":
            payload["price"] = val_to_send
        elif edit_target == "sku":
            payload["skus"] = [str(val_to_send)]

        if not payload:
            continue

        res = requests.put(url, json=payload, headers=headers)

        if res.status_code == 200:
            success_count += 1
        else:
            failure_logs.append(
                f"ID {listing_id}: Response Status {res.status_code} - {res.text}"
            )

    if failure_logs:
        return (
            f"<h3>Execution Log Details</h3>"
            f"<p>Processed {success_count}. Failed {len(failure_logs)} targets.</p>"
            f"<pre>{json.dumps(failure_logs, indent=2)}</pre>"
            f"<p><a href='/listings?state={working_state}&group={active_group}'>Back</a></p>"
        )

    return redirect(f"/listings?state={working_state}&group={active_group}")


if __name__ == "__main__":
    app.run(debug=True)
