import os
import sys
import sqlite3
import secrets
from pathlib import Path
from datetime import date
from functools import wraps
from getpass import getpass

from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, session, g
)
from werkzeug.security import generate_password_hash, check_password_hash
  
def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped_view


def role_required(*allowed_roles):
    def decorator(view):
        @wraps(view)
        def wrapped_view(*args, **kwargs):
            if not session.get("user_id"):
                flash("Please log in to continue.", "warning")
                return redirect(url_for("login"))

            user = get_current_user()

            if not user or user["role"] not in allowed_roles:
                flash("You do not have permission to perform that action.", "error")
                return redirect(url_for("home"))

            return view(*args, **kwargs)
        return wrapped_view
    return decorator
  

def get_current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    with db() as con:
        return con.execute(
            "SELECT id, name, email, department, role FROM users WHERE id = ?",
            (user_id,)
        ).fetchone()


@app.before_request
def load_logged_in_user():
    g.user = get_current_user()


def get_equipment():
    with db() as con:
        return con.execute(
            "SELECT * FROM equipment ORDER BY department, name"
        ).fetchall()


def get_bookings(user):
    with db() as con:
        query = """
            SELECT b.*, e.name AS equipment_name, e.location
            FROM bookings b
            JOIN equipment e ON e.id = b.equipment_id
        """
        if user["role"] == "Student":
            query += " WHERE b.user_id = ?"
            params = (user["id"],)
        else:
            params = ()
        query += " ORDER BY b.booking_date DESC, b.slot"
        return con.execute(query, params).fetchall()


def slot_is_free(equipment_id, day, slot):
    with db() as con:
        equipment = con.execute(
            "SELECT quantity FROM equipment WHERE id = ?",
            (equipment_id,)
        ).fetchone()
        if not equipment:
            return False

        booked_count = con.execute("""
            SELECT COUNT(*) FROM bookings
            WHERE equipment_id = ?
              AND booking_date = ?
              AND slot = ?
              AND status IN ('Pending', 'Approved')
        """, (equipment_id, day, slot)).fetchone()[0]

    return booked_count < equipment["quantity"]

@app.route("/decision/<int:booking_id>", methods=["POST"])
@login_required
@role_required("Faculty", "Admin")
def decision(booking_id):
    action = request.form.get("action")
    comment = request.form.get("comment", "").strip()

    if action not in ("Approved", "Rejected"):
        flash("Invalid decision.", "error")
        return redirect(url_for("home"))

    with db() as con:
        booking = con.execute(
            "SELECT * FROM bookings WHERE id = ?", (booking_id,)
        ).fetchone()

        if not booking or booking["status"] != "Pending":
            flash("This request is no longer pending.", "warning")
            return redirect(url_for("home"))

        if action == "Approved":
            equipment = con.execute(
                "SELECT quantity FROM equipment WHERE id = ?",
                (booking["equipment_id"],)
            ).fetchone()

            approved_count = con.execute("""
                SELECT COUNT(*) FROM bookings
                WHERE equipment_id = ?
                  AND booking_date = ?
                  AND slot = ?
                  AND status = 'Approved'
                  AND id <> ?
            """, (
                booking["equipment_id"],
                booking["booking_date"],
                booking["slot"],
                booking_id
            )).fetchone()[0]

            if not equipment or approved_count >= equipment["quantity"]:
                flash(
                    "This equipment slot has reached its approval capacity. "
                    "Ask the student to choose another slot.",
                    "warning"
                )
                return redirect(url_for("home"))

        con.execute(
            "UPDATE bookings SET status = ?, faculty_comment = ? WHERE id = ?",
            (action, comment, booking_id)
        )

    flash(f"Request #{booking_id} {action.lower()}.", "success")
    return redirect(url_for("home"))

def add_equipment():
    fields = [
        request.form.get(key, "").strip()
        for key in ("name", "department", "category", "description", "location")
    ]
    quantity = request.form.get("quantity", type=int) or 1

    if not all(fields[:3]) or quantity < 1:
        flash("Enter a name, department, category and a valid quantity.", "error")
        return redirect(url_for("home"))

    with db() as con:
        con.execute("""
            INSERT INTO equipment
            (name, department, category, description, location, quantity)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (*fields, quantity))

    flash("Equipment added to the catalogue.", "success")
    return redirect(url_for("home"))


def create_staff_account():
    """Create Faculty/Admin accounts from the local terminal, not public signup."""
    init_db()
    print("Create a LabLink staff account")
    name = input("Full name: ").strip()
    email = input("Email: ").strip().lower()
    department = input("Department: ").strip()
    role = input("Role (Faculty/Admin): ").strip().title()

    if role not in ("Faculty", "Admin"):
        print("Role must be Faculty or Admin.")
        return
    if not all([name, email, department]):
        print("All fields are required.")
        return

    password = getpass("Password (at least 8 characters): ")
    confirm = getpass("Confirm password: ")
    if len(password) < 8 or password != confirm:
        print("Passwords must match and contain at least 8 characters.")
        return

    try:
        with db() as con:
            con.execute("""
                INSERT INTO users(name, email, department, password_hash, role)
                VALUES (?, ?, ?, ?, ?)
            """, (
                name, email, department,
                generate_password_hash(password), role
            ))
        print(f"{role} account created successfully.")
    except sqlite3.IntegrityError:
        print("An account with that email already exists.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "create-staff":
        create_staff_account()
    else:
        init_db()
        app.run(debug=True)
