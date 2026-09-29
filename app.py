from flask import Flask, request

app = Flask(__name__)

@app.route("/")
def home():
    return """
    <h1>APMagic</h1>
    <p>Art Plus Music Etsy Manager</p>
    <p>Server online.</p>
    """

@app.route("/callback")
def callback():
    code = request.args.get("code", "No code received")

    return f"""
    <h1>Etsy Callback Received</h1>
    <p>{code}</p>
    """

if __name__ == "__main__":
    app.run()
