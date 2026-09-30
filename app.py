import os
import secrets
import hashlib
import base64
import json
import requests
from flask import Flask, redirect, request, session
from concurrent.futures import ThreadPoolExecutor, as_completed

# Import everything safely from our custom side files
from helpers import GROUPS, ORDERED_COLUMNS, assign_group, cast_and_validate_value
from etsy_api import KEYSTRING, fetch_draft_listings, update_single_listing

app = Flask(__name__)

CLIENT_ID = KEYSTRING  
SHARED_SECRET = os.getenv("ETSY_SHARED_SECRET")
CALLBACK_URL = os.getenv("ETSY_CALLBACK_URL", "https://artplusmusic.store")
app.secret_key = os.getenv("FLASK_SECRET_KEY", "change-this-in-render")

app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_HTTPONLY=True
)

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

    val_to_send, error_msg = cast_and_validate_value(edit_target, insert_value)
    if error_msg:
        return error_msg, 400

    payload = {}
    if edit_target == "sku":
        payload["skus"] = [str(val_to_send)]
    else:
        payload[edit_target] = val_to_send

    success_count = 0
    failure_logs = []

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
