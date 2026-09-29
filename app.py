from flask import Flask, redirect, request, session
import os
import secrets
import hashlib
import base64
import requests
import json

app = Flask(__name__)

CLIENT_ID = os.getenv("ETSY_CLIENT_ID")
CLIENT_SECRET = os.getenv("ETSY_CLIENT_SECRET")

app.secret_key = os.getenv(
    "FLASK_SECRET_KEY",
    "change-this-in-render"
)

CALLBACK_URL = "https://apmagic.artplusmusic.store/callback"
SHOP_ID = "66416115"


@app.route("/")
def home():
    return """
    <h1>APMagic</h1>
    <a href="/login">Login with Etsy</a>
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
        json={
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "redirect_uri": CALLBACK_URL,
            "code": code,
            "code_verifier": verifier,
        },
    )

    token_data = token_response.json()

    if "access_token" not in token_data:
        return f"<pre>{json.dumps(token_data, indent=2)}</pre>"

    access_token = token_data["access_token"]
    session["access_token"] = access_token

    return redirect("/listings")


def fetch_listings(access_token):
    states = ["active"]
    all_results = []
    for s in states:
        r = requests.get(
            f"https://api.etsy.com/v3/application/shops/{SHOP_ID}/listings?state={s}",
            headers={
                "Authorization": f"Bearer {access_token}",
                "x-api-key": f"{CLIENT_ID}:{CLIENT_SECRET}",
            },
        )
        data = r.json()
        if "results" in data:
            all_results.extend(data["results"])
        else:
            all_results.append({"state": s, "error": data})
    return all_results


@app.route("/listings")
def listings():
    access_token = session.get("access_token")
    if not access_token:
        return redirect("/login")

    all_results = fetch_listings(access_token)

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

    grouped = {k: [] for k in KEYWORD_GROUPS}
    grouped["other"] = []
    grouped["all"] = all_results

    for l in all_results:
        blob = (
            (l.get("title", "") or "") + " " +
            (l.get("description", "") or "") + " " +
            " ".join(l.get("tags", []) or []) + " " +
            " ".join(l.get("skus", []) or [])
        )
        matched = False
        for group_name, keywords in KEYWORD_GROUPS.items():
            for kw in keywords:
                if kw in blob:
                    grouped[group_name].append(l)
                    matched = True
                    break
            if matched:
                break
        if not matched:
            grouped["other"].append(l)

    html = []
    html.append("<html><head><title>Listings</title></head><body>")
    html.append("<h1>Listings</h1>")
    html.append("<p><a href=\"/login\">Re-login</a></p>")

    for group_name, items in grouped.items():
        if group_name == "all":
            continue
        html.append(f"<h2>{group_name} ({len(items)})</h2>")
        if not items:
            html.append("<p>None</p>")
            continue
        html.append("<table border='1' cellspacing='0' cellpadding='4'>")
        html.append("<tr>")
        html.append("<th>ID</th>")
        html.append("<th>Title</th>")
        html.append("<th>Description</th>")
        html.append("<th>State</th>")
        html.append("<th>Quantity</th>")
        html.append("<th>Shop Section ID</th>")
        html.append("<th>Tags</th>")
        html.append("<th>Materials</th>")
        html.append("<th>Shipping Profile ID</th>")
        html.append("<th>Return Policy ID</th>")
        html.append("<th>Processing Min</th>")
        html.append("<th>Processing Max</th>")
        html.append("<th>Who Made</th>")
        html.append("<th>When Made</th>")
        html.append("<th>Is Supply</th>")
        html.append("<th>Item Weight</th>")
        html.append("<th>Item Weight Unit</th>")
        html.append("<th>Item Length</th>")
        html.append("<th>Item Width</th>")
        html.append("<th>Item Height</th>")
        html.append("<th>Item Dimensions Unit</th>")
        html.append("<th>Is Private</th>")
        html.append("<th>Style</th>")
        html.append("<th>Listing Type</th>")
        html.append("<th>Should Auto Renew</th>")
        html.append("<th>Taxonomy ID</th>")
        html.append("<th>Price</th>")
        html.append("<th>Non Taxable</th>")
        html.append("<th>Is Taxable</th>")
        html.append("<th>Is Customizable</th>")
        html.append("<th>Is Personalizable</th>")
        html.append("<th>SKU</th>")
        html.append("<th>Save</th>")
        html.append("</tr>")
        for l in items:
            listing_id = l.get("listing_id", "")
            title = (l.get("title") or "").replace('"', "&quot;")
            description = (l.get("description") or "").replace('"', "&quot;")
            state = l.get("state", "")
            quantity = str(l.get("quantity", ""))
            shop_section_id = str(l.get("shop_section_id", ""))
            tags = ",".join(l.get("tags", []) or [])
            materials = ",".join(l.get("materials", []) or [])
            shipping_profile_id = str(l.get("shipping_profile_id", ""))
            return_policy_id = str(l.get("return_policy_id", ""))
            processing_min = str(l.get("processing_min", ""))
            processing_max = str(l.get("processing_max", ""))
            who_made = l.get("who_made", "")
            when_made = l.get("when_made", "")
            is_supply = str(l.get("is_supply", ""))
            item_weight = str(l.get("item_weight", ""))
            item_weight_unit = l.get("item_weight_unit", "")
            item_length = str(l.get("item_length", ""))
            item_width = str(l.get("item_width", ""))
            item_height = str(l.get("item_height", ""))
            item_dimensions_unit = l.get("item_dimensions_unit", "")
            is_private = str(l.get("is_private", ""))
            style = ",".join(l.get("style", []) or [])
            listing_type = l.get("listing_type", "")
            should_auto_renew = str(l.get("should_auto_renew", ""))
            taxonomy_id = str(l.get("taxonomy_id", ""))
            price = ""
            if l.get("price"):
                if isinstance(l["price"], dict):
                    price = str(l["price"].get("amount", ""))
                else:
                    price = str(l["price"])
            non_taxable = str(l.get("non_taxable", ""))
            is_taxable = str(l.get("is_taxable", ""))
            is_customizable = str(l.get("is_customizable", ""))
            is_personalizable = str(l.get("is_personalizable", ""))
            skus = l.get("skus", [])
            sku = ""
            if isinstance(skus, list) and skus:
                sku = str(skus[0])

            html.append("<tr>")
            html.append(f"<td>{listing_id}</td>")
            html.append("<td>")
            html.append(f"<form method='POST' action='/update/{listing_id}'>")
            html.append(f"<input type='text' name='title' value=\"{title}\" style='width:200px;' />")
            html.append("</td>")
            html.append("<td>")
            html.append(f"<textarea name='description' rows='3' cols='30'>{description}</textarea>")
            html.append("</td>")
            html.append("<td>")
            html.append(f"<input type='text' name='state' value='{state}' style='width:80px;' />")
            html.append("</td>")
            html.append("<td>")
            html.append(f"<input type='text' name='quantity' value='{quantity}' style='width:60px;' />")
            html.append("</td>")
            html.append("<td>")
            html.append(f"<input type='text' name='shop_section_id' value='{shop_section_id}' style='width:80px;' />")
            html.append("</td>")
            html.append("<td>")
            html.append(f"<input type='text' name='tags' value='{tags}' style='width:150px;' />")
            html.append("</td>")
            html.append("<td>")
            html.append(f"<input type='text' name='materials' value='{materials}' style='width:150px;' />")
            html.append("</td>")
            html.append("<td>")
            html.append(f"<input type='text' name='shipping_profile_id' value='{shipping_profile_id}' style='width:100px;' />")
            html.append("</td>")
            html.append("<td>")
            html.append(f"<input type='text' name='return_policy_id' value='{return_policy_id}' style='width:100px;' />")
            html.append("</td>")
            html.append("<td>")
            html.append(f"<input type='text' name='processing_min' value='{processing_min}' style='width:60px;' />")
            html.append("</td>")
            html.append("<td>")
            html.append(f"<input type='text' name='processing_max' value='{processing_max}' style='width:60px;' />")
            html.append("</td>")
            html.append("<td>")
            html.append(f"<input type='text' name='who_made' value='{who_made}' style='width:100px;' />")
            html.append("</td>")
            html.append("<td>")
            html.append(f"<input type='text' name='when_made' value='{when_made}' style='width:120px;' />")
            html.append("</td>")
            html.append("<td>")
            html.append(f"<input type='text' name='is_supply' value='{is_supply}' style='width:60px;' />")
            html.append("</td>")
            html.append("<td>")
            html.append(f"<input type='text' name='item_weight' value='{item_weight}' style='width:80px;' />")
            html.append("</td>")
            html.append("<td>")
            html.append(f"<input type='text' name='item_weight_unit' value='{item_weight_unit}' style='width:60px;' />")
            html.append("</td>")
            html.append("<td>")
            html.append(f"<input type='text' name='item_length' value='{item_length}' style='width:80px;' />")
            html.append("</td>")
            html.append("<td>")
            html.append(f"<input type='text' name='item_width' value='{item_width}' style='width:80px;' />")
            html.append("</td>")
            html.append("<td>")
            html.append(f"<input type='text' name='item_height' value='{item_height}' style='width:80px;' />")
            html.append("</td>")
            html.append("<td>")
            html.append(f"<input type='text' name='item_dimensions_unit' value='{item_dimensions_unit}' style='width:80px;' />")
            html.append("</td>")
            html.append("<td>")
            html.append(f"<input type='text' name='is_private' value='{is_private}' style='width:60px;' />")
            html.append("</td>")
            html.append("<td>")
            html.append(f"<input type='text' name='style' value='{style}' style='width:120px;' />")
            html.append("</td>")
            html.append("<td>")
            html.append(f"<input type='text' name='listing_type' value='{listing_type}' style='width:100px;' />")
            html.append("</td>")
            html.append("<td>")
            html.append(f"<input type='text' name='should_auto_renew' value='{should_auto_renew}' style='width:80px;' />")
            html.append("</td>")
            html.append("<td>")
            html.append(f"<input type='text' name='taxonomy_id' value='{taxonomy_id}' style='width:80px;' />")
            html.append("</td>")
            html.append("<td>")
            html.append(f"<input type='text' name='price' value='{price}' style='width:80px;' />")
            html.append("</td>")
            html.append("<td>")
            html.append(f"<input type='text' name='non_taxable' value='{non_taxable}' style='width:80px;' />")
            html.append("</td>")
            html.append("<td>")
            html.append(f"<input type='text' name='is_taxable' value='{is_taxable}' style='width:80px;' />")
            html.append("</td>")
            html.append("<td>")
            html.append(f"<input type='text' name='is_customizable' value='{is_customizable}' style='width:80px;' />")
            html.append("</td>")
            html.append("<td>")
            html.append(f"<input type='text' name='is_personalizable' value='{is_personalizable}' style='width:80px;' />")
            html.append("</td>")
            html.append("<td>")
            html.append(f"<input type='text' name='sku' value='{sku}' style='width:100px;' />")
            html.append("</td>")
            html.append("<td>")
            html.append("<input type='submit' value='Save' />")
            html.append("</td>")
            html.append("</form>")
            html.append("</tr>")
        html.append("</table>")

    html.append("</body></html>")
    return "\n".join(html)


def parse_bool(value):
    v = value.strip().lower()
    if v in ("true", "1", "yes", "y"):
        return True
    if v in ("false", "0", "no", "n"):
        return False
    return None


@app.route("/update/<int:listing_id>", methods=["POST"])
def update_listing(listing_id):
    access_token = session.get("access_token")
    if not access_token:
        return redirect("/login")

    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    state = request.form.get("state", "").strip()
    quantity = request.form.get("quantity", "").strip()
    shop_section_id = request.form.get("shop_section_id", "").strip()
    tags = request.form.get("tags", "").strip()
    materials = request.form.get("materials", "").strip()
    shipping_profile_id = request.form.get("shipping_profile_id", "").strip()
    return_policy_id = request.form.get("return_policy_id", "").strip()
    processing_min = request.form.get("processing_min", "").strip()
    processing_max = request.form.get("processing_max", "").strip()
    who_made = request.form.get("who_made", "").strip()
    when_made = request.form.get("when_made", "").strip()
    is_supply = request.form.get("is_supply", "").strip()
    item_weight = request.form.get("item_weight", "").strip()
    item_weight_unit = request.form.get("item_weight_unit", "").strip()
    item_length = request.form.get("item_length", "").strip()
    item_width = request.form.get("item_width", "").strip()
    item_height = request.form.get("item_height", "").strip()
    item_dimensions_unit = request.form.get("item_dimensions_unit", "").strip()
    is_private = request.form.get("is_private", "").strip()
    style = request.form.get("style", "").strip()
    listing_type = request.form.get("listing_type", "").strip()
    should_auto_renew = request.form.get("should_auto_renew", "").strip()
    taxonomy_id = request.form.get("taxonomy_id", "").strip()
    price = request.form.get("price", "").strip()
    non_taxable = request.form.get("non_taxable", "").strip()
    is_taxable = request.form.get("is_taxable", "").strip()
    is_customizable = request.form.get("is_customizable", "").strip()
    is_personalizable = request.form.get("is_personalizable", "").strip()
    sku = request.form.get("sku", "").strip()

    payload = {}

    if title:
        payload["title"] = title
    if description:
        payload["description"] = description
    if state:
        payload["state"] = state
    if quantity:
        try:
            payload["quantity"] = int(quantity)
        except ValueError:
            pass
    if shop_section_id:
        try:
            payload["shop_section_id"] = int(shop_section_id)
        except ValueError:
            pass
    if tags:
        payload["tags"] = [t.strip() for t in tags.split(",") if t.strip()]
    if materials:
        payload["materials"] = [m.strip() for m in materials.split(",") if m.strip()]
    if shipping_profile_id:
        try:
            payload["shipping_profile_id"] = int(shipping_profile_id)
        except ValueError:
            pass
    if return_policy_id:
        try:
            payload["return_policy_id"] = int(return_policy_id)
        except ValueError:
            pass
    if processing_min:
        try:
            payload["processing_min"] = int(processing_min)
        except ValueError:
            pass
    if processing_max:
        try:
            payload["processing_max"] = int(processing_max)
        except ValueError:
            pass
    if who_made:
        payload["who_made"] = who_made
    if when_made:
        payload["when_made"] = when_made
    if is_supply:
        b = parse_bool(is_supply)
        if b is not None:
            payload["is_supply"] = b
    if item_weight:
        try:
            payload["item_weight"] = float(item_weight)
        except ValueError:
            pass
    if item_weight_unit:
        payload["item_weight_unit"] = item_weight_unit
    if item_length:
        try:
            payload["item_length"] = float(item_length)
        except ValueError:
            pass
    if item_width:
        try:
            payload["item_width"] = float(item_width)
        except ValueError:
            pass
    if item_height:
        try:
            payload["item_height"] = float(item_height)
        except ValueError:
            pass
    if item_dimensions_unit:
        payload["item_dimensions_unit"] = item_dimensions_unit
    if is_private:
        b = parse_bool(is_private)
        if b is not None:
            payload["is_private"] = b
    if style:
        payload["style"] = [s.strip() for s in style.split(",") if s.strip()]
    if listing_type:
        payload["listing_type"] = listing_type
    if should_auto_renew:
        b = parse_bool(should_auto_renew)
        if b is not None:
            payload["should_auto_renew"] = b
    if taxonomy_id:
        try:
            payload["taxonomy_id"] = int(taxonomy_id)
        except ValueError:
            pass
    if price:
        try:
            payload["price"] = float(price)
        except ValueError:
            pass
    if non_taxable:
        b = parse_bool(non_taxable)
        if b is not None:
            payload["non_taxable"] = b
    if is_taxable:
        b = parse_bool(is_taxable)
        if b is not None:
            payload["is_taxable"] = b
    if is_customizable:
        b = parse_bool(is_customizable)
        if b is not None:
            payload["is_customizable"] = b
    if is_personalizable:
        b = parse_bool(is_personalizable)
        if b is not None:
            payload["is_personalizable"] = b
    if sku:
        payload["skus"] = [sku]

    if payload:
        requests.put(
            f"https://api.etsy.com/v3/application/listings/{listing_id}",
            headers={
                "Authorization": f"Bearer {access_token}",
                "x-api-key": f"{CLIENT_ID}:{CLIENT_SECRET}",
                "Content-Type": "application/json",
            },
            json=payload,
        )

    return redirect("/listings")


if __name__ == "__main__":
    app.run()
