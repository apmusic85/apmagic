from flask import Flask, request

app = Flask(__name__)

@app.route("/")
def home():
    return "APMagic is alive"

@app.route("/callback")
def callback():
    code = request.args.get("code")
    return f"Etsy code received: {code}"

if __name__ == "__main__":
    app.run()
