from flask import Flask, redirect, request, session
import os
import secrets
import hashlib
import base64
import requests

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
    <a href="/loginh Etsy</a>
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
            "code_verifier": verifier
        }
    )

    token_data = token_response.json()

    if "access_token" not in token_data:
        return f"<pre>{token_data}</pre>"

    access_token = token_data["access_token"]

    listings_response = requests.get(
        f"https://openapi.etsy.com/v3/application/shops/{SHOP_ID}/listings",
        headers={
            "Authorization": f"Bearer {access_token}",
            "x-api-key": f"{CLIENT_ID}:{CLIENT_SECRET}"
        }
    )

    return f"""
    <h1>Listings</h1>
    <pre>{listings_response.text}</pre>
    """


if __name__ == "__main__":
    app.run()
