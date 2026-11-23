
import os
import sys
import sqlite3
from pathlib import Path
from datetime import date, datetime
from functools import wraps
from getpass import getpass
from dotenv import load_dotenv
from groq import Groq

from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, session, g
)
from werkzeug.security import generate_password_hash, check_password_hash


# --------------------------------------------------
# APP CONFIGURATION
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "lablink.db"

load_dotenv()

groq_client = None
if os.getenv("GROQ_API_KEY"):
    groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
app = Flask(__name__)
app.secret_key = os.environ.get(
    "FLASK_SECRET_KEY",
    "lablink-local-demo-secret-change-before-deployment"
)

SLOTS = [
    "09:00 AM - 10:00 AM",
    "10:00 AM - 11:00 AM",
    "11:00 AM - 12:00 PM",
    "12:00 PM - 01:00 PM",
    "01:00 PM - 02:00 PM",
    "02:00 PM - 03:00 PM",
    "03:00 PM - 04:00 PM",
    "04:00 PM - 05:00 PM"
]


# --------------------------------------------------
# DATABASE
# --------------------------------------------------

def db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(error=None):
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


def get_columns(table):
    return {
        row["name"]
        for row in db().execute(f"PRAGMA table_info({table})").fetchall()
    }


def add_missing_columns(table, columns):
    existing = get_columns(table)

    for column, definition in columns.items():
        if column not in existing:
            db().execute(
                f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
            )


def init_db():
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row

    connection.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            department TEXT NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'Student',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS equipment (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            department TEXT NOT NULL,
            category TEXT,
            location TEXT,
            quantity INTEGER DEFAULT 1,
            description TEXT
        )
    """)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student TEXT,
            department TEXT,
            equipment_id INTEGER,
            project TEXT,
            deadline TEXT,
            booking_date TEXT,
            slot TEXT,
            purpose TEXT,
            status TEXT DEFAULT 'Pending',
            faculty_comment TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    connection.commit()
    connection.close()

    # Safely add columns to databases created by older versions.
    with app.app_context():
        add_missing_columns("users", {
            "name": "TEXT",
            "email": "TEXT",
            "department": "TEXT",
            "password": "TEXT",
            "role": "TEXT DEFAULT 'Student'",
            "created_at": "TEXT"
        })

        add_missing_columns("equipment", {
            "name": "TEXT",
            "department": "TEXT",
            "category": "TEXT",
            "location": "TEXT",
            "quantity": "INTEGER DEFAULT 1",
            "description": "TEXT"
        })

        add_missing_columns("bookings", {
            "student": "TEXT",
            "department": "TEXT",
            "equipment_id": "INTEGER",
            "project": "TEXT",
            "deadline": "TEXT",
            "booking_date": "TEXT",
            "slot": "TEXT",
            "purpose": "TEXT",
            "status": "TEXT DEFAULT 'Pending'",
            "faculty_comment": "TEXT",
            "created_at": "TEXT",
            "user_id": "INTEGER"
        })

        # Seed equipment only when the equipment table is empty.
        count = db().execute(
            "SELECT COUNT(*) FROM equipment"
        ).fetchone()[0]

        if count == 0:
            equipment_items = [
                (
                    "Arduino Uno Kit", "Electronics",
                    "Development Kit", "Electronics Lab 2", 8,
                    "Arduino development board and accessories"
                ),
                (
                    "Raspberry Pi 4", "Computer Science",
                    "Development Kit", "IoT Lab", 5,
                    "Single-board computer for IoT projects"
                ),
                (
                    "3D Printer", "Mechanical",
                    "Fabrication", "Makerspace", 2,
                    "3D printing equipment"
                ),
                (
                    "Digital Oscilloscope", "Electronics",
                    "Test Equipment", "Electronics Lab 1", 4,
                    "Digital signal testing equipment"
                ),
                (
                    "GPU Workstation", "Computer Science",
                    "Workstation", "AI Lab", 3,
                    "High-performance workstation for AI projects"
                ),
                (
                    "Robotics Workstation", "Mechatronics",
                    "Workstation", "Robotics Lab", 2,
                    "Workstation for robotics development"
                )
            ]

            db().executemany("""
                INSERT INTO equipment
                (name, department, category, location, quantity, description)
                VALUES (?, ?, ?, ?, ?, ?)
            """, equipment_items)

        db().commit()


# --------------------------------------------------
# AUTHENTICATION
# --------------------------------------------------

def get_current_user():
    user_id = session.get("user_id")

    if not user_id:
        return None

    return db().execute(
        "SELECT * FROM users WHERE id = ?",
        (user_id,)
    ).fetchone()


@app.before_request
def load_user():
    g.user = get_current_user()


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not g.user:
            flash("Please log in to continue.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped_view


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped_view(*args, **kwargs):
            if not g.user:
                return redirect(url_for("login"))

            if g.user["role"] not in roles:
                flash("You do not have permission to access this page.", "error")
                return redirect(url_for("home"))

            return view(*args, **kwargs)
        return wrapped_view
    return decorator


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        department = request.form.get("department", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not all([name, email, department, password]):
            flash("Please fill in all the fields.", "error")
            return redirect(url_for("register"))

        if password != confirm_password:
            flash("Passwords do not match.", "error")
            return redirect(url_for("register"))

        if len(password) < 6:
            flash("Password must contain at least 6 characters.", "error")
            return redirect(url_for("register"))

        existing = db().execute(
            "SELECT id FROM users WHERE email = ?",
            (email,)
        ).fetchone()

        if existing:
            flash("An account with this email already exists.", "error")
            return redirect(url_for("register"))

        db().execute("""
            INSERT INTO users (name, email, department, password, role)
            VALUES (?, ?, ?, ?, 'Student')
        """, (
            name,
            email,
            department,
            generate_password_hash(password)
        ))
        db().commit()

        flash("Registration successful. Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = db().execute(
            "SELECT * FROM users WHERE email = ?",
            (email,)
        ).fetchone()

        if user and check_password_hash(user["password"], password):
            session.clear()
            session["user_id"] = user["id"]

            flash(f"Welcome back, {user['name']}!", "success")
            return redirect(url_for("home"))

        flash("Invalid email or password.", "error")

    return render_template("login.html")


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


# --------------------------------------------------
# EQUIPMENT AND BOOKING HELPERS
# --------------------------------------------------

def get_equipment():
    return db().execute("""
        SELECT * FROM equipment
        ORDER BY department, name
    """).fetchall()
def get_bookings(user=None):
    query = """
        SELECT bookings.*,
               equipment.name AS equipment_name,
               equipment.location AS location
        FROM bookings
        LEFT JOIN equipment
        ON bookings.equipment_id = equipment.id
    """

    if user and user["role"] == "Student":
        query += """
            WHERE bookings.user_id = ?
            ORDER BY bookings.id DESC
        """
        return db().execute(query, (user["id"],)).fetchall()

    query += " ORDER BY bookings.id DESC"
    return db().execute(query).fetchall()



def slot_is_free(equipment_id, booking_date, slot, exclude_booking_id=None):
    equipment = db().execute(
        "SELECT quantity FROM equipment WHERE id = ?",
        (equipment_id,)
    ).fetchone()

    if not equipment:
        return False

    query = """
        SELECT COUNT(*) FROM bookings
        WHERE equipment_id = ?
        AND booking_date = ?
        AND slot = ?
        AND status IN ('Pending', 'Approved')
    """
    parameters = [equipment_id, booking_date, slot]

    if exclude_booking_id is not None:
        query += " AND id != ?"
        parameters.append(exclude_booking_id)

    booked = db().execute(query, parameters).fetchone()[0]

    return booked < equipment["quantity"]


def get_slot_usage(equipment_id, booking_date, slot):
    return db().execute("""
        SELECT COUNT(*) FROM bookings
        WHERE equipment_id = ?
        AND booking_date = ?
        AND slot = ?
        AND status IN ('Pending', 'Approved')
    """, (equipment_id, booking_date, slot)).fetchone()[0]


# --------------------------------------------------
# SLOT RECOMMENDATION SYSTEM
# --------------------------------------------------

def recommend_slots(equipment_id, booking_date, deadline, student):
    suggestions = []

    equipment = db().execute(
        "SELECT quantity FROM equipment WHERE id = ?",
        (equipment_id,)
    ).fetchone()

    if not equipment:
        return suggestions, {}, 0

    try:
        booking_day = date.fromisoformat(booking_date)
        deadline_day = date.fromisoformat(deadline)
        days_left = (deadline_day - booking_day).days
    except (ValueError, TypeError):
        days_left = 0

    usage = {}

    for slot in SLOTS:
        booked = get_slot_usage(equipment_id, booking_date, slot)
        usage[slot] = booked

        if booked >= equipment["quantity"]:
            continue

        # Fewer bookings means a more available slot.
        score = booked * 10

        # Encourage fair distribution of equipment usage.
        previous_usage = db().execute("""
            SELECT COUNT(*) FROM bookings
            WHERE equipment_id = ?
            AND user_id = ?
            AND status IN ('Pending', 'Approved')
        """, (equipment_id, student["id"])).fetchone()[0]

        score += previous_usage * 2

        reason = "This slot has good equipment availability."

        if booked == 0:
            reason = "No existing bookings for this slot."
        elif booked < equipment["quantity"]:
            reason = "This slot has some remaining equipment capacity."

        if days_left <= 1:
            reason += " It also helps accommodate your close deadline."

        suggestions.append({
            "slot": slot,
            "reason": reason,
            "score": score
        })

    suggestions.sort(key=lambda item: item["score"])

    return suggestions[:3], usage, days_left


# --------------------------------------------------
# HOME PAGE
# --------------------------------------------------

@app.route("/")
@login_required
def home():
    user = g.user

    # Get every equipment item for the booking dropdown.
    all_equipment = get_equipment()

    # Apply search and department filters to the student catalogue.
    search_query = request.args.get("q", "").strip()
    selected_department = request.args.get("department", "").strip()

    equipment_data = []

    for item in all_equipment:
        item_dict = dict(item)

        booked_count = db().execute("""
            SELECT COUNT(*) FROM bookings
            WHERE equipment_id = ?
            AND status IN ('Pending', 'Approved')
        """, (item["id"],)).fetchone()[0]

        item_dict["booked_count"] = booked_count
        item_dict["available_quantity"] = max(
            0, (item["quantity"] or 0) - booked_count
        )
        item_dict["usage_count"] = booked_count

        equipment_data.append(item_dict)

    filtered_equipment = equipment_data

    if search_query:
        filtered_equipment = [
            e for e in filtered_equipment
            if search_query.lower() in e["name"].lower()
            or search_query.lower() in (e["category"] or "").lower()
            or search_query.lower() in (e["description"] or "").lower()
        ]

    if selected_department:
        filtered_equipment = [
            e for e in filtered_equipment
            if e["department"] == selected_department
        ]

    departments = [
        row["department"]
        for row in db().execute("""
            SELECT DISTINCT department
            FROM equipment
            ORDER BY department
        """).fetchall()
    ]

    bookings = get_bookings(user)

    pending_count = db().execute("""
        SELECT COUNT(*) FROM bookings
        WHERE status = 'Pending'
    """).fetchone()[0]

    approved_count = db().execute("""
        SELECT COUNT(*) FROM bookings
        WHERE status = 'Approved'
    """).fetchone()[0]

    total_bookings = db().execute(
        "SELECT COUNT(*) FROM bookings"
    ).fetchone()[0]

    stats = {
        "total_equipment": len(all_equipment),
        "total_bookings": total_bookings,
        "pending_bookings": pending_count,
        "approved_bookings": approved_count
    }

    form_data = session.pop("booking_form", {})
    ai_result = session.pop("ai_result", None)
    ai_project = session.pop("ai_project", "")

    suggestions = []
    usage = {}
    days_left = None

    suggestion_data = session.pop("suggestion_data", None)

    if suggestion_data:
        suggestions = suggestion_data.get("suggestions", [])
        usage = suggestion_data.get("usage", {})
        days_left = suggestion_data.get("days_left")

    return render_template(
        "index.html",
        user=user,
        role=user["role"],
        equipment=filtered_equipment,
        all_equipment=all_equipment,
        bookings=bookings,
        departments=departments,
        stats=stats,
        pending_count=pending_count,
        approved_count=approved_count,
        total_bookings=total_bookings,
        today=date.today().isoformat(),
        slots=SLOTS,
        form_data=form_data,
        suggestions=suggestions,
        usage=usage,
        days_left=days_left,
        ai_result=ai_result,
        ai_project=ai_project,
    )

# --------------------------------------------------
# AI EQUIPMENT RECOMMENDATIONS — GROQ
# --------------------------------------------------

@app.route("/ai-recommend", methods=["POST"])
@login_required
@role_required("Student")
def ai_recommend():
    project_description = request.form.get(
        "project_description", ""
    ).strip()

    if not project_description:
        flash("Please describe your project first.", "error")
        return redirect(url_for("home", _anchor="ai-assistant"))

    if not groq_client:
        flash("AI is not configured. Please check your Groq API key in .env.", "error")
        return redirect(url_for("home", _anchor="ai-assistant"))

    equipment = get_equipment()

    if not equipment:
        flash("No equipment is currently listed in the catalogue.", "error")
        return redirect(url_for("home", _anchor="ai-assistant"))

    catalogue = "\n".join(
        [
            f"- {item['name']} | Department: {item['department']} "
            f"| Category: {item['category']} "
            f"| Quantity: {item['quantity']} "
            f"| Location: {item['location']} "
            f"| Description: {item['description']}"
            for item in equipment
        ]
    )

    prompt = f"""
You are LabLink's campus laboratory equipment recommendation assistant.

A student has described this project:
{project_description}

The following is the complete equipment catalogue:
{catalogue}

Recommend the 2 or 3 most suitable items ONLY from this catalogue.

For each recommendation:
1. Give the exact equipment name.
2. Explain why it suits the project.
3. Mention its department and location.
4. Explain briefly how the student could use it.

If no listed equipment is suitable, say so honestly.
Do not invent equipment or claim that a resource is currently available
for booking. Actual availability is checked separately by LabLink.

Keep the answer clear, practical and student-friendly.
"""

    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful laboratory equipment advisor."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.3,
            max_tokens=600
        )

        session["ai_result"] = response.choices[0].message.content
        session["ai_project"] = project_description

    except Exception as error:
        print("Groq API error:", error)
        flash(
            "The AI recommendation service is temporarily unavailable. Please try again.",
            "error"
        )

    return redirect(url_for("home", _anchor="ai-assistant"))
# --------------------------------------------------
# CREATE A BOOKING
# --------------------------------------------------

@app.route("/book", methods=["POST"])
@login_required
@role_required("Student")
def book():
    user = g.user

    equipment_id = request.form.get("equipment_id", type=int)
    booking_date = request.form.get("booking_date", "").strip()
    slot = request.form.get("slot", "").strip()
    project = request.form.get("project", "").strip()
    deadline = request.form.get("deadline", "").strip()
    purpose = request.form.get("purpose", "").strip()

    form_data = request.form.to_dict()
    session["booking_form"] = form_data

    if not all([
        equipment_id, booking_date, slot,
        project, deadline, purpose
    ]):
        flash("Please complete all booking fields.", "error")
        return redirect(url_for("home", _anchor="booking-form"))

    if slot not in SLOTS:
        flash("Please select a valid time slot.", "error")
        return redirect(url_for("home", _anchor="booking-form"))

    try:
        selected_date = date.fromisoformat(booking_date)
        deadline_date = date.fromisoformat(deadline)
    except ValueError:
        flash("Please enter valid dates.", "error")
        return redirect(url_for("home", _anchor="booking-form"))

    if selected_date < date.today():
        flash("You cannot book a date in the past.", "error")
        return redirect(url_for("home", _anchor="booking-form"))

    if deadline_date < selected_date:
        flash("The project deadline cannot be before the booking date.", "error")
        return redirect(url_for("home", _anchor="booking-form"))

    equipment = db().execute(
        "SELECT id FROM equipment WHERE id = ?",
        (equipment_id,)
    ).fetchone()

    if not equipment:
        flash("Selected equipment does not exist.", "error")
        return redirect(url_for("home"))

    if not slot_is_free(equipment_id, booking_date, slot):
        suggestions, usage, days_left = recommend_slots(
            equipment_id, booking_date, deadline, user
        )

        session["suggestion_data"] = {
            "suggestions": suggestions,
            "usage": usage,
            "days_left": days_left
        }

        flash(
            "That slot is fully booked. Please choose a suggested alternative.",
            "error"
        )
        return redirect(url_for("home", _anchor="booking-form"))

    db().execute("""
        INSERT INTO bookings (
            student, department, equipment_id, project,
            deadline, booking_date, slot, purpose,
            status, user_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Pending', ?)
    """, (
        user["name"],
        user["department"],
        equipment_id,
        project,
        deadline,
        booking_date,
        slot,
        purpose,
        user["id"]
    ))

    db().commit()
    session.pop("booking_form", None)
    session.pop("suggestion_data", None)

    flash("Booking request submitted successfully!", "success")
    return redirect(url_for("home"))


# --------------------------------------------------
# FACULTY APPROVAL / REJECTION
# --------------------------------------------------
@app.route("/decision/<int:booking_id>", methods=["POST"])
@login_required
@role_required("Faculty", "Admin")
def decision(booking_id):
    decision_value = request.form.get(
        "action", request.form.get("decision", "")
    ).strip().title()

    comment = request.form.get(
        "comment", request.form.get("faculty_comment", "")
    ).strip()

    if decision_value not in ["Approved", "Rejected"]:
        flash("Invalid booking decision.", "error")
        return redirect(url_for("home"))

    booking = db().execute(
        "SELECT * FROM bookings WHERE id = ?",
        (booking_id,)
    ).fetchone()

    if not booking:
        flash("Booking not found.", "error")
        return redirect(url_for("home"))

    if booking["status"] != "Pending":
        flash("This booking has already been processed.", "error")
        return redirect(url_for("home"))

    if decision_value == "Approved":
        if not slot_is_free(
            booking["equipment_id"],
            booking["booking_date"],
            booking["slot"],
            exclude_booking_id=booking_id
        ):
            flash(
                "This slot no longer has enough capacity.",
                "error"
            )
            return redirect(url_for("home"))

    db().execute("""
        UPDATE bookings
        SET status = ?, faculty_comment = ?
        WHERE id = ?
    """, (decision_value, comment, booking_id))

    db().commit()

    flash(
        f"Booking {decision_value.lower()} successfully.",
        "success"
    )
    return redirect(url_for("home"))


# --------------------------------------------------
# ADMIN: ADD EQUIPMENT
# --------------------------------------------------

@app.route("/equipment/add", methods=["POST"])
@login_required
@role_required("Admin")
def add_equipment():
    name = request.form.get("name", "").strip()
    department = request.form.get("department", "").strip()
    category = request.form.get("category", "").strip()
    location = request.form.get("location", "").strip()
    description = request.form.get("description", "").strip()
    quantity = request.form.get("quantity", type=int)

    if not all([name, department, category, location]):
        flash("Please complete all required equipment fields.", "error")
        return redirect(url_for("home"))

    if quantity is None or quantity < 1:
        flash("Quantity must be at least 1.", "error")
        return redirect(url_for("home"))

    db().execute("""
        INSERT INTO equipment (
            name, department, category,
            location, quantity, description
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        name, department, category,
        location, quantity, description
    ))

    db().commit()

    flash("Equipment added successfully.", "success")
    return redirect(url_for("home"))


# --------------------------------------------------
# CREATE FACULTY / ADMIN ACCOUNTS
# --------------------------------------------------

def create_staff_account():
    print("\nLabLink - Create Staff Account")
    print("--------------------------------")

    name = input("Name: ").strip()
    email = input("Email: ").strip().lower()
    department = input("Department: ").strip()
    role = input("Role (Faculty/Admin): ").strip().title()

    if role not in ["Faculty", "Admin"]:
        print("Invalid role. Enter Faculty or Admin.")
        return

    if not all([name, email, department]):
        print("All fields are required.")
        return

    password = getpass("Password: ")
    confirm = getpass("Confirm password: ")

    if len(password) < 6:
        print("Password must contain at least 6 characters.")
        return

    if password != confirm:
        print("Passwords do not match.")
        return

    with app.app_context():
        existing = db().execute(
            "SELECT id FROM users WHERE email = ?",
            (email,)
        ).fetchone()

        if existing:
            print("An account with this email already exists.")
            return

        db().execute("""
            INSERT INTO users (name, email, department, password, role)
            VALUES (?, ?, ?, ?, ?)
        """, (
            name,
            email,
            department,
            generate_password_hash(password),
            role
        ))

        db().commit()

    print(f"{role} account created successfully.")


# --------------------------------------------------
# START APPLICATION
# --------------------------------------------------

if __name__ == "__main__":
    init_db()

    if len(sys.argv) > 1 and sys.argv[1] == "create-staff":
        create_staff_account()
    else:
        app.run(debug=True)
