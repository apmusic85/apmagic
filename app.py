from flask import Flask, redirect, request
import os

app = Flask(__name__)

CLIENT_ID = os.getenv("ETSY_CLIENT_ID")

CALLBACK_URL = (
    "https://apmagic.artplusmusic.store/callback"
)

@app.route("/")
def home():
    return f"""
    <h1>APMagic</h1>

    <p>Art Plus Music Etsy Manager</p>

    /login
        Login with Etsy
    </a>
    """

@app.route("/login")
def login():

    scopes = "listings_r shops_r"

    url = (
        "https://www.etsy.com/oauth/connect"
        f"?response_type=code"
        f"&redirect_uri={CALLBACK_URL}"
        f"&scope={scopes}"
        f"&client_id={CLIENT_ID}"
    )

    return redirect(url)

@app.route("/callback")
def callback():

    code = request.args.get("code")

    return f"""
    <h1>Etsy Authorization Complete</h1>

    <p>Authorization code:</p>

    <pre>{code}</pre>
    """

if __name__ == "__main__":
    app.run()
