import hashlib
import os
import re
import secrets
from datetime import datetime, timedelta, timezone


import mysql.connector
from flask import Flask, jsonify, request, send_from_directory, session
from mysql.connector import errorcode
from werkzeug.security import check_password_hash, generate_password_hash

from flask import Flask
from flask_cors import CORS

app = Flask(__name__)

CORS(
    app,
    supports_credentials=True,
    resources={r"/*": {
        "origins": [
            "https://certify-me-assessment-zqqv.vercel.app"
        ]
    }}
)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "sky")

app.secret_key = os.environ.get("SECRET_KEY", "dev-change-this-secret-key")
app.permanent_session_lifetime = timedelta(days=30)

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
CATEGORY_MAP = {
    "technology": "Technology",
    "business": "Business",
    "design": "Design",
    "marketing": "Marketing",
    "data": "Data Science",
    "data science": "Data Science",
    "other": "Other",
}
VALID_CATEGORIES = set(CATEGORY_MAP.values())


def db_config(include_database=True):
    config = {
        "host": os.environ.get("MYSQL_HOST", "localhost"),
        "port": int(os.environ.get("MYSQL_PORT", "3306")),
        "user": os.environ.get("MYSQL_USER", "root"),
        "password": os.environ.get("MYSQL_PASSWORD", ""),
    }
    if include_database:
        config["database"] = os.environ.get("MYSQL_DATABASE", "certify_me")
    return config


def get_db():
    return mysql.connector.connect(**db_config())


def init_db():
    database = os.environ.get("MYSQL_DATABASE", "certify_me")
    root_conn = mysql.connector.connect(**db_config(include_database=False))
    root_cursor = root_conn.cursor()
    root_cursor.execute(
        f"CREATE DATABASE IF NOT EXISTS `{database}` "
        "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
    )
    root_cursor.close()
    root_conn.close()

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS admins (
            id INT AUTO_INCREMENT PRIMARY KEY,
            full_name VARCHAR(255) NOT NULL,
            email VARCHAR(255) NOT NULL UNIQUE,
            password_hash VARCHAR(255) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            id INT AUTO_INCREMENT PRIMARY KEY,
            admin_id INT NOT NULL,
            token_hash CHAR(64) NOT NULL UNIQUE,
            expires_at DATETIME NOT NULL,
            used_at DATETIME NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_reset_token_hash (token_hash),
            CONSTRAINT fk_reset_admin
                FOREIGN KEY (admin_id) REFERENCES admins(id)
                ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS opportunities (
            id INT AUTO_INCREMENT PRIMARY KEY,
            admin_id INT NOT NULL,
            name VARCHAR(255) NOT NULL,
            duration VARCHAR(100) NOT NULL,
            start_date DATE NOT NULL,
            description TEXT NOT NULL,
            skills TEXT NOT NULL,
            category VARCHAR(50) NOT NULL,
            future_opportunities TEXT NOT NULL,
            max_applicants INT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_opportunities_admin (admin_id),
            CONSTRAINT fk_opportunities_admin
                FOREIGN KEY (admin_id) REFERENCES admins(id)
                ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    cursor.close()
    conn.close()


def api_error(message, status=400):
    return jsonify({"error": message}), status


def current_admin_id():
    return session.get("admin_id")


def require_admin():
    admin_id = current_admin_id()
    if not admin_id:
        return None, api_error("Authentication required", 401)
    return admin_id, None


def normalize_email(email):
    return (email or "").strip().lower()


def normalize_category(value):
    raw = (value or "").strip()
    return CATEGORY_MAP.get(raw.lower(), raw)


def token_digest(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def serialize_opportunity(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "duration": row["duration"],
        "startDate": row["start_date"].isoformat(),
        "description": row["description"],
        "skills": [skill.strip() for skill in row["skills"].split(",") if skill.strip()],
        "category": row["category"],
        "futureOpportunities": row["future_opportunities"],
        "maxApplicants": row["max_applicants"],
    }


def validate_opportunity_payload(payload):
    name = (payload.get("name") or "").strip()
    duration = (payload.get("duration") or "").strip()
    start_date = (payload.get("startDate") or payload.get("start_date") or "").strip()
    description = (payload.get("description") or "").strip()
    skills = payload.get("skills")
    category = normalize_category(payload.get("category"))
    future = (payload.get("futureOpportunities") or payload.get("future_opportunities") or "").strip()
    max_applicants = payload.get("maxApplicants", payload.get("max_applicants"))

    if isinstance(skills, list):
        skill_list = [str(skill).strip() for skill in skills if str(skill).strip()]
    else:
        skill_list = [skill.strip() for skill in str(skills or "").split(",") if skill.strip()]

    if not all([name, duration, start_date, description, skill_list, category, future]):
        return None, "All required opportunity fields must be filled"
    if category not in VALID_CATEGORIES:
        return None, "Invalid category"

    try:
        parsed_date = datetime.strptime(start_date, "%Y-%m-%d").date()
    except ValueError:
        return None, "Start date must use YYYY-MM-DD format"

    if max_applicants in ("", None):
        parsed_max = None
    else:
        try:
            parsed_max = int(max_applicants)
        except (TypeError, ValueError):
            return None, "Maximum applicants must be a number"
        if parsed_max < 0:
            return None, "Maximum applicants cannot be negative"

    return {
        "name": name,
        "duration": duration,
        "start_date": parsed_date,
        "description": description,
        "skills": ", ".join(skill_list),
        "category": category,
        "future_opportunities": future,
        "max_applicants": parsed_max,
    }, None


@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "admin.html")


@app.route("/api/auth/signup", methods=["POST"])
def signup():
    payload = request.get_json(silent=True) or {}
    full_name = (payload.get("fullName") or payload.get("full_name") or "").strip()
    email = normalize_email(payload.get("email"))
    password = payload.get("password") or ""
    confirm_password = payload.get("confirmPassword") or payload.get("confirm_password") or ""

    if not full_name or not email or not password or not confirm_password:
        return api_error("All fields are required")
    if not EMAIL_RE.match(email):
        return api_error("Please enter a valid email address")
    if len(password) < 8:
        return api_error("Password must be at least 8 characters")
    if password != confirm_password:
        return api_error("Passwords do not match")

    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO admins (full_name, email, password_hash) VALUES (%s, %s, %s)",
            (full_name, email, generate_password_hash(password)),
        )
        conn.commit()
    except mysql.connector.Error as err:
        if err.errno == errorcode.ER_DUP_ENTRY:
            return api_error("Account already exists", 409)
        raise
    finally:
        if "cursor" in locals():
            cursor.close()
        if "conn" in locals():
            conn.close()

    return jsonify({"message": "Account created successfully"})


@app.route("/api/auth/login", methods=["POST"])
def login():
    payload = request.get_json(silent=True) or {}
    email = normalize_email(payload.get("email"))
    password = payload.get("password") or ""
    remember_me = bool(payload.get("rememberMe") or payload.get("remember_me"))

    if not email or not password:
        return api_error("Invalid email or password", 401)

    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id, full_name, email, password_hash FROM admins WHERE email = %s", (email,))
    admin = cursor.fetchone()
    cursor.close()
    conn.close()

    if not admin or not check_password_hash(admin["password_hash"], password):
        return api_error("Invalid email or password", 401)

    session.clear()
    session.permanent = remember_me
    session["admin_id"] = admin["id"]
    session["admin_name"] = admin["full_name"]
    session["admin_email"] = admin["email"]

    return jsonify({
        "message": "Login successful",
        "admin": {"id": admin["id"], "fullName": admin["full_name"], "email": admin["email"]},
    })


@app.route("/api/auth/me")
def me():
    admin_id = current_admin_id()
    if not admin_id:
        return jsonify({"admin": None}), 401
    return jsonify({
        "admin": {
            "id": admin_id,
            "fullName": session.get("admin_name"),
            "email": session.get("admin_email"),
        }
    })


@app.route("/api/auth/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"message": "Signed out successfully"})


@app.route("/api/auth/forgot-password", methods=["POST"])
def forgot_password():
    payload = request.get_json(silent=True) or {}
    email = normalize_email(payload.get("email"))
    public_message = "If the email is registered, a reset link has been generated."

    if not email or not EMAIL_RE.match(email):
        return api_error("Please enter a valid email address")

    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id FROM admins WHERE email = %s", (email,))
    admin = cursor.fetchone()

    if admin:
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1)
        cursor.execute(
            "INSERT INTO password_reset_tokens (admin_id, token_hash, expires_at) VALUES (%s, %s, %s)",
            (admin["id"], token_digest(token), expires_at),
        )
        conn.commit()
        reset_link = request.host_url.rstrip("/") + "/reset-password/" + token
        app.logger.info("Password reset link for %s: %s", email, reset_link)

    cursor.close()
    conn.close()
    return jsonify({"message": public_message})


@app.route("/reset-password/<token>")
def reset_password_link(token):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """
        SELECT expires_at, used_at
        FROM password_reset_tokens
        WHERE token_hash = %s
        """,
        (token_digest(token),),
    )
    reset = cursor.fetchone()
    cursor.close()
    conn.close()

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if not reset:
        return "Invalid reset link.", 404
    if reset["used_at"] or reset["expires_at"] < now:
        return "This reset link has expired. Please request a new password reset link.", 400
    return "This reset link is valid. Password update form is not enabled in this stage."


@app.route("/api/opportunities", methods=["GET"])
def list_opportunities():
    admin_id, error = require_admin()
    if error:
        return error

    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """
        SELECT id, name, duration, start_date, description, skills, category,
               future_opportunities, max_applicants
        FROM opportunities
        WHERE admin_id = %s
        ORDER BY created_at DESC, id DESC
        """,
        (admin_id,),
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify({"opportunities": [serialize_opportunity(row) for row in rows]})


@app.route("/api/opportunities", methods=["POST"])
def create_opportunity():
    admin_id, error = require_admin()
    if error:
        return error

    data, validation_error = validate_opportunity_payload(request.get_json(silent=True) or {})
    if validation_error:
        return api_error(validation_error)

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO opportunities
            (admin_id, name, duration, start_date, description, skills, category,
             future_opportunities, max_applicants)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            admin_id,
            data["name"],
            data["duration"],
            data["start_date"],
            data["description"],
            data["skills"],
            data["category"],
            data["future_opportunities"],
            data["max_applicants"],
        ),
    )
    opportunity_id = cursor.lastrowid
    conn.commit()
    cursor.close()
    conn.close()
    return get_opportunity_response(opportunity_id, 201)


def get_opportunity_response(opportunity_id, status=200):
    admin_id = current_admin_id()
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """
        SELECT id, name, duration, start_date, description, skills, category,
               future_opportunities, max_applicants
        FROM opportunities
        WHERE id = %s AND admin_id = %s
        """,
        (opportunity_id, admin_id),
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    if not row:
        return api_error("Opportunity not found", 404)
    return jsonify({"opportunity": serialize_opportunity(row)}), status


@app.route("/api/opportunities/<int:opportunity_id>", methods=["GET"])
def get_opportunity(opportunity_id):
    admin_id, error = require_admin()
    if error:
        return error
    return get_opportunity_response(opportunity_id)


@app.route("/api/opportunities/<int:opportunity_id>", methods=["PUT"])
def update_opportunity(opportunity_id):
    admin_id, error = require_admin()
    if error:
        return error

    data, validation_error = validate_opportunity_payload(request.get_json(silent=True) or {})
    if validation_error:
        return api_error(validation_error)

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE opportunities
        SET name = %s, duration = %s, start_date = %s, description = %s,
            skills = %s, category = %s, future_opportunities = %s, max_applicants = %s
        WHERE id = %s AND admin_id = %s
        """,
        (
            data["name"],
            data["duration"],
            data["start_date"],
            data["description"],
            data["skills"],
            data["category"],
            data["future_opportunities"],
            data["max_applicants"],
            opportunity_id,
            admin_id,
        ),
    )
    conn.commit()
    affected = cursor.rowcount
    cursor.close()
    conn.close()
    if affected == 0:
        return api_error("Opportunity not found", 404)
    return get_opportunity_response(opportunity_id)


@app.route("/api/opportunities/<int:opportunity_id>", methods=["DELETE"])
def delete_opportunity(opportunity_id):
    admin_id, error = require_admin()
    if error:
        return error

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM opportunities WHERE id = %s AND admin_id = %s",
        (opportunity_id, admin_id),
    )
    conn.commit()
    affected = cursor.rowcount
    cursor.close()
    conn.close()
    if affected == 0:
        return api_error("Opportunity not found", 404)
    return jsonify({"message": "Opportunity deleted successfully"})


with app.app_context():
    init_db()



if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=False
    )