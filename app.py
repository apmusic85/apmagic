from flask import Flask, redirect, request
import os
import secrets
import hashlib
import base64

app = Flask(__name__)

CLIENT_ID = os.getenv("ETSY_CLIENT_ID")
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

    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).decode().rstrip("=")

    state = secrets.token_urlsafe(32)

    with open("/tmp/verifier.txt", "w") as f:
        f.write(verifier)

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

    return f"""
    <h1>Etsy Authorization Complete</h1>
    <p>Authorization Code:</p>
    <pre>{code}</pre>
    """

if __name__ == "__main__":
    app.run()
