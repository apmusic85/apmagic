import os
import secrets
import hashlib
import base64
import json
from urllib.parse import urlencode
import requests
import csv
import io
from flask import Response
from flask import Flask, redirect, request, session, jsonify

app = Flask(__name__)

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

    # Build active column list — shop_section_id is always col 1, never in this list
    cols_param = request.args.get("cols", "")
    active_cols = []
    if cols_param:
        for c in cols_param.split(","):
            c = c.strip()
            if c and c in ORDERED_COLUMNS and c != "shop_section_id" and c != "listing_id" and c not in active_cols:
                active_cols.append(c)
    cols_str = ",".join(active_cols)

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
<div class="action-panel">
  <span class="action-label">Field</span>
  <form method="POST" action="/bulk_update" style="display:contents;">
    <input type="hidden" name="state" value="{working_state}"/>
    <input type="hidden" name="group" value="{active_group}"/>
    <input type="hidden" name="cols"  value="{cols_str}"/>
    <select name="edit_target" id="field-select">
""")
    for field in selectable_fields:
        h.append(f'<option value="{field}">{field}</option>')
    h.append(f"""    </select>
    <input type="text" name="insert_value" placeholder="Value to apply to rows in view…"/>
    <button type="submit" name="sync_scope" value="local" class="btn-black">Submit &amp; Sync (Local)</button>
    <button type="submit" name="sync_scope" value="global" class="btn-black" style="background:#b32424; margin-left:6px;">Submit &amp; Sync (Global)</button>
  </form>
<a class="btn-outline"
href="/export.csv?state={working_state}&group={active_group}&cols={cols_str}">
Export CSV
</a>

<button class="btn-outline" id="add-col-btn">+ Add Column</button>

<span class="count-note">{len(filtered)} listings</span>
<script>
(function() {{
  var colsStr = "{cols_str}";
  var st = "{working_state}";
  var gr = "{active_group}";
  document.getElementById("add-col-btn").addEventListener("click", function() {{
    var field = document.getElementById("field-select").value;
    if (field === "shop_section_id") return; // always col 1, skip
    var cols = colsStr ? colsStr.split(",").filter(Boolean) : [];
    if (!cols.includes(field)) cols.push(field);
    window.location.href = "/listings?state=" + st + "&group=" + gr + "&cols=" + cols.join(",");
  }});
}})();
</script>
""")

    h.append("""
<!-- Live Master Taxonomy Lookup Engine -->
<div style="margin: 0 20px 15px 20px; padding: 12px; background: #fff; border: 1px solid #ddd; border-radius: 6px; box-shadow: 0 1px 4px rgba(0,0,0,0.05);">
    <div style="display: flex; gap: 10px; align-items: center;">
        <span style="font-size: 11px; font-weight: bold; text-transform: uppercase; color: #888; white-space: nowrap;">Etsy Master Lookup:</span>
        <input type="text" id="master-search-box" placeholder="Type category name (e.g. Tees, Prints, Hats)..." style="padding: 6px 10px; width: 280px; border: 1px solid #ccc; border-radius: 4px; font-size: 12px; color: #000;">
        <button type="button" onclick="queryEtsyMasterList()" style="padding: 6px 14px; background: #111; color: #fff; border: none; border-radius: 4px; font-size: 12px; cursor: pointer; white-space: nowrap;">Find True IDs</button>
    </div>
    <div id="master-search-results" style="font-size: 12px; color: #333; font-weight: 500; margin-top: 8px;"></div>
</div>

<script>
function queryEtsyMasterList() {
    var term = document.getElementById('master-search-box').value.trim().toLowerCase();
    var resultsBox = document.getElementById('master-search-results');
    if (!term) return;
    
    resultsBox.innerHTML = "Querying live tree...";
    
    fetch('/api/categories')
        .then(function(res) { return res.json(); })
        .then(function(payload) {
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
            traverse(payload.results || [], []);
            // Show the deepest (most specific / leaf) matches first — that's the node Etsy
            // actually wants you to pick, since same-named categories can exist at several depths.
            found.sort(function(a, b) { return b.depth - a.depth; });
            if (found.length === 0) {
                resultsBox.innerHTML = "No matching categories found.";
            } else {
                resultsBox.innerHTML = found.map(function(f) {
                    var tag = f.leaf
                        ? "<span style='color:#0a7a2f; font-weight:bold;'>LEAF</span>"
                        : "<span style='color:#999;'>parent</span>";
                    return "<div style='padding:3px 0;'>" + tag + " &nbsp; " + f.path +
                           " &nbsp; <span style='color:#b32424; font-family:monospace; font-weight:bold;'>" + f.id + "</span></div>";
                }).join("");
            }
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
    access_token = session.get("access_token")
    if not access_token:
        return "Authentication access expired. Please re-login.", 401

    working_state = request.form.get("state", "draft")
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

    all_results = fetch_all_listings(access_token, working_state)
    targets = []
    for l in all_results:
            if active_group == "All" or assign_group(l) == active_group:
                listing_id = l.get("listing_id")
                if listing_id:
                    targets.append(listing_id)

    # Type casting
    if edit_target in ["price", "item_length", "item_width", "item_height", "item_weight"]:
        try:
            val_to_send = float(insert_value)
        except ValueError:
            return f"Format Error: '{edit_target}' requires a numeric value.", 400
    elif edit_target in [
        "quantity", "processing_min", "processing_max", "taxonomy_id",
        "shipping_profile_id", "return_policy_id", "shop_section_id",
    ]:
        try:
            val_to_send = int(insert_value)
        except ValueError:
            return f"Format Error: '{edit_target}' requires an integer.", 400
    elif edit_target in [
        "is_customizable", "is_personalizable", "is_private", "is_supply",
        "non_taxable", "is_taxable", "should_auto_renew",
    ]:
        val_to_send = parse_bool(insert_value)
        if val_to_send is None:
            return "Format Error: Field requires true/false.", 400
    elif edit_target in ["tags", "materials", "style"]:
        val_to_send = [x.strip() for x in insert_value.split(",") if x.strip()]
    else:
        val_to_send = insert_value

    success_count = 0
    failure_logs  = []

    # Build lookup dictionary for fast access to listing details
    listing_lookup = {
        l.get("listing_id"): l
        for l in all_results
        if l.get("listing_id") is not None
    }

    for listing_id in targets:
        # Check if the targeted edit belongs to the inventory subsystem
        is_inventory_target = edit_target in ["price", "quantity", "sku"]

        if is_inventory_target:
            # --- INVENTORY PATHWAY: PUT REQUEST ---
            url = f"https://etsy.com{listing_id}/inventory"
            headers = {
                "Authorization": f"Bearer {access_token}",
                "x-api-key": f"{KEYSTRING}:{SHARED_SECRET}",
                "Content-Type": "application/json; charset=utf-8"
            }
            
            get_r = requests.get(url, headers={"Authorization": f"Bearer {access_token}", "x-api-key": f"{KEYSTRING}:{SHARED_SECRET}"})
            if get_r.status_code != 200:
                failure_logs.append(f"ID {listing_id}: Could not fetch baseline inventory — {get_r.text}")
                continue
                
            g_data = get_r.json()
            products_list = g_data.get("products", [])
            
            if not products_list:
                failure_logs.append(f"ID {listing_id}: No products structure found to modify.")
                continue

            # Safely loop through all 18 variations (sizes and colors)
            for product in products_list:
                # Force SKU property context to null to satisfy validation constraints
                product["sku"] = None
                
                offerings = product.get("offerings", [])
                for offering in offerings:
                    if edit_target == "quantity":
                        # Applies the chosen stock number identically across all sizes/colors
                        offering["quantity"] = int(val_to_send)
                        
                    elif edit_target == "price":
                        # Applies a uniform price across all variations using strict currency units
                        offering["price"] = {
                            "amount": int(round(float(val_to_send) * 100)),
                            "divisor": 100,
                            "currency_code": "USD"
                        }
                
                # Strip out the read-only tracking IDs before pushing updates
                product.pop("product_id", None)
                product.pop("scale_name", None)
                product.pop("is_deleted", None)
                for offering in product.get("offerings", []):
                    offering.pop("offering_id", None)

            payload = {"products": products_list}
            res = requests.put(url, json=payload, headers=headers)

        else:
            # --- METADATA PATHWAY: PATCH REQUEST USING FORM DATA ---
            url = f"https://api.etsy.com/v3/application/shops/{SHOP_ID}/listings/{listing_id}"
            headers = {
                "Authorization": f"Bearer {access_token}",
                "x-api-key": f"{KEYSTRING}:{SHARED_SECRET}",
                "Content-Type": "application/x-www-form-urlencoded"
            }
            
            payload = {}
            if edit_target == "title":
                if "<insert title>" in val_to_send:
                    current_listing = listing_lookup.get(listing_id, {})
                    design_name = current_listing.get("title", "Original Art")
                    payload["title"] = val_to_send.replace("<insert title>", design_name).strip()
                else:
                    payload["title"] = val_to_send
                    
            elif edit_target == "description": payload["description"] = val_to_send
            elif edit_target == "state": payload["state"] = val_to_send
            elif edit_target == "shop_section_id": payload["shop_section_id"] = int(val_to_send)
            
            elif edit_target == "tags": payload["tags"] = ",".join(val_to_send) if isinstance(val_to_send, list) else val_to_send
            elif edit_target == "materials": payload["materials"] = ",".join(val_to_send) if isinstance(val_to_send, list) else val_to_send
            elif edit_target == "style": payload["style"] = ",".join(val_to_send) if isinstance(val_to_send, list) else val_to_send
            
            elif edit_target == "shipping_profile_id": payload["shipping_profile_id"] = int(val_to_send)
            elif edit_target == "return_policy_id": payload["return_policy_id"] = int(val_to_send)
            elif edit_target == "processing_min": payload["processing_min"] = int(val_to_send)
            elif edit_target == "processing_max": payload["processing_max"] = int(val_to_send)
            elif edit_target == "taxonomy_id": payload["taxonomy_id"] = int(val_to_send)
            elif edit_target == "who_made": payload["who_made"] = val_to_send
            elif edit_target == "when_made": payload["when_made"] = val_to_send
            
            elif edit_target == "is_supply": payload["is_supply"] = "true" if val_to_send else "false"
            elif edit_target == "is_customizable": payload["is_customizable"] = "true" if val_to_send else "false"
            elif edit_target == "is_personalizable": payload["is_personalizable"] = "true" if val_to_send else "false"
            elif edit_target == "is_private": payload["is_private"] = "true" if val_to_send else "false"
            elif edit_target == "non_taxable": payload["non_taxable"] = "true" if val_to_send else "false"
            elif edit_target == "is_taxable": payload["is_taxable"] = "true" if val_to_send else "false"
            elif edit_target == "should_auto_renew": payload["should_auto_renew"] = "true" if val_to_send else "false"

            if not payload:
                continue

            res = requests.patch(url, data=payload, headers=headers)

        # Track execution logs consistently
        if res.status_code == 200:
            success_count += 1
        else:
            failure_logs.append(f"ID {listing_id} ({edit_target}): {res.status_code} — {res.text}")

    if failure_logs:
        return (
            f"<h3>Execution Log</h3>"
            f"<p>Success: {success_count} &nbsp;|&nbsp; Failed: {len(failure_logs)}</p>"
            f"<pre>{json.dumps(failure_logs, indent=2)}</pre>"
            f"<p><a href='{back_url}'>Back</a></p>"
        )

    return redirect(back_url)


@app.route("/debug")
def debug():
    access_token = session.get("access_token")
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
    access_token = session.get("access_token")
    if not access_token:
        return jsonify({"error": "Authentication required. Please log in first."}), 401

    url = f"https://openapi.etsy.com/v3/application/seller-taxonomy/nodes/{category_id}/properties"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "x-api-key": f"{KEYSTRING}:{SHARED_SECRET}"
    }
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return jsonify(response.json())
        return jsonify({"error": "Etsy rejected variation request", "details": response.text}), response.status_code
    except Exception as e:
        return jsonify({"error": "Network connection loss", "details": str(e)}), 500

@app.route("/export.csv")
def export_csv():

    access_token = session.get("access_token")

    if not access_token:
        return "Authentication access expired. Please re-login.", 401

    working_state = request.args.get("state", "draft")
    active_group = request.args.get("group", "All")

    cols_param = request.args.get("cols", "")
    active_cols = [c.strip() for c in cols_param.split(",") if c.strip()]

    if not active_cols:
        active_cols = [
            c for c in ORDERED_COLUMNS
            if c not in ("listing_id", "shop_section_id")
        ]

    all_results = fetch_all_listings(access_token, working_state)

    rows = [
        l for l in all_results
        if active_group == "All" or assign_group(l) == active_group
    ]

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(
        ["listing_id", "shop_section_id"] + active_cols
    )

    for l in rows:

        row = [
            l.get("listing_id", ""),
            l.get("shop_section_id", "")
        ]

        for col in active_cols:

            val = l.get(col, "")

            if isinstance(val, (list, dict)):
                val = json.dumps(val)

            row.append(val)

        writer.writerow(row)

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition":
            f"attachment; filename=listings_{working_state}_{active_group}.csv"
        }
    )


if __name__ == "__main__":
    app.run(debug=True)


