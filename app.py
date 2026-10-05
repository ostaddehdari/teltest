import hmac
import os
import secrets
import time
from functools import wraps

from flask import Flask, abort, jsonify, redirect, render_template, request, session, url_for

BASE_PATH = "/teltest"
VERSION = os.getenv("TELTEST_VERSION", "0.1.2")
ADMIN_USERNAME = os.getenv("TELTEST_USERNAME", "teletonadmin")
ADMIN_PASSWORD = os.getenv("TELTEST_PASSWORD", "")

app = Flask(
    __name__,
    static_folder="static",
    static_url_path=f"{BASE_PATH}/static",
    template_folder="templates",
)

app.config.update(
    SECRET_KEY=os.environ.get("TELTEST_SECRET_KEY", secrets.token_hex(32)),
    SESSION_COOKIE_NAME="teltest_session",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=os.getenv("TELTEST_COOKIE_SECURE", "1") == "1",
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_PATH=f"{BASE_PATH}/",
    PERMANENT_SESSION_LIFETIME=60 * 60 * 12,
)


def csrf_token() -> str:
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


app.jinja_env.globals["csrf_token"] = csrf_token


def valid_csrf() -> bool:
    expected = session.get("csrf_token", "")
    supplied = request.form.get("csrf_token", "")
    return bool(expected and supplied and hmac.compare_digest(expected, supplied))


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("authenticated"):
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


@app.get(f"{BASE_PATH}/health")
def health():
    return jsonify(
        ok=True,
        app="teltest",
        version=VERSION,
        stage="01",
        status="ready",
    )


@app.route(f"{BASE_PATH}/login", methods=["GET", "POST"])
def login():
    if session.get("authenticated"):
        return redirect(url_for("dashboard"))

    error = None
    if request.method == "POST":
        if not valid_csrf():
            abort(400)

        username = request.form.get("username", "")
        password = request.form.get("password", "")

        user_ok = hmac.compare_digest(username, ADMIN_USERNAME)
        pass_ok = bool(ADMIN_PASSWORD) and hmac.compare_digest(password, ADMIN_PASSWORD)

        if user_ok and pass_ok:
            session.clear()
            session["authenticated"] = True
            session["username"] = ADMIN_USERNAME
            session["csrf_token"] = secrets.token_urlsafe(32)
            session.permanent = True
            return redirect(url_for("dashboard"))

        time.sleep(0.45)
        error = "نام کاربری یا رمز عبور صحیح نیست."

    return render_template("login.html", error=error, version=VERSION)


@app.post(f"{BASE_PATH}/logout")
@login_required
def logout():
    if not valid_csrf():
        abort(400)
    session.clear()
    return redirect(url_for("login"))


@app.get(f"{BASE_PATH}/")
@login_required
def dashboard():
    stats = {
        "accounts": 0,
        "channels": 0,
        "jobs": 0,
        "posts": 0,
        "forwarded": 0,
        "failed": 0,
    }
    return render_template(
        "dashboard.html",
        username=session.get("username", ADMIN_USERNAME),
        version=VERSION,
        stats=stats,
    )


@app.get(f"{BASE_PATH}")
def dashboard_no_slash():
    return redirect(url_for("dashboard"))


@app.errorhandler(400)
def bad_request(_error):
    return "Bad request", 400


@app.errorhandler(404)
def not_found(_error):
    return "Not found", 404


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=18870, debug=False)
