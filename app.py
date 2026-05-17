from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
from datetime import datetime
from pathlib import Path

APP_DIR = Path(__file__).parent
DB_PATH = APP_DIR / "radio_system.db"

app = Flask(__name__)
app.secret_key = "schimba_cheia_asta_intr_o_cheie_lunga_si_secreta"

CHANNELS = [
    "DISPECERAT GENERAL",
    "SMURD",
    "POMPIERI",
    "POLITIE",
    "AMBULANTA",
    "INTERVENTII SPECIALE",
    "LOGISTICA",
    "TEST RADIO"
]

CODES = [
    ("Cod 0", "Mesaj de test / verificare radio"),
    ("Cod 1", "Liber / disponibil"),
    ("Cod 2", "În deplasare"),
    ("Cod 3", "Ajuns la fața locului"),
    ("Cod 4", "Intervenție finalizată"),
    ("Cod 5", "Solicit sprijin"),
    ("Cod ROȘU", "Urgență majoră"),
    ("Cod GALBEN", "Urgență medie"),
    ("Cod VERDE", "Situație stabilă")
]

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = db()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        callsign TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'operator',
        unit TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        active INTEGER DEFAULT 1
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        channel TEXT NOT NULL,
        message TEXT NOT NULL,
        msg_type TEXT NOT NULL DEFAULT 'text',
        created_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)
    cur.execute("SELECT id FROM users WHERE username = ?", ("admin",))
    if not cur.fetchone():
        cur.execute("""
        INSERT INTO users(username, password_hash, callsign, role, unit, created_at, active)
        VALUES(?,?,?,?,?,?,1)
        """, (
            "admin",
            generate_password_hash("admin123"),
            "DISPECERAT-01",
            "admin",
            "Centru Operativ",
            now()
        ))
    conn.commit()
    conn.close()

def now():
    return datetime.now().strftime("%d.%m.%Y %H:%M:%S")

def current_user():
    if "user_id" not in session:
        return None
    conn = db()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    conn.close()
    return user

def login_required():
    return current_user() is not None

@app.context_processor
def inject_globals():
    return {
        "current_user": current_user(),
        "channels": CHANNELS,
        "codes": CODES
    }

@app.route("/")
def index():
    if login_required():
        return redirect(url_for("radio"))
    return redirect(url_for("login"))

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        callsign = request.form.get("callsign", "").strip().upper()
        unit = request.form.get("unit", "").strip()

        if len(username) < 3 or len(password) < 4 or len(callsign) < 2:
            flash("Completează corect datele. Username min. 3 caractere, parolă min. 4, indicativ min. 2.")
            return redirect(url_for("register"))

        conn = db()
        try:
            conn.execute("""
            INSERT INTO users(username, password_hash, callsign, role, unit, created_at, active)
            VALUES(?,?,?,?,?,?,1)
            """, (username, generate_password_hash(password), callsign, "operator", unit, now()))
            conn.commit()
            flash("Cont creat. Te poți autentifica.")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("Username deja folosit.")
        finally:
            conn.close()
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        conn = db()
        user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        conn.close()

        if user and user["active"] == 1 and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            session["channel"] = "DISPECERAT GENERAL"
            return redirect(url_for("radio"))
        flash("Date greșite sau cont dezactivat.")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/radio")
def radio():
    user = current_user()
    if not user:
        return redirect(url_for("login"))
    channel = request.args.get("channel") or session.get("channel") or "DISPECERAT GENERAL"
    if channel not in CHANNELS:
        channel = "DISPECERAT GENERAL"
    session["channel"] = channel
    return render_template("radio.html", selected_channel=channel)

@app.route("/api/messages")
def api_messages():
    user = current_user()
    if not user:
        return jsonify({"error": "not_logged"}), 401

    channel = request.args.get("channel", session.get("channel", "DISPECERAT GENERAL"))
    after_id = int(request.args.get("after_id", 0))

    conn = db()
    rows = conn.execute("""
    SELECT messages.*, users.callsign, users.role, users.unit
    FROM messages
    JOIN users ON messages.user_id = users.id
    WHERE channel = ? AND messages.id > ?
    ORDER BY messages.id ASC
    LIMIT 100
    """, (channel, after_id)).fetchall()
    conn.close()

    return jsonify([dict(r) for r in rows])

@app.route("/api/send", methods=["POST"])
def api_send():
    user = current_user()
    if not user:
        return jsonify({"error": "not_logged"}), 401

    data = request.get_json(force=True)
    channel = data.get("channel", "DISPECERAT GENERAL")
    message = data.get("message", "").strip()
    msg_type = data.get("msg_type", "text")

    if channel not in CHANNELS:
        return jsonify({"error": "bad_channel"}), 400
    if not message:
        return jsonify({"error": "empty"}), 400
    if len(message) > 500:
        return jsonify({"error": "too_long"}), 400

    conn = db()
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO messages(user_id, channel, message, msg_type, created_at)
    VALUES(?,?,?,?,?)
    """, (user["id"], channel, message, msg_type, now()))
    conn.commit()
    msg_id = cur.lastrowid
    conn.close()
    return jsonify({"ok": True, "id": msg_id})

@app.route("/admin")
def admin():
    user = current_user()
    if not user:
        return redirect(url_for("login"))
    if user["role"] != "admin":
        flash("Acces permis doar administratorului.")
        return redirect(url_for("radio"))

    conn = db()
    users = conn.execute("SELECT id, username, callsign, role, unit, created_at, active FROM users ORDER BY id DESC").fetchall()
    messages_count = conn.execute("SELECT COUNT(*) AS c FROM messages").fetchone()["c"]
    conn.close()
    return render_template("admin.html", users=users, messages_count=messages_count)

@app.route("/admin/toggle/<int:user_id>", methods=["POST"])
def toggle_user(user_id):
    user = current_user()
    if not user or user["role"] != "admin":
        return redirect(url_for("login"))
    if user_id == user["id"]:
        flash("Nu îți poți dezactiva propriul cont admin.")
        return redirect(url_for("admin"))
    conn = db()
    target = conn.execute("SELECT active FROM users WHERE id = ?", (user_id,)).fetchone()
    if target:
        new_state = 0 if target["active"] == 1 else 1
        conn.execute("UPDATE users SET active = ? WHERE id = ?", (new_state, user_id))
        conn.commit()
    conn.close()
    return redirect(url_for("admin"))

@app.route("/admin/promote/<int:user_id>", methods=["POST"])
def promote_user(user_id):
    user = current_user()
    if not user or user["role"] != "admin":
        return redirect(url_for("login"))
    conn = db()
    target = conn.execute("SELECT role FROM users WHERE id = ?", (user_id,)).fetchone()
    if target:
        new_role = "operator" if target["role"] == "admin" else "admin"
        conn.execute("UPDATE users SET role = ? WHERE id = ?", (new_role, user_id))
        conn.commit()
    conn.close()
    return redirect(url_for("admin"))

@app.route("/history")
def history():
    user = current_user()
    if not user:
        return redirect(url_for("login"))
    channel = request.args.get("channel", "DISPECERAT GENERAL")
    conn = db()
    rows = conn.execute("""
    SELECT messages.*, users.callsign, users.unit
    FROM messages
    JOIN users ON messages.user_id = users.id
    WHERE channel = ?
    ORDER BY messages.id DESC
    LIMIT 300
    """, (channel,)).fetchall()
    conn.close()
    return render_template("history.html", rows=rows, selected_channel=channel)

if __name__ == "__main__":
    init_db()
    app.run(debug=True, host="127.0.0.1", port=5000)
