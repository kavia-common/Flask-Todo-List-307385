from flask import Flask, render_template, redirect, url_for, request, session, jsonify
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
import os

app = Flask(__name__)
app.secret_key = "secretkey"

users = []
items = []

week_days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
months = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]


def _today_string_and_parts():
    """Builds the same 'today' string used in the template and also returns year/month/day parts."""
    now = datetime.now()
    year = int(now.year)
    month = int(now.month)
    day = int(now.day)
    weekday = now.weekday()
    week_day = week_days[weekday]
    month_name = months[month - 1]
    today_str = f"{day} {month_name} {year}, {week_day}"
    return today_str, year, month, day


def _is_overdue(due_year: int, due_month: int, due_day: int, year: int, month: int, day: int) -> bool:
    """Returns True if (due_year, due_month, due_day) is before (year, month, day)."""
    return (due_year, due_month, due_day) < (year, month, day)


def _recompute_overdue_flags():
    """Recomputes overdue flags for all items based on the current date."""
    _today, year, month, day = _today_string_and_parts()
    for item in items:
        date = item["due_date"]
        item["overdue"] = _is_overdue(date["year"], date["month"], date["day"], year, month, day)


def _json_error(message: str, status_code: int):
    """Creates a consistent JSON error payload."""
    return jsonify({"error": message}), status_code


def _get_allowed_origins():
    """
    Returns a set of allowed origins for CORS.

    Environment variable:
      TODO_APP_ALLOWED_ORIGINS: comma-separated list of origins.
    """
    raw = os.getenv("TODO_APP_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    return {o.strip() for o in raw.split(",") if o.strip()}


@app.before_request
def _handle_api_preflight():
    """Handle CORS preflight for /api/* routes without extra dependencies."""
    if request.method != "OPTIONS":
        return None
    if not request.path.startswith("/api/"):
        return None

    resp = app.make_default_options_response()
    origin = request.headers.get("Origin")
    if origin and origin in _get_allowed_origins():
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        resp.headers["Access-Control-Allow-Methods"] = "GET,POST,DELETE,OPTIONS"
    return resp


@app.after_request
def _add_api_cors_headers(response):
    """Add CORS headers to /api/* responses so the React app can send cookies (credentials)."""
    if request.path.startswith("/api/"):
        origin = request.headers.get("Origin")
        if origin and origin in _get_allowed_origins():
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type"
            response.headers["Access-Control-Allow-Methods"] = "GET,POST,DELETE,OPTIONS"
    return response


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        users.append({"username": username, "password": generate_password_hash(password)})

        return redirect("/login")

    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        for user in users:
            if user["username"] == username and check_password_hash(user["password"], password):
                session["user"] = username
                return redirect("/")

        return "Login failed"

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


@app.route("/", methods=["GET", "POST"])
def home():
    if "user" not in session:
        return redirect("/login")

    if request.method == "POST":
        form_data = request.form
        new_item_content = form_data["newItem"]
        new_item_duedate = form_data["duedate"]

        date_is = new_item_duedate.split("-")
        due_year = int(date_is[0])
        due_month = int(date_is[1])
        due_day = int(date_is[2])

        new_item_id = len(items) + 1
        new_item = {
            "id": int(new_item_id),
            "content": new_item_content,
            "due_date": {"year": due_year, "month": due_month, "day": due_day},
        }
        items.append(new_item)

        _recompute_overdue_flags()

        return redirect(url_for("home"))

    today_str, *_parts = _today_string_and_parts()
    _recompute_overdue_flags()
    return render_template("index.html", list_items=items, today=today_str, leng=len(items))


@app.route("/delete-item", methods=["POST"])
def delete_item():
    if request.method == "POST":
        form = request.form
        item_id = int(form["checkbox"])
        for item in list(items):
            if item["id"] == item_id:
                del items[items.index(item)]
                break
        return redirect("/")


# ---------------------------
# JSON API for React client
# ---------------------------

@app.get("/api/me")
def api_me():
    """Returns the logged-in username based on Flask session cookie, or 401 if not logged in."""
    username = session.get("user")
    if not username:
        return _json_error("Not authenticated", 401)
    return jsonify({"username": username})


@app.post("/api/signup")
def api_signup():
    """Creates a user (in-memory) and returns success."""
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    if not username or not password:
        return _json_error("username and password are required", 400)

    if any(u["username"] == username for u in users):
        return _json_error("username already exists", 409)

    users.append({"username": username, "password": generate_password_hash(password)})
    return jsonify({"ok": True})


@app.post("/api/login")
def api_login():
    """Authenticates user and establishes a session cookie."""
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    if not username or not password:
        return _json_error("username and password are required", 400)

    for user in users:
        if user["username"] == username and check_password_hash(user["password"], password):
            session["user"] = username
            return jsonify({"ok": True, "username": username})

    return _json_error("Login failed", 401)


@app.post("/api/logout")
def api_logout():
    """Clears the session."""
    session.clear()
    return jsonify({"ok": True})


@app.get("/api/todos")
def api_list_todos():
    """Returns the todo list and today's display string; requires authentication."""
    if "user" not in session:
        return _json_error("Not authenticated", 401)

    today_str, *_parts = _today_string_and_parts()
    _recompute_overdue_flags()
    return jsonify({"today": today_str, "items": items})


@app.post("/api/todos")
def api_add_todo():
    """Adds a todo item; requires authentication."""
    if "user" not in session:
        return _json_error("Not authenticated", 401)

    data = request.get_json(silent=True) or {}
    content = (data.get("content") or "").strip()
    due_date = (data.get("dueDate") or "").strip()  # expected YYYY-MM-DD

    if not content or not due_date:
        return _json_error("content and dueDate are required", 400)

    try:
        yyyy, mm, dd = due_date.split("-")
        due_year = int(yyyy)
        due_month = int(mm)
        due_day = int(dd)
    except Exception:
        return _json_error("dueDate must be in YYYY-MM-DD format", 400)

    new_item_id = len(items) + 1
    new_item = {
        "id": int(new_item_id),
        "content": content,
        "due_date": {"year": due_year, "month": due_month, "day": due_day},
    }
    items.append(new_item)
    _recompute_overdue_flags()

    return jsonify({"ok": True, "item": new_item})


@app.delete("/api/todos/<int:item_id>")
def api_delete_todo(item_id: int):
    """Deletes a todo item by id; requires authentication."""
    if "user" not in session:
        return _json_error("Not authenticated", 401)

    for item in list(items):
        if item["id"] == item_id:
            del items[items.index(item)]
            return jsonify({"ok": True})

    return _json_error("Todo not found", 404)


if __name__ == "__main__":
    app.run(debug=True)
