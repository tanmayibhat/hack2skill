# LabLink Prototype

A Flask + SQLite prototype for campus laboratory resource sharing.

## Features
- Search/filter shared equipment across departments
- Student project-based booking requests
- Slot conflict checking and alternative-slot suggestions
- Faculty approval/rejection with comments
- Admin equipment catalogue management
- Dashboard counts for resources and booking statuses

## Run locally
1. Install Python 3.10+.
2. Open a terminal in this folder.
3. Create/activate a virtual environment (optional but recommended).
4. Install dependencies:
   `pip install -r requirements.txt`
5. Start the application:
   `python app.py`
6. Open `http://127.0.0.1:5000`.

The database `lablink.db` is created automatically and seeded with sample equipment.

## Demo roles
Use the role selector at the top-right to switch between Student, Faculty, and Admin.
This is a classroom prototype: role switching is intentionally simplified and is not secure authentication.

## Scheduling logic
The prototype blocks a resource/date/time slot if another request is pending or approved.
When a conflict occurs, it lists available slots for the selected date and displays the student's active-request count and deadline gap as transparent fairness/context signals. This is a rule-based demonstration, not a connected GenAI model.

## Notes before real deployment
Add authentication, role-based authorization, CSRF protection, audit logs, resource-specific capacity handling, and proper tests. The demo treats each equipment record as one reservable unit per slot; quantity is displayed but not yet used for parallel capacity allocation.
