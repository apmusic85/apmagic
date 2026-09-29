from flask import Flask, redirect, request
import os
import secrets
import hashlib
import base64
import requests

app = Flask(__name__)

CLIENT_ID = os.getenv("ETSY_CLIENT_ID")
CLIENT_SECRET = os.getenv("ETSY_CLIENT_SECRET")

CALLBACK_URL = "https://apmagic.artplusmusic.store/callback"

@app.route("/")
def home():
    return """
    <h1>APMagic</h1>
    <p>Art Plus Music Etsy Manager</p>
    <p>/loginLogin with Etsy</a></p>
    """

@app.route("/login")
def login():

    verifier = secrets.token_urlsafe(64)

    with open("/tmp/verifier.txt", "w") as f:
        f.write(verifier)

    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).decode().rstrip("=")

    state = secrets.token_urlsafe(32)

    url = (
        "https://www.etsy.com/oauth/connect"
        "?response_type=code"
        f"&client_id={CLIENT_ID}"
        f"&redirect_uri={CALLBACK_URL}"
        "&scope=listings_r%20shops_r"
        f"&state={state}"
        f"&code_challenge={challenge}"
        "&code_challenge_method=S256"
    )

    return redirect(url)

@app.route("/callback")
def callback():

    code = request.args.get("code")

    with open("/tmp/verifier.txt", "r") as f:
        verifier = f.read()

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

    return f"""
    <h1>Token Response</h1>
    <pre>{token_response.text}</pre>
    """

if __name__ == "__main__":
    app.run()
