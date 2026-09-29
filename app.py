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
    verifier = session.get("code_verifier")

    if not verifier:
        return "Missing verifier in session"

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
        return f"<pre>{token_data}</pre>"

    access_token = token_data["access_token"]

    states = ["active", "inactive", "sold_out", "draft", "removed", "expired", "edit"]
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
            grouped.setdefault("other", []).append(l)

    return f"""
    <h1>Listings</h1>
    <pre>{json.dumps(grouped, indent=2)}</pre>
    """


if __name__ == "__main__":
    app.run()
