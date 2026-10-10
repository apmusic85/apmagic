import os
import time
import copy
import csv
import io
import secrets
import hashlib
import base64
import json
from urllib.parse import urlencode
import requests
from flask import Flask, redirect, request, session, jsonify, Response

app = Flask(__name__)

# In-memory log of bulk edits made this server run: [{batch_id, ts, listing_id,
# edit_target, old_value, new_value, success}, ...]. Used by the undo feature.
# This resets whenever the dyno restarts (e.g. a new deploy) — it's a same-session
# safety net, not permanent history.
EDIT_LOG = []

# --- CONFIG ---
KEYSTRING = os.getenv("ETSY_KEYSTRING")
CLIENT_ID = os.getenv("CLIENT_ID", KEYSTRING)
SHARED_SECRET = os.getenv("ETSY_SHARED_SECRET")
CALLBACK_URL = os.getenv("CALLBACK_URL", "https://apmagic.artplusmusic.store/callback")
SHOP_ID = os.getenv("ETSY_SHOP_ID", "66416115")
app.secret_key = os.getenv("FLASK_SECRET_KEY", "change-this-in-render")

STATE_OPTIONS = [
    "draft", "active", "inactive", "sold_out", "expired", "edit", "removed",
]

GROUPS = [
    "All", "60007259", "60007263", "60007265", "60611782", "60007269", "60611670",
]

GROUP_LABELS = {
    "All": "All",
    "60007259": "Tees",
    "60007263": "Hats",
    "60007265": "Shoes-M",
    "60611782": "Shoes-W",
    "60007269": "Prints",
    "60611670": "custom",
}

ORDERED_COLUMNS = [
    "listing_id", "state", "shop_section_id", "title", "price", "quantity",
    "sku", "description", "tags", "materials", "style", "shipping_profile_id",
    "return_policy_id", "processing_min", "processing_max", "taxonomy_id",
    "who_made", "when_made", "is_supply", "item_length", "item_width",
    "item_height", "item_dimensions_unit", "item_weight", "item_weight_unit",
    "is_customizable", "is_personalizable", "is_private", "non_taxable",
    "is_taxable", "listing_type", "should_auto_renew",
]


def assign_group(listing):
    return str(listing.get("shop_section_id"))


def parse_bool(value: str):
    v = value.strip().lower()
    if v in ("true", "1", "yes", "y"):
        return True
    if v in ("false", "0", "no", "n"):
        return False
    return None


def _bearer(token):
    # Builds the Authorization header value for an Etsy API call.
    return "Bearer " + token


RATE_LIMIT_DELAY = 0.2  # seconds between Etsy API calls, to stay comfortably under their rate limit


def cast_value(edit_target, raw_value):
    """
    Converts a raw string (e.g. typed into the bulk-edit box, or read from an
    imported CSV cell) into the correctly-typed value Etsy's API expects for
    that field. Returns (value, error_message); error_message is None on success.
    Already-typed values (e.g. passed straight through from code, not a form)
    are returned unchanged.
    """
    if isinstance(raw_value, (int, float, bool, list)):
        return raw_value, None

    raw_value = str(raw_value).strip()

    if edit_target in ["price", "item_length", "item_width", "item_height", "item_weight"]:
        try:
            return float(raw_value), None
        except ValueError:
            return None, f"'{edit_target}' requires a numeric value."

    if edit_target in [
        "quantity", "processing_min", "processing_max", "taxonomy_id",
        "shipping_profile_id", "return_policy_id", "shop_section_id",
    ]:
        try:
            return int(raw_value), None
        except ValueError:
            return None, f"'{edit_target}' requires an integer."

    if edit_target in [
        "is_customizable", "is_personalizable", "is_private", "is_supply",
        "non_taxable", "is_taxable", "should_auto_renew",
    ]:
        parsed = parse_bool(raw_value)
        if parsed is None:
            return None, "Field requires true/false."
        return parsed, None

    if edit_target in ["tags", "materials", "style"]:
        return [x.strip() for x in raw_value.split(",") if x.strip()], None

    return raw_value, None


def apply_single_edit(listing_id, edit_target, val_to_send, access_token, listing_lookup):
    """
    Applies one field edit to one listing on Etsy.
    Returns {"ok": bool, "message": str, "old_value": <value from before the edit>}.
    For inventory-backed fields (price/quantity/sku), old_value is the exact
    pre-edit inventory payload (wrapped so undo can PUT it straight back).
    For every other field, old_value is whatever that field held in the listing
    snapshot that was fetched at the start of this run.
    """
    is_inventory_target = edit_target in ["price", "quantity", "sku"]

    if is_inventory_target:
        url = f"https://api.etsy.com/v3/application/listings/{listing_id}/inventory"
        auth_headers = {"Authorization": _bearer(access_token), "x-api-key": f"{KEYSTRING}:{SHARED_SECRET}"}

        get_r = requests.get(url, headers=auth_headers)
        if get_r.status_code != 200:
            return {"ok": False, "message": f"ID {listing_id}: Could not fetch baseline inventory — {get_r.text}", "old_value": None}

        g_data = get_r.json()
        products_list = g_data.get("products", [])
        if not products_list:
            return {"ok": False, "message": f"ID {listing_id}: No products structure found to modify.", "old_value": None}

        # Snapshot the exact pre-edit payload so an undo can restore it precisely.
        old_snapshot = copy.deepcopy(products_list)

        for product in products_list:
            if edit_target == "sku":
                product["sku"] = str(val_to_send)
            else:
                product["sku"] = product.get("sku")

            offerings = product.get("offerings", [])
            for offering in offerings:
                if edit_target == "quantity":
                    offering["quantity"] = int(val_to_send)
                elif edit_target == "price":
                    offering["price"] = {
                        "amount": int(round(float(val_to_send) * 100)),
                        "divisor": 100,
                        "currency_code": "USD",
                    }

            product.pop("product_id", None)
            product.pop("scale_name", None)
            product.pop("is_deleted", None)
            for offering in product.get("offerings", []):
                offering.pop("offering_id", None)

        headers = dict(auth_headers)
        headers["Content-Type"] = "application/json; charset=utf-8"
        res = requests.put(url, json={"products": products_list}, headers=headers)

        old_value_wrapped = {"_inventory_products": old_snapshot}
        if res.status_code == 200:
            return {"ok": True, "message": f"ID {listing_id}: updated", "old_value": old_value_wrapped}
        return {"ok": False, "message": f"ID {listing_id} ({edit_target}): {res.status_code} — {res.text}", "old_value": old_value_wrapped}

    # --- METADATA PATHWAY ---
    url = f"https://api.etsy.com/v3/application/shops/{SHOP_ID}/listings/{listing_id}"
    headers = {
        "Authorization": _bearer(access_token),
        "x-api-key": f"{KEYSTRING}:{SHARED_SECRET}",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    current_listing = listing_lookup.get(listing_id, {})
    old_value = current_listing.get(edit_target)

    payload = {}
    if edit_target == "title":
        if isinstance(val_to_send, str) and "<insert title>" in val_to_send:
            design_name = current_listing.get("title", "Original Art")
            payload["title"] = val_to_send.replace("<insert title>", design_name).strip()
        else:
            payload["title"] = val_to_send
    elif edit_target == "description":
        payload["description"] = val_to_send
    elif edit_target == "state":
        payload["state"] = val_to_send
    elif edit_target == "shop_section_id":
        payload["shop_section_id"] = int(val_to_send)
    elif edit_target == "tags":
        payload["tags"] = ",".join(val_to_send) if isinstance(val_to_send, list) else val_to_send
    elif edit_target == "materials":
        payload["materials"] = ",".join(val_to_send) if isinstance(val_to_send, list) else val_to_send
    elif edit_target == "style":
        payload["style"] = ",".join(val_to_send) if isinstance(val_to_send, list) else val_to_send
    elif edit_target == "shipping_profile_id":
        payload["shipping_profile_id"] = int(val_to_send)
    elif edit_target == "return_policy_id":
        payload["return_policy_id"] = int(val_to_send)
    elif edit_target == "processing_min":
        payload["processing_min"] = int(val_to_send)
    elif edit_target == "processing_max":
        payload["processing_max"] = int(val_to_send)
    elif edit_target == "taxonomy_id":
        payload["taxonomy_id"] = int(val_to_send)
    elif edit_target == "who_made":
        payload["who_made"] = val_to_send
    elif edit_target == "when_made":
        payload["when_made"] = val_to_send
    elif edit_target in [
        "is_supply", "is_customizable", "is_personalizable", "is_private",
        "non_taxable", "is_taxable", "should_auto_renew",
    ]:
        payload[edit_target] = "true" if val_to_send else "false"

    if not payload:
        return {"ok": False, "message": f"ID {listing_id}: '{edit_target}' is not an editable field.", "old_value": old_value}

    res = requests.patch(url, data=payload, headers=headers)
    if res.status_code == 200:
        return {"ok": True, "message": f"ID {listing_id}: updated", "old_value": old_value}
    return {"ok": False, "message": f"ID {listing_id} ({edit_target}): {res.status_code} — {res.text}", "old_value": old_value}


def fetch_all_listings(access_token: str, state: str | None = None):
    all_results = []
    page = 1
    while True:
        params = {"limit": 100, "offset": (page - 1) * 100}
        if state:
            params["state"] = state
        url = f"https://api.etsy.com/v3/application/shops/{SHOP_ID}/listings?{urlencode(params)}"
        r = requests.get(
            url,
            headers={
                "Authorization": _bearer(access_token),
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
    <html><head><title>APMagic</title></head><body>
    <h1>APMagic Etsy Bulk Inventory Manager</h1>
    <p><a href="/login">Login with Etsy</a></p>
    <p><a href="/listings">Go to Matrix</a></p>
    </body></html>
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
    session["access_token"] = token_data["access_token"]
    session["refresh_token"] = token_data.get("refresh_token")
    # expires_in is in seconds; keep a 2-minute safety buffer before it actually expires
    session["token_expires_at"] = time.time() + float(token_data.get("expires_in", 3600)) - 120
    return redirect("/listings")


def get_valid_access_token():
    """
    Returns a usable access token, transparently refreshing it first if it's
    expired (or about to expire) instead of letting every API call fail with 401.
    Returns None if there's no session at all or the refresh itself fails.
    """
    access_token = session.get("access_token")
    if not access_token:
        return None

    expires_at = session.get("token_expires_at", 0)
    if time.time() < expires_at:
        return access_token  # still good

    refresh_token = session.get("refresh_token")
    if not refresh_token:
        # No refresh token on file (e.g. an old session from before this feature) —
        # fall back to whatever we have and let the caller handle a possible 401.
        return access_token

    resp = requests.post(
        "https://api.etsy.com/v3/public/oauth/token",
        data={
            "grant_type": "refresh_token",
            "client_id": CLIENT_ID,
            "refresh_token": refresh_token,
        },
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "x-api-key": f"{KEYSTRING}:{SHARED_SECRET}",
        },
    )
    if resp.status_code != 200:
        # Refresh failed (e.g. the refresh token itself finally expired) — return
        # the stale token; the caller's own 401 handling takes over from there.
        return access_token

    new_data = resp.json()
    new_access = new_data.get("access_token")
    if not new_access:
        return access_token

    session["access_token"] = new_access
    session["refresh_token"] = new_data.get("refresh_token", refresh_token)
    session["token_expires_at"] = time.time() + float(new_data.get("expires_in", 3600)) - 120
    return new_access


@app.route("/listings", methods=["GET"])
def listings():
    access_token = get_valid_access_token()
    if not access_token:
        return redirect("/login")

    working_state = request.args.get("state", "draft")
    if working_state not in STATE_OPTIONS:
        working_state = "draft"

    active_group = request.args.get("group", "All")
    if active_group not in GROUPS:
        active_group = "All"

    # Build active column list — shop_section_id is always col 1, never in this list
    cols_param = request.args.get("cols", "")
    active_cols = []
    if cols_param:
        for c in cols_param.split(","):
            c = c.strip()
            if c and c in ORDERED_COLUMNS and c != "shop_section_id" and c != "listing_id" and c not in active_cols:
                active_cols.append(c)
    cols_str = ",".join(active_cols)
    cols_suffix = f"&cols={cols_str}" if cols_str else ""

    # Fetch and filter
    all_results = fetch_all_listings(access_token, working_state)
    enriched = [(l, l.get("state", ""), assign_group(l)) for l in all_results]
    state_filtered = [item for item in enriched if item[1] == working_state]
    if active_group != "All":
        filtered = [item for item in state_filtered if item[2] == active_group]
    else:
        filtered = state_filtered

    # URL helpers
    def nav_url(state=working_state, group=active_group, cols=cols_str):
        u = f"/listings?state={state}&group={group}"
        if cols:
            u += f"&cols={cols}"
        return u

    def remove_col_url(field):
        new_cols = [c for c in active_cols if c != field]
        return nav_url(cols=",".join(new_cols))

    # Dropdown fields: everything except listing_id (shop_section_id stays for bulk edit)
    selectable_fields = [f for f in ORDERED_COLUMNS if f != "listing_id"]

    # ---- HTML ----
    h = []
    h.append("""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>APMagic — Etsy Bulk Manager</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: #f0f0f0;
    color: #1a1a1a;
    font-size: 14px;
  }

  /* ── TOP BAR ── */
  .topbar {
    position: sticky;
    top: 0;
    z-index: 200;
    background: #111;
    color: #fff;
    padding: 0 20px;
    height: 48px;
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .topbar h1 { font-size: 15px; font-weight: 600; letter-spacing: .04em; }
  .topbar a  { color: #888; font-size: 12px; text-decoration: none; }
  .topbar a:hover { color: #fff; }

  /* ── TOOLBAR ── */
  .toolbar {
    position: sticky;
    top: 48px;
    z-index: 190;
    background: #fff;
    border-bottom: 1px solid #ddd;
    padding: 10px 20px;
    display: flex;
    flex-wrap: wrap;
    gap: 18px;
    align-items: flex-start;
  }
  .filter-group { display: flex; flex-direction: column; align-items: flex-start; gap: 4px; flex-wrap: wrap; }
  .filter-label {
    font-size: 10px; font-weight: 700; text-transform: uppercase;
    letter-spacing: .07em; color: #999; white-space: nowrap;
  }
  .filter-buttons { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
  .btn {
    padding: 4px 11px;
    border: 1px solid #ccc;
    border-radius: 4px;
    background: #fafafa;
    color: #444;
    font-size: 12px;
    cursor: pointer;
    text-decoration: none;
    display: inline-block;
    line-height: 1.5;
    transition: background .12s, color .12s;
  }
  .btn:hover { background: #ebebeb; }
  .btn.active { background: #111; color: #fff; border-color: #111; }

  .group-item {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 2px;
  }
  .group-btn {
    padding: 4px 11px;
    border: 1px solid #ccc;
    border-radius: 4px;
    background: #fafafa;
    color: #444;
    font-size: 12px;
    cursor: pointer;
    text-decoration: none;
    display: inline-block;
    line-height: 1.5;
    transition: background .12s, color .12s;
  }
  .group-btn:hover { background: #ebebeb; }
  .group-btn.active { background: #111; color: #fff; border-color: #111; }
  .group-label {
    font-size: 11px;
    color: #666;
    text-align: center;
    white-space: nowrap;
    max-width: 72px;
    line-height: 1.1;
    letter-spacing: 0.01em;
  }

  /* ── ACTION PANEL ── */
  .action-panel {
    position: sticky;
    top: 94px;           /* 48 topbar + 46 toolbar */
    z-index: 180;
    background: #f8f8f8;
    border-bottom: 2px solid #ddd;
    padding: 10px 20px;
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
  }
  .action-label {
    font-size: 10px; font-weight: 700; text-transform: uppercase;
    letter-spacing: .07em; color: #999; white-space: nowrap;
  }
  .action-panel select {
    width: 190px; padding: 6px 8px;
    border: 1px solid #ccc; border-radius: 4px;
    font-size: 13px; background: #fff;
  }
  .action-panel input[type=text] {
    width: 320px; padding: 6px 10px;
    border: 1px solid #ccc; border-radius: 4px;
    font-size: 13px; background: #fff;
  }
  .btn-black {
    padding: 6px 16px;
    background: #111; color: #fff;
    border: none; border-radius: 4px;
    font-size: 13px; cursor: pointer; white-space: nowrap;
  }
  .btn-black:hover { background: #333; }
  .btn-outline {
    padding: 6px 14px;
    background: #fff; color: #111;
    border: 1px solid #333; border-radius: 4px;
    font-size: 13px; cursor: pointer; white-space: nowrap;
    text-decoration: none; display: inline-block;
  }
  .btn-outline:hover { background: #f0f0f0; }
  .count-note { font-size: 11px; color: #aaa; white-space: nowrap; }

  /* ── TABLE ── */
  .table-wrap {
    position: sticky;
    top: 94px;
    z-index: 160;
    overflow-x: auto;
    background: #f0f0f0;
    padding: 20px;
  }

  table {
    border-collapse: collapse;
    background: #fff;
    width: max-content;
    min-width: 100%;
    border-radius: 6px;
    overflow: hidden;
    box-shadow: 0 1px 6px rgba(0,0,0,.07);
  }

  thead th {
    position: sticky;
    top: 0;
    z-index: 10;
    background: #1a1a1a;
    color: #fff;
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: .06em;
    padding: 10px 16px;
    text-align: left;
    white-space: nowrap;
    border-right: 1px solid #333;
  }
  thead th:last-child { border-right: none; }

  .col-x {
    margin-left: 7px; color: #666;
    font-size: 14px; text-decoration: none; font-weight: 400;
  }
  .col-x:hover { color: #e00; }

  tbody tr { border-bottom: 1px solid #f0f0f0; }
  tbody tr:nth-child(even) { background: #fafafa; }
  tbody tr:hover { background: #f0f6ff; }

  tbody td {
    padding: 9px 16px;
    font-size: 13px;
    vertical-align: middle;
    border-right: 1px solid #f0f0f0;
    white-space: nowrap;
    max-width: 360px;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  tbody td:last-child { border-right: none; }

  .td-num    { color: #bbb; font-size: 11px; text-align: center; width: 42px; }
  .td-sec    { font-family: monospace; font-size: 12px; color: #666; min-width: 110px; }
  .td-normal { min-width: 140px; }
</style>
</head>
<body>
""")

    # TOP BAR
    h.append(f"""
<div class="topbar">
  <h1>APMagic &mdash; Etsy Bulk Manager</h1>
  <a href="/login">Re-login</a>
</div>
""")

    # TOOLBAR — keep state in request flow, hide it from UX while leaving section visible
    h.append('<div class="toolbar">')
    h.append('<div class="filter-group" style="display:none;">')
    h.append('<span class="filter-label">State</span>')
    for s in STATE_OPTIONS:
        cls = "btn active" if s == working_state else "btn"
        h.append(f'<a class="{cls}" href="{nav_url(state=s)}">{s}</a>')
    h.append('</div>')
    h.append('<div class="filter-group"><span class="filter-label">Section</span>')
    h.append('<div class="filter-buttons">')
    for g in GROUPS:
        cls = "group-btn active" if g == active_group else "group-btn"
        label = GROUP_LABELS.get(g, g)
        h.append(f'<div class="group-item"><a class="{cls}" href="{nav_url(group=g)}">{g}</a><div class="group-label">{label}</div></div>')
    h.append('</div></div></div>')

    # ACTION PANEL — sticky below toolbar
    h.append(f"""
<div class="action-panel" style="flex-direction: column; align-items: stretch; gap: 8px;">
  <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;">
    <span class="action-label">Field</span>
    <form method="POST" action="/bulk_update" id="bulk-form" style="display:contents;">
      <input type="hidden" name="group" value="{active_group}"/>
      <input type="hidden" name="cols"  value="{cols_str}"/>
      <input type="hidden" name="state" value="{working_state}"/>
      <select name="edit_target" id="field-select">
""")
    for field in selectable_fields:
        h.append(f'<option value="{field}">{field}</option>')
    h.append(f"""      </select>
      <input type="text" name="insert_value" placeholder="Value to apply to rows in view…"/>
      <span class="action-label" style="margin-left:8px;">Apply to states:</span>
""")
    for s in STATE_OPTIONS:
        checked = "checked" if s == working_state else ""
        h.append(f'<label style="font-size:12px; color:#444; display:inline-flex; align-items:center; gap:3px;"><input type="checkbox" name="target_states" value="{s}" {checked}/>{s}</label>')
    h.append(f"""
      <button type="submit" name="sync_scope" value="local" class="btn-black">Submit &amp; Sync (Local)</button>
      <button type="submit" name="sync_scope" value="global" class="btn-black" id="global-submit-btn" style="background:#b32424; margin-left:6px;">Submit &amp; Sync (Global)</button>
    </form>
    <button class="btn-outline" id="add-col-btn">+ Add Column</button>
    <span class="count-note">{len(filtered)} listings in view &nbsp;|&nbsp; {len(state_filtered)} in this state</span>
  </div>
  <div style="display:flex; align-items:center; gap:14px; padding-top:4px; border-top:1px solid #eee;">
    <a class="btn-outline" href="/export.csv?state={working_state}&group={active_group}{cols_suffix}">Export CSV (current view)</a>
    <form method="POST" action="/import_csv" enctype="multipart/form-data" style="display:flex; align-items:center; gap:6px;">
      <input type="file" name="file" accept=".csv" required style="font-size:12px;"/>
      <button type="submit" class="btn-outline" onclick="return confirm('This will apply every column in the uploaded CSV to the listing_id in each row. Continue?');">Import CSV</button>
    </form>
  </div>
</div>

<script>
(function() {{
  var colsStr = "{cols_str}";
  var st = "{working_state}";
  var gr = "{active_group}";
  var stateFilteredCount = {len(state_filtered)};
  var viewCount = {len(filtered)};

  document.getElementById("add-col-btn").addEventListener("click", function() {{
    var field = document.getElementById("field-select").value;
    if (field === "shop_section_id") return; // always col 1, skip
    var cols = colsStr ? colsStr.split(",").filter(Boolean) : [];
    if (!cols.includes(field)) cols.push(field);
    window.location.href = "/listings?state=" + st + "&group=" + gr + "&cols=" + cols.join(",");
  }});

  // Global sync is a shop-wide write — make sure a stray click can't fire it unconfirmed.
  document.getElementById("global-submit-btn").addEventListener("click", function(e) {{
    var checkedStates = document.querySelectorAll('input[name="target_states"]:checked').length;
    var msg = "This will push this change to EVERY section (not just \\"" + gr + "\\"), " +
      "across " + checkedStates + " state(s) you've ticked above — roughly " + stateFilteredCount +
      "+ listing(s). This writes directly to your live Etsy shop. Continue?";
    if (!window.confirm(msg)) {{
      e.preventDefault();
    }}
  }});

  // Local sync still deserves a lighter confirmation since it's also a real write.
  document.getElementById("bulk-form").addEventListener("submit", function(e) {{
    var checkedStates = document.querySelectorAll('input[name="target_states"]:checked');
    if (checkedStates.length === 0) {{
      alert("Pick at least one state to apply this edit to.");
      e.preventDefault();
    }}
  }});
}})();
</script>
""")

    h.append("""
<!-- Live Master Lookup Engine: categories, shipping profiles, return policies -->
<div style="margin: 0 20px 15px 20px; padding: 12px; background: #fff; border: 1px solid #ddd; border-radius: 6px; box-shadow: 0 1px 4px rgba(0,0,0,0.05);">
    <div style="display: flex; gap: 10px; align-items: center;">
        <span style="font-size: 11px; font-weight: bold; text-transform: uppercase; color: #888; white-space: nowrap;">Etsy Master Lookup:</span>
        <select id="master-search-type" style="padding: 6px 8px; border: 1px solid #ccc; border-radius: 4px; font-size: 12px;">
            <option value="category">Category (taxonomy_id)</option>
            <option value="shipping">Shipping Profile</option>
            <option value="return">Return Policy</option>
        </select>
        <input type="text" id="master-search-box" placeholder="Type a name to search (e.g. Tees, Standard Shipping)..." style="padding: 6px 10px; width: 280px; border: 1px solid #ccc; border-radius: 4px; font-size: 12px; color: #000;">
        <button type="button" onclick="queryEtsyMasterList()" style="padding: 6px 14px; background: #111; color: #fff; border: none; border-radius: 4px; font-size: 12px; cursor: pointer; white-space: nowrap;">Find True IDs</button>
    </div>
    <div id="master-search-results" style="font-size: 12px; color: #333; font-weight: 500; margin-top: 8px;"></div>
</div>

<script>
var _categoryTreeCache = null;

function fetchCategoryTree() {
    if (_categoryTreeCache) return Promise.resolve(_categoryTreeCache);
    return fetch('/api/categories').then(function(res) { return res.json(); }).then(function(payload) {
        _categoryTreeCache = payload.results || [];
        return _categoryTreeCache;
    });
}

function showCategoryAttributes(categoryId, rowId) {
    var el = document.getElementById(rowId);
    el.innerHTML = "Loading required attributes...";
    fetch('/api/categories/' + categoryId + '/properties')
        .then(function(res) { return res.json(); })
        .then(function(payload) {
            var props = payload.results || [];
            if (!props.length) {
                el.innerHTML = "<em>No listed attribute requirements for this category.</em>";
                return;
            }
            el.innerHTML = props.map(function(p) {
                var req = p.is_required ? "<b style='color:#b32424;'>required</b>" : "<span style='color:#999;'>optional</span>";
                return "&bull; " + p.display_name + " (" + req + ")";
            }).join("<br/>");
        })
        .catch(function() { el.innerHTML = "Could not load attributes."; });
}

function queryEtsyMasterList() {
    var term = document.getElementById('master-search-box').value.trim().toLowerCase();
    var mode = document.getElementById('master-search-type').value;
    var resultsBox = document.getElementById('master-search-results');
    if (!term) return;

    resultsBox.innerHTML = "Querying live data...";

    if (mode === 'category') {
        fetchCategoryTree().then(function(tree) {
            var found = [];
            function traverse(nodes, path) {
                nodes.forEach(function(n) {
                    var here = path.concat([n.name]);
                    if (n.name && n.name.toLowerCase().includes(term)) {
                        var isLeaf = !n.children || n.children.length === 0;
                        found.push({ id: n.id, depth: here.length, leaf: isLeaf, path: here.join(" &gt; ") });
                    }
                    if (n.children) traverse(n.children, here);
                });
            }
            traverse(tree, []);
            // Deepest / most specific matches first — that's the node Etsy actually wants.
            found.sort(function(a, b) { return b.depth - a.depth; });
            if (found.length === 0) {
                resultsBox.innerHTML = "No matching categories found.";
                return;
            }
            resultsBox.innerHTML = found.map(function(f, idx) {
                var rowId = "cat-attrs-" + idx;
                var tag = f.leaf
                    ? "<span style='color:#0a7a2f; font-weight:bold;'>LEAF</span>"
                    : "<span style='color:#999;'>parent</span>";
                return "<div style='padding:3px 0;'>" + tag + " &nbsp; " + f.path +
                       " &nbsp; <span style='color:#b32424; font-family:monospace; font-weight:bold;'>" + f.id + "</span>" +
                       " &nbsp; <a href='javascript:void(0)' onclick=\"showCategoryAttributes(" + f.id + ", '" + rowId + "')\" style='font-size:11px;'>show required attributes</a>" +
                       "<div id='" + rowId + "' style='margin:3px 0 0 20px; font-size:11px; color:#555;'></div></div>";
            }).join("");
        }).catch(function() { resultsBox.innerHTML = "Lookup handshake failed."; });
        return;
    }

    var endpoint = mode === 'shipping' ? '/api/shipping-profiles' : '/api/return-policies';
    fetch(endpoint)
        .then(function(res) { return res.json(); })
        .then(function(payload) {
            var items = payload.results || [];
            var found = items.filter(function(it) {
                var label = (it.title || it.name || "").toString().toLowerCase();
                return label.includes(term);
            });
            if (found.length === 0) {
                resultsBox.innerHTML = "No matches found.";
                return;
            }
            resultsBox.innerHTML = found.map(function(it) {
                var id = mode === 'shipping' ? it.shipping_profile_id : it.return_policy_id;
                var label = it.title || it.name || ("Policy " + id);
                return "<div style='padding:3px 0;'>" + label +
                       " &nbsp; <span style='color:#b32424; font-family:monospace; font-weight:bold;'>" + id + "</span></div>";
            }).join("");
        })
        .catch(function() { resultsBox.innerHTML = "Lookup handshake failed."; });
}
</script>
""")

    # TABLE
    h.append('<div class="table-wrap">')
    h.append('<table><thead><tr>')
    h.append('<th>#</th>')
    h.append('<th>shop_section_id</th>')
    for col in active_cols:
        h.append(f'<th>{col}<a class="col-x" href="{remove_col_url(col)}" title="Remove">&times;</a></th>')
    h.append('</tr></thead><tbody>')

    for idx, (listing, _, _grp) in enumerate(filtered, 1):
        h.append('<tr>')
        h.append(f'<td class="td-num">{idx}</td>')
        h.append(f'<td class="td-sec">{listing.get("shop_section_id", "")}</td>')
        for col in active_cols:
            if col == "sku":
                skus = listing.get("skus")
                val = skus if isinstance(skus, list) and skus else ""
            elif col == "price":
                raw = listing.get("price", "")
                if isinstance(raw, dict):
                    amt = float(raw.get("amount", 0))
                    div = float(raw.get("divisor", 1) or 1)
                    val = f"${amt / div:.2f}"
                else:
                    val = raw
            else:
                val = listing.get(col, "")
            if isinstance(val, (list, dict)):
                val = json.dumps(val)
            display = str(val) if val is not None else ""
            safe = display.replace('"', '&quot;')
            h.append(f'<td class="td-normal" title="{safe}">{display}</td>')
        h.append('</tr>')

    h.append('</tbody></table></div>')
    h.append('</body></html>')
    return "\n".join(h)


@app.route("/bulk_update", methods=["POST"])
def bulk_update():
    access_token = get_valid_access_token()
    if not access_token:
        return "Authentication access expired. Please re-login.", 401

    working_state = request.form.get("state", "draft")
    target_states = [s for s in request.form.getlist("target_states") if s in STATE_OPTIONS]
    if not target_states:
        target_states = [working_state]

    active_group  = request.form.get("group", "All")
    cols          = request.form.get("cols", "")
    edit_target   = request.form.get("edit_target")
    insert_value  = request.form.get("insert_value", "").strip()
    sync_scope    = request.form.get("sync_scope", "local")

    if sync_scope == "global":
        active_group = "All"

    cols_suffix = f"&cols={cols}" if cols else ""
    back_url = f"/listings?state={working_state}&group={active_group}{cols_suffix}"

    if not edit_target or insert_value == "":
        return redirect(back_url)

    val_to_send, cast_error = cast_value(edit_target, insert_value)
    if cast_error:
        return f"Format Error: {cast_error}", 400

    # Pull listings from every state ticked in the panel and merge, de-duplicated —
    # this is what makes a single sync able to span e.g. both draft and active at once.
    all_results = []
    seen_ids = set()
    for st in target_states:
        for l in fetch_all_listings(access_token, st):
            lid = l.get("listing_id")
            if lid is not None and lid not in seen_ids:
                seen_ids.add(lid)
                all_results.append(l)

    targets = []
    for l in all_results:
        if active_group == "All" or assign_group(l) == active_group:
            listing_id = l.get("listing_id")
            if listing_id:
                targets.append(listing_id)

    listing_lookup = {
        l.get("listing_id"): l
        for l in all_results
        if l.get("listing_id") is not None
    }

    batch_id = str(int(time.time() * 1000))
    scope_label = "Global — every section" if sync_scope == "global" else f"Local — section {active_group}"

    def generate():
        yield (
            "<html><head><title>Sync in progress</title>"
            "<meta charset='utf-8'>"
            "<style>body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;"
            "padding:24px;background:#fafafa;color:#1a1a1a;} "
            ".row{padding:2px 0;font-size:13px;} .ok{color:#0a7a2f;} .fail{color:#b32424;} "
            "a{color:#111;} .btn-black{padding:6px 16px;background:#111;color:#fff;border:none;"
            "border-radius:4px;font-size:13px;cursor:pointer;}"
            "</style></head><body>"
            f"<h3>Syncing {len(targets)} listing(s) &mdash; states: {', '.join(target_states)} ({scope_label})</h3>"
            "<div id='log'>"
        )
        success_count = 0
        failure_logs = []
        for i, listing_id in enumerate(targets, 1):
            result = apply_single_edit(listing_id, edit_target, val_to_send, access_token, listing_lookup)
            EDIT_LOG.append({
                "batch_id": batch_id,
                "ts": time.time(),
                "listing_id": listing_id,
                "edit_target": edit_target,
                "old_value": result["old_value"],
                "new_value": val_to_send,
                "success": result["ok"],
            })
            if result["ok"]:
                success_count += 1
                yield f"<div class='row ok'>&#10003; {i}/{len(targets)} &mdash; {result['message']}</div>"
            else:
                failure_logs.append(result["message"])
                yield f"<div class='row fail'>&#10007; {i}/{len(targets)} &mdash; {result['message']}</div>"
            time.sleep(RATE_LIMIT_DELAY)

        yield "</div>"
        yield f"<h3>Done &mdash; Success: {success_count} &nbsp;|&nbsp; Failed: {len(failure_logs)}</h3>"
        if success_count:
            yield (
                "<form method='POST' action='/undo_last' style='display:inline;'>"
                f"<input type='hidden' name='batch_id' value='{batch_id}'/>"
                f"<button type='submit' class='btn-black' onclick=\"return confirm('Revert all {success_count} change(s) from this run back to their previous values?');\">"
                "Undo this batch</button></form> &nbsp; "
            )
        yield f"<a href='{back_url}'>Back to listings</a>"
        yield "</body></html>"

    return Response(generate(), mimetype="text/html")


@app.route("/undo_last", methods=["POST"])
def undo_last():
    access_token = get_valid_access_token()
    if not access_token:
        return "Authentication access expired. Please re-login.", 401

    batch_id = request.form.get("batch_id")
    entries = [e for e in EDIT_LOG if e["batch_id"] == batch_id and e["success"]]
    if not entries:
        return "Nothing to undo for that batch (it may have already been undone, or the server restarted since).", 400

    undo_batch_id = f"undo-{batch_id}-{int(time.time() * 1000)}"

    def generate():
        yield (
            "<html><head><title>Undo in progress</title><meta charset='utf-8'>"
            "<style>body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;"
            "padding:24px;background:#fafafa;} .ok{color:#0a7a2f;} .fail{color:#b32424;}"
            "</style></head><body>"
            f"<h3>Reverting {len(entries)} change(s)...</h3><div>"
        )
        success_count = 0
        for i, entry in enumerate(entries, 1):
            old_value = entry["old_value"]
            edit_target = entry["edit_target"]
            listing_id = entry["listing_id"]

            if isinstance(old_value, dict) and "_inventory_products" in old_value:
                # Inventory field — restore the exact snapshot taken right before the edit.
                url = f"https://api.etsy.com/v3/application/listings/{listing_id}/inventory"
                headers = {
                    "Authorization": _bearer(access_token),
                    "x-api-key": f"{KEYSTRING}:{SHARED_SECRET}",
                    "Content-Type": "application/json; charset=utf-8",
                }
                res = requests.put(url, json={"products": old_value["_inventory_products"]}, headers=headers)
                ok = res.status_code == 200
                msg = f"ID {listing_id}: reverted" if ok else f"ID {listing_id}: revert failed &mdash; {res.status_code}"
            elif old_value is None:
                ok = False
                msg = f"ID {listing_id}: no prior value was captured for '{edit_target}', skipped."
            else:
                result = apply_single_edit(listing_id, edit_target, old_value, access_token, {})
                ok = result["ok"]
                msg = result["message"]

            EDIT_LOG.append({
                "batch_id": undo_batch_id, "ts": time.time(), "listing_id": listing_id,
                "edit_target": edit_target, "old_value": None, "new_value": old_value, "success": ok,
            })
            success_count += 1 if ok else 0
            cls = "ok" if ok else "fail"
            mark = "&#10003;" if ok else "&#10007;"
            yield f"<div class='{cls}'>{mark} {i}/{len(entries)} &mdash; {msg}</div>"
            time.sleep(RATE_LIMIT_DELAY)

        yield f"</div><h3>Undo complete &mdash; Reverted: {success_count}/{len(entries)}</h3>"
        yield "<a href='/listings'>Back to listings</a></body></html>"

    return Response(generate(), mimetype="text/html")


@app.route("/export.csv")
def export_csv():
    access_token = get_valid_access_token()
    if not access_token:
        return "Authentication access expired. Please re-login.", 401

    working_state = request.args.get("state", "draft")
    active_group = request.args.get("group", "All")
    cols_param = request.args.get("cols", "")
    active_cols = [c.strip() for c in cols_param.split(",") if c.strip()]
    if not active_cols:
        active_cols = [c for c in ORDERED_COLUMNS if c not in ("listing_id", "shop_section_id")]

    all_results = fetch_all_listings(access_token, working_state)
    rows = [l for l in all_results if active_group == "All" or assign_group(l) == active_group]

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["listing_id", "shop_section_id"] + active_cols)
    for l in rows:
        row = [l.get("listing_id", ""), l.get("shop_section_id", "")]
        for col in active_cols:
            val = l.get(col, "")
            if isinstance(val, (list, dict)):
                val = json.dumps(val)
            row.append(val)
        writer.writerow(row)

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=listings_{working_state}_{active_group}.csv"},
    )


@app.route("/import_csv", methods=["POST"])
def import_csv():
    access_token = get_valid_access_token()
    if not access_token:
        return "Authentication access expired. Please re-login.", 401

    file = request.files.get("file")
    if not file or not file.filename:
        return "No file uploaded.", 400

    text_stream = io.StringIO(file.stream.read().decode("utf-8-sig"))
    reader = csv.DictReader(text_stream)
    fieldnames = reader.fieldnames or []
    if "listing_id" not in fieldnames:
        return "CSV must include a 'listing_id' column.", 400

    editable_cols = [c for c in fieldnames if c != "listing_id" and c in ORDERED_COLUMNS]

    # Pull every state up front so any listing_id in the CSV can be found regardless
    # of which tab it happens to be filed under right now.
    all_results = []
    for st in STATE_OPTIONS:
        all_results.extend(fetch_all_listings(access_token, st))
    listing_lookup = {l.get("listing_id"): l for l in all_results if l.get("listing_id") is not None}

    jobs = []
    parse_errors = []
    for row in reader:
        raw_id = (row.get("listing_id") or "").strip()
        if not raw_id:
            continue
        try:
            listing_id = int(raw_id)
        except ValueError:
            parse_errors.append(f"Skipped row &mdash; invalid listing_id '{raw_id}'")
            continue
        for col in editable_cols:
            raw_value = (row.get(col) or "").strip()
            if raw_value == "":
                continue
            jobs.append((listing_id, col, raw_value))

    batch_id = f"csv-{int(time.time() * 1000)}"

    def generate():
        yield (
            "<html><head><title>CSV import in progress</title><meta charset='utf-8'>"
            "<style>body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;"
            "padding:24px;background:#fafafa;} .ok{color:#0a7a2f;} .fail{color:#b32424;} "
            ".btn-black{padding:6px 16px;background:#111;color:#fff;border:none;border-radius:4px;"
            "font-size:13px;cursor:pointer;}</style></head><body>"
        )
        for err in parse_errors:
            yield f"<div class='fail'>{err}</div>"
        yield f"<h3>Applying {len(jobs)} cell change(s) from your file...</h3><div>"
        success_count = 0
        for i, (listing_id, edit_target, raw_value) in enumerate(jobs, 1):
            val_to_send, cast_error = cast_value(edit_target, raw_value)
            if cast_error:
                yield f"<div class='fail'>&#10007; {i}/{len(jobs)} &mdash; ID {listing_id} ({edit_target}): {cast_error}</div>"
                continue
            result = apply_single_edit(listing_id, edit_target, val_to_send, access_token, listing_lookup)
            EDIT_LOG.append({
                "batch_id": batch_id, "ts": time.time(), "listing_id": listing_id,
                "edit_target": edit_target, "old_value": result["old_value"],
                "new_value": val_to_send, "success": result["ok"],
            })
            cls = "ok" if result["ok"] else "fail"
            mark = "&#10003;" if result["ok"] else "&#10007;"
            success_count += 1 if result["ok"] else 0
            yield f"<div class='{cls}'>{mark} {i}/{len(jobs)} &mdash; {result['message']}</div>"
            time.sleep(RATE_LIMIT_DELAY)
        yield f"</div><h3>Import complete &mdash; Success: {success_count} &nbsp;|&nbsp; Failed: {len(jobs) - success_count}</h3>"
        if success_count:
            yield (
                "<form method='POST' action='/undo_last' style='display:inline;'>"
                f"<input type='hidden' name='batch_id' value='{batch_id}'/>"
                f"<button type='submit' class='btn-black' onclick=\"return confirm('Revert all {success_count} change(s) from this import?');\">Undo this import</button></form> &nbsp; "
            )
        yield "<a href='/listings'>Back to listings</a></body></html>"

    return Response(generate(), mimetype="text/html")

@app.route("/debug")
def debug():
    access_token = get_valid_access_token()
    if not access_token:
        return redirect("/login")
    r = requests.get("https://etsy.com", headers={"x-api-key": f"{KEYSTRING}:{SHARED_SECRET}"})
    return f"<pre>{json.dumps(r.json(), indent=2)}</pre>"


# --- ETSY TAXONOMY MANAGEMENT ROUTES ---

@app.route('/api/categories', methods=['GET'])
def get_all_categories():
    """
    Fetches the live full hierarchy taxonomy tree directly from Etsy OpenAPI v3.
    """
    url = "https://openapi.etsy.com/v3/application/seller-taxonomy/nodes"
    headers = {"x-api-key": f"{KEYSTRING}:{SHARED_SECRET}"}
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return jsonify(response.json())
        return jsonify({"error": "Etsy API failure pulling categories", "details": response.text}), response.status_code
    except Exception as e:
        return jsonify({"error": "Server connection failed", "details": str(e)}), 500


@app.route('/api/categories/<int:category_id>/properties', methods=['GET'])
def get_category_properties(category_id):
    """
    Retrieves the authentic, live variation requirements from Etsy for this category.
    """
    access_token = get_valid_access_token()
    if not access_token:
        return jsonify({"error": "Authentication required. Please log in first."}), 401

    url = f"https://openapi.etsy.com/v3/application/seller-taxonomy/nodes/{category_id}/properties"
    headers = {
        "Authorization": _bearer(access_token),
        "x-api-key": f"{KEYSTRING}:{SHARED_SECRET}"
    }
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return jsonify(response.json())
        return jsonify({"error": "Etsy rejected variation request", "details": response.text}), response.status_code
    except Exception as e:
        return jsonify({"error": "Network connection loss", "details": str(e)}), 500


@app.route('/api/shipping-profiles', methods=['GET'])
def get_shipping_profiles():
    """
    Flat list of this shop's shipping profiles (name + id) — used by the Master
    Lookup tool so shipping_profile_id edits don't have to be guessed blind.
    """
    access_token = get_valid_access_token()
    if not access_token:
        return jsonify({"error": "Authentication required. Please log in first."}), 401

    url = f"https://api.etsy.com/v3/application/shops/{SHOP_ID}/shipping-profiles"
    headers = {"Authorization": _bearer(access_token), "x-api-key": f"{KEYSTRING}:{SHARED_SECRET}"}
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return jsonify(response.json())
        return jsonify({"error": "Etsy API failure pulling shipping profiles", "details": response.text}), response.status_code
    except Exception as e:
        return jsonify({"error": "Server connection failed", "details": str(e)}), 500


@app.route('/api/return-policies', methods=['GET'])
def get_return_policies():
    """
    Flat list of this shop's return policies (id + terms) — same purpose as
    shipping-profiles above, for return_policy_id edits.
    """
    access_token = get_valid_access_token()
    if not access_token:
        return jsonify({"error": "Authentication required. Please log in first."}), 401

    url = f"https://api.etsy.com/v3/application/shops/{SHOP_ID}/policies/return"
    headers = {"Authorization": _bearer(access_token), "x-api-key": f"{KEYSTRING}:{SHARED_SECRET}"}
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return jsonify(response.json())
        return jsonify({"error": "Etsy API failure pulling return policies", "details": response.text}), response.status_code
    except Exception as e:
        return jsonify({"error": "Server connection failed", "details": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True)


