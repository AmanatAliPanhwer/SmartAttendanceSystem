"""
app.py
- Main Flask application for the Smart Attendance System.
- Handles serving HTML pages and API endpoints for face registration and recognition.
"""

import base64
import csv
import datetime
import io
import json
import os
import time

import cv2
import numpy as np
from flask import Flask, jsonify, render_template, request, send_file
from openpyxl import Workbook
from pydantic import ValidationError
from sqlalchemy import desc, extract, func, inspect, text

from models import Attendance, StudentClass, User, SystemSetting, db
from schemas import AttendanceMatch, RecognizeRequest, RecognizeResponse, RegisterRequest
from utils import FaceRecognitionUtils
import pytz

from path_utils import get_resource_path, get_executable_dir

# --- Configuration & Global State ---
KARACHI_TZ = pytz.timezone("Asia/Karachi")

# For Bundled Resources (Static/Templates)
template_dir = get_resource_path("templates")
static_dir = get_resource_path("static")

app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)

# For Persistent Database (outside EXE)
db_dir = os.path.join(get_executable_dir(), "instance")
if not os.path.exists(db_dir):
    os.makedirs(db_dir)
db_path = os.path.join(db_dir, "attendance.db")
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)

# Initialize utilities (loads ONNX models)
try:
    face_utils = FaceRecognitionUtils()
except Exception as e:
    raise RuntimeError(f"CRITICAL: Failed to initialize FaceRecognitionUtils: {e}")

# Recognition State
# known_face_encodings and last_seen_timestamps are now managed via DB and in-memory cache for speed if needed
# For simplicity, we will query DB or load DB into memory.
# To keep performance high, let's load encodings from DB into memory on startup/reload.
known_face_encodings = {}
known_face_metadata = {}  # {name: {class_name, father_name}}
last_seen_timestamps = {}  # {name: timestamp}
RECOGNITION_THRESHOLD = 0.5
ATTENDANCE_COOLDOWN_SECONDS = 60


def load_face_encodings():
    """
    Loads all face encodings from the database into memory.
    """
    global known_face_encodings, known_face_metadata
    try:
        with app.app_context():
            # Only load active students into recognition memory
            users = User.query.filter_by(status='active').all()
            known_face_encodings = {u.name: u.get_encoding() for u in users}
            known_face_metadata = {
                u.name: {"class_name": u.class_name, "father_name": u.father_name} 
                for u in users
            }
            print(f"[System] Loaded {len(known_face_encodings)} active encodings from DB.")
    except Exception as e:
        print(f"[Error] Loading encodings from DB: {e}")
        known_face_encodings = {}
        known_face_metadata = {}


def migrate_database():
    """Manually adds missing columns and tables for automatic schema updates."""
    try:
        with app.app_context():
            inspector = inspect(db.engine)
            
            # 1. Check for missing tables
            existing_tables = inspector.get_table_names()
            if "system_settings" not in existing_tables:
                print("[Migration] system_settings table missing, creating all tables...")
                db.create_all()

            # 2. Check for missing columns in 'users'
            user_columns = [c["name"] for c in inspector.get_columns("users")]
            if "academic_year" not in user_columns:
                print("[Migration] Adding 'academic_year' column to 'users'...")
                with db.engine.connect() as conn:
                    conn.execute(text("ALTER TABLE users ADD COLUMN academic_year VARCHAR(20)"))
                    conn.commit()
            
            if "status" not in user_columns:
                print("[Migration] Adding 'status' column to 'users'...")
                with db.engine.connect() as conn:
                    conn.execute(text("ALTER TABLE users ADD COLUMN status VARCHAR(20) DEFAULT 'active'"))
                    conn.commit()

            # 3. Check for missing columns in 'student_classes'
            class_columns = [c["name"] for c in inspector.get_columns("student_classes")]
            if "next_class_id" not in class_columns:
                print("[Migration] Adding 'next_class_id' column to 'student_classes'...")
                with db.engine.connect() as conn:
                    conn.execute(text("ALTER TABLE student_classes ADD COLUMN next_class_id INTEGER"))
                    conn.commit()

            # 4. Check for missing columns in 'attendance'
            attendance_columns = [c["name"] for c in inspector.get_columns("attendance")]
            if "class_name" not in attendance_columns:
                print("[Migration] Adding 'class_name' column to 'attendance'...")
                with db.engine.connect() as conn:
                    conn.execute(text("ALTER TABLE attendance ADD COLUMN class_name VARCHAR(50)"))
                    conn.commit()

            if "academic_year" not in attendance_columns:
                print("[Migration] Adding 'academic_year' column to 'attendance'...")
                with db.engine.connect() as conn:
                    conn.execute(text("ALTER TABLE attendance ADD COLUMN academic_year VARCHAR(20)"))
                    conn.commit()

            print("[System] Database migration checks complete.")

            attendance_columns = [c["name"] for c in inspector.get_columns("attendance")]
            if "class_name" not in attendance_columns:
                print("[Migration] Adding 'class_name' column to 'attendance'...")
                with db.engine.connect() as conn:
                    conn.execute(text("ALTER TABLE attendance ADD COLUMN class_name VARCHAR(50)"))
                    conn.commit()
            
            if "academic_year" not in attendance_columns:
                print("[Migration] Adding 'academic_year' column to 'attendance'...")
                with db.engine.connect() as conn:
                    conn.execute(text("ALTER TABLE attendance ADD COLUMN academic_year VARCHAR(20)"))
                    conn.commit()

            print("[System] Database migration checks complete.")
    except Exception as e:
        print(f"[Error] Database migration failed: {e}")


def initialize_database():
    """Creates database tables if they don't exist and runs migrations."""
    try:
        with app.app_context():
            # Run migration first to ensure columns exist
            migrate_database()
            db.create_all()
            print("[System] Database initialized.")
    except Exception as e:
        print(f"[Error] Database initialization failed: {e}")


def seed_classes():
    """Seeds the StudentClass table with initial values (1-12) if empty."""
    try:
        with app.app_context():
            if StudentClass.query.first() is None:
                print("[System] Seeding initial classes...")
                initial_classes = [str(i) for i in range(1, 13)]
                class_objs = []
                for c_name in initial_classes:
                    new_cls = StudentClass(name=c_name)
                    db.session.add(new_cls)
                    class_objs.append(new_cls)
                
                db.session.flush() # To get IDs

                # Optional: Pre-set default mappings (1->2, 2->3, ..., 11->12)
                for i in range(len(class_objs) - 1):
                    class_objs[i].next_class_id = class_objs[i+1].id
                
                db.session.commit()
                print("[System] Seeding complete with default mappings.")
    except Exception as e:
        print(f"[Warning] Could not seed classes: {e}")

# Initial load & Migration
initialize_database()
seed_classes()
load_face_encodings()


@app.route("/api/classes")
def get_classes():
    """Returns list of all available student classes."""
    classes = StudentClass.query.order_by(StudentClass.name).all()
    # Sort numerically if possible, otherwise alphabetically
    # Simple alpha sort: "1", "10", "11", "12", "2"... 
    # Let's do a smarter sort in python
    data = [c.name for c in classes]
    try:
        data.sort(key=lambda x: int(x) if x.isdigit() else float('inf'))
    except:
        data.sort()
    return jsonify(data)


# --- Helper Functions ---


def get_setting(key, default=None):
    """Retrieves a system setting from the database."""
    try:
        setting = SystemSetting.query.filter_by(key=key).first()
        return setting.value if setting else default
    except Exception:
        return default


def set_setting(key, value):
    """Sets a system setting in the database."""
    try:
        setting = SystemSetting.query.filter_by(key=key).first()
        if setting:
            setting.value = str(value)
        else:
            db.session.add(SystemSetting(key=key, value=str(value)))
        db.session.commit()
        return True
    except Exception as e:
        db.session.rollback()
        print(f"[Error] Setting system setting {key}: {e}")
        return False


def mark_attendance(name: str) -> tuple[bool, str]:
    """
    Marks attendance for a user in the Database.
    Uses local timezone to determine "today" to avoid timezone-related bugs.
    """
    try:
        user = User.query.filter_by(name=name).first()
        if not user:
            return False, "User not found in DB."

        # Get current local time and determine today's boundaries
        now_local = datetime.datetime.now()
        today_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end_local = now_local.replace(hour=23, minute=59, second=59, microsecond=999999)
        
        # Convert to UTC for database comparison
        # Assume local timezone offset (this works for systems with fixed timezone)
        # Get the UTC offset by comparing naive local time with UTC time
        utc_now = datetime.datetime.utcnow()
        local_now = datetime.datetime.now()
        offset = local_now - utc_now
        
        today_start_utc = today_start_local - offset
        today_end_utc = today_end_local - offset
        
        # Make them timezone-aware for comparison with DB
        today_start_utc = today_start_utc.replace(tzinfo=datetime.timezone.utc)
        today_end_utc = today_end_utc.replace(tzinfo=datetime.timezone.utc)
        
        existing_attendance = Attendance.query.filter(
            Attendance.user_id == user.id,
            Attendance.timestamp >= today_start_utc,
            Attendance.timestamp <= today_end_utc
        ).first()

        if existing_attendance:
            return False, "You are already marked present today."

        new_att = Attendance(user_id=user.id)
        db.session.add(new_att)
        db.session.commit()
        print(f"[Attendance] Marked for {name} in DB")
        return True, "Success"
    except Exception as e:
        db.session.rollback()
        print(f"[Error] Marking attendance: {e}")
        return False, "Database Error"


def ensure_utc(dt):
    """Ensures a datetime object is timezone-aware (UTC)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=datetime.timezone.utc)
    return dt


def decode_base64_to_image(data_url: str) -> np.ndarray:
    """
    Decodes a base64 data URL into an OpenCV image (BGR).

    Args:
        data_url (str): Base64 string (e.g. "data:image/jpeg;base64,...").

    Returns:
        np.ndarray: BGR Image or None if decoding fails.
    """
    try:
        if "," in data_url:
            _, encoded = data_url.split(",", 1)
        else:
            encoded = data_url

        data = base64.b64decode(encoded)
        np_arr = np.frombuffer(data, np.uint8)
        img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        return img
    except Exception as e:
        print(f"[Error] Decoding image: {e}")
        return None


def build_attendance_query(request_args):
    """
    Helper function to build SQLAlchemy query based on request arguments.
    Supports: date/time range, specific Y/M/D, and user_id.
    """
    user_id = request_args.get("user_id", type=int)

    # Advanced Date Filters
    start_iso = request_args.get("start_iso")  # ISO8601 string
    end_iso = request_args.get("end_iso")  # ISO8601 string

    year = request_args.get("year", type=int)
    month = request_args.get("month", type=int)
    day = request_args.get("day", type=int)

    # Legacy/Simple Date Filter (YYYY-MM-DD)
    date_str = request_args.get("date")

    # Join User to get metadata
    query = db.session.query(
        Attendance, 
        User.name, 
        User.class_name, 
        User.father_name
    ).join(User, Attendance.user_id == User.id)

    if user_id:
        query = query.filter(Attendance.user_id == user_id)

    # 1. ISO Range Filter (Takes precedence or works alongside others?)
    # Usually range is specific enough.
    if start_iso and end_iso:
        try:
            start_dt = datetime.datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
            end_dt = datetime.datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
            query = query.filter(Attendance.timestamp >= start_dt, Attendance.timestamp <= end_dt)
        except ValueError:
            pass

    # 2. Granular Filters (Year/Month/Day)
    # Applied if range is not fully specifying everything or used in conjunction
    if year:
        query = query.filter(extract("year", Attendance.timestamp) == year)
    if month:
        query = query.filter(extract("month", Attendance.timestamp) == month)
    if day:
        query = query.filter(extract("day", Attendance.timestamp) == day)

    # 3. Legacy Date Filter (Fallback if no advanced filters)
    if date_str and not (start_iso or year or month or day):
        try:
            date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
            next_day = date_obj + datetime.timedelta(days=1)
            query = query.filter(Attendance.timestamp >= date_obj, Attendance.timestamp < next_day)
        except ValueError:
            pass

    return query.order_by(desc(Attendance.timestamp))


# --- Routes ---


@app.route("/")
def index():
    """Renders the home page."""
    return render_template("index.html")


@app.route("/register")
def register_page():
    """Renders the face registration page."""
    return render_template("register.html")


@app.route("/recognize")
def recognize_page():
    """
    Renders the face recognition/attendance page.
    Refreshes encodings on load to ensure new registrations are active.
    """
    load_face_encodings()
    return render_template("recognize.html")


@app.route("/docs")
def docs_page():
    """Renders the documentation page."""
    return render_template("docs/index.html")


@app.route("/reports")
def reports_page():
    """Renders the reports page."""
    users = User.query.with_entities(User.id, User.name).all()
    return render_template("reports.html", users=users)


@app.route("/dashboard")
def dashboard_page():
    """Renders the dashboard page."""
    return render_template("dashboard.html")


@app.route("/student_analytics")
def student_analytics_page():
    """Renders the individual student analytics page."""
    users = User.query.with_entities(User.id, User.name, User.class_name, User.status, User.father_name).order_by(User.name).all()
    return render_template("student_analytics.html", users=users)


@app.route("/api/student_calendar/<int:user_id>")
def get_student_calendar(user_id):
    """
    API to fetch attendance for a specific student to be displayed on a calendar.
    Returns:
        - attendance_days: List of ISO dates when student was present
        - stats: {month_present, total_present, percentage}
    """
    month = request.args.get("month", type=int)
    year = request.args.get("year", type=int)
    
    # 1. Base Query for all attendance of this user
    query = Attendance.query.filter(Attendance.user_id == user_id)
    
    # 2. Statistics (current month)
    now_karachi = datetime.datetime.now(KARACHI_TZ)
    curr_month = month or now_karachi.month
    curr_year = year or now_karachi.year
    
    month_records = query.filter(
        extract("month", Attendance.timestamp) == curr_month,
        extract("year", Attendance.timestamp) == curr_year
    ).all()
    
    # Use a set to get unique dates (in case of multiple marks per day)
    present_dates = set()
    for att in month_records:
        local_date = ensure_utc(att.timestamp).astimezone(KARACHI_TZ).strftime("%Y-%m-%d")
        present_dates.add(local_date)
    
    month_present_count = len(present_dates)
    
    # 3. Overall stats
    total_present_all_time = db.session.query(db.func.count(db.distinct(db.func.date(Attendance.timestamp)))).filter(
        Attendance.user_id == user_id
    ).scalar() or 0

    return jsonify({
        "present_days": list(present_dates),
        "stats": {
            "month_present": month_present_count,
            "total_present": total_present_all_time,
            "month_name": datetime.date(curr_year, curr_month, 1).strftime("%B"),
            "year": curr_year
        }
    })


@app.route("/api/dashboard_stats")
def get_dashboard_stats():
    """
    API to fetch statistics for the interactive dashboard.
    Returns:
        - total_users: Total registered students
        - today_count: Students present today
        - weekly_data: List of {date, count} for last 7 days
        - class_distribution: Attendance by class for today
        - recent_logs: Last 5 attendance records
    """
    now_karachi = datetime.datetime.now(KARACHI_TZ)
    today_start = now_karachi.replace(hour=0, minute=0, second=0, microsecond=0)
    today_start_utc = today_start.astimezone(pytz.utc)

    # 1. Total Users
    total_users = User.query.count()

    # 2. Today's Attendance
    today_attendance_query = db.session.query(Attendance.user_id).filter(
        Attendance.timestamp >= today_start_utc
    ).distinct()
    today_count = today_attendance_query.count()

    # 3. Weekly Data (Last 7 Days)
    weekly_data = []
    for i in range(6, -1, -1):
        day = today_start - datetime.timedelta(days=i)
        day_end = day + datetime.timedelta(days=1)
        
        count = db.session.query(Attendance.user_id).filter(
            Attendance.timestamp >= day.astimezone(pytz.utc),
            Attendance.timestamp < day_end.astimezone(pytz.utc)
        ).distinct().count()
        
        weekly_data.append({
            "date": day.strftime("%Y-%m-%d"),
            "count": count
        })

    # 4. Class Distribution (Today)
    class_dist = db.session.query(
        User.class_name, db.func.count(db.distinct(Attendance.user_id))
    ).join(Attendance, User.id == Attendance.user_id).filter(
        Attendance.timestamp >= today_start_utc
    ).group_by(User.class_name).all()
    
    class_distribution = [{"class": c or "Unknown", "count": count} for c, count in class_dist]

    # 5. Recent Logs
    recent_logs_query = db.session.query(
        Attendance, User.name, User.class_name
    ).join(User, Attendance.user_id == User.id).order_by(
        desc(Attendance.timestamp)
    ).limit(5).all()

    recent_logs = [
        {
            "name": name,
            "class": class_name,
            "time": ensure_utc(att.timestamp).astimezone(KARACHI_TZ).strftime("%H:%M:%S")
        }
        for att, name, class_name in recent_logs_query
    ]

    return jsonify({
        "total_users": total_users,
        "today_count": today_count,
        "weekly_data": weekly_data,
        "class_distribution": class_distribution,
        "recent_logs": recent_logs
    })


@app.route("/api/attendance_records")
def get_attendance_records():
    """
    API to fetch attendance records with optional filters.
    Query Params:
        user_id (int): User ID
        start_iso (str): Start datetime ISO
        end_iso (str): End datetime ISO
        year, month, day (int): Granular date components
        date (str): Simple YYYY-MM-DD (legacy/simple mode)
    """
    query = build_attendance_query(request.args)
    records = query.all()

    data = [
        {
            "id": att.id,
            "name": name,
            "class_name": class_name,
            "father_name": father_name,
            "timestamp": ensure_utc(att.timestamp).isoformat(),
            "date_str": ensure_utc(att.timestamp).astimezone(KARACHI_TZ).strftime("%Y-%m-%d"),
            "time_str": ensure_utc(att.timestamp).astimezone(KARACHI_TZ).strftime("%H:%M:%S"),
        }
        for att, name, class_name, father_name in records
    ]

    return jsonify(data)


@app.route("/api/export/csv")
def export_csv():
    """Export attendance records to CSV."""
    query = build_attendance_query(request.args)
    records = query.all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Name", "Class", "Father's Name", "Date", "Time", "Timestamp"])

    for att, name, class_name, father_name in records:
        # Convert to Karachi time for export
        local_dt = ensure_utc(att.timestamp).astimezone(KARACHI_TZ)
        writer.writerow(
            [
                att.id,
                name,
                class_name or "",
                father_name or "",
                local_dt.strftime("%Y-%m-%d"),
                local_dt.strftime("%H:%M:%S"),
                local_dt.isoformat(),
            ]
        )

    output.seek(0)

    return send_file(
        io.BytesIO(output.getvalue().encode("utf-8")),
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"attendance_report_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}.csv",
    )


@app.route("/api/export/json")
def export_json():
    """Export attendance records to JSON."""
    query = build_attendance_query(request.args)
    records = query.all()

    data = [
        {
            "id": att.id, 
            "name": name, 
            "class_name": class_name,
            "father_name": father_name,
            "timestamp": ensure_utc(att.timestamp).isoformat()
        } 
        for att, name, class_name, father_name in records
    ]

    return send_file(
        io.BytesIO(json.dumps(data, indent=2).encode("utf-8")),
        mimetype="application/json",
        as_attachment=True,
        download_name=f"attendance_report_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}.json",
    )


@app.route("/api/export/excel")
def export_excel():
    """Export attendance records to Excel (XLSX)."""
    query = build_attendance_query(request.args)
    records = query.all()

    wb = Workbook()
    ws = wb.active
    ws.title = "Attendance Report"

    # Headers
    headers = ["ID", "Name", "Class", "Father's Name", "Date", "Time", "Timestamp"]
    ws.append(headers)

    for att, name, class_name, father_name in records:
        # Convert to Karachi time for export
        local_dt = ensure_utc(att.timestamp).astimezone(KARACHI_TZ)
        ws.append(
            [
                att.id,
                name,
                class_name or "",
                father_name or "",
                local_dt.strftime("%Y-%m-%d"),
                local_dt.strftime("%H:%M:%S"),
                local_dt.isoformat(),
            ]
        )

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    return send_file(
        output,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=f"attendance_report_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}.xlsx",
    )


@app.route("/api/register_capture", methods=["POST"])
def api_register_capture():
    """
    API call to register a new face from a captured image.
    validates with Pydantic.
    """
    if not face_utils:
        return jsonify({"success": False, "message": "Server not initialized."})

    try:
        req_data = RegisterRequest(**request.json)
    except ValidationError as e:
        return jsonify({"success": False, "message": str(e)}), 400

    name = req_data.name
    class_name = req_data.class_name
    father_name = req_data.father_name
    image_data = req_data.image

    frame = decode_base64_to_image(image_data)
    if frame is None:
        return jsonify({"success": False, "message": "Invalid image data."})

    # Convert to RGB for Mediapipe
    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    # Detect faces
    face_bboxes = face_utils.detect_faces_rgb(rgb_frame)
    if not face_bboxes:
        return jsonify({"success": False, "message": "No face detected. Please try again."})

    # Pick the largest face (Assumption: User is close to camera)
    sorted_bboxes = sorted(face_bboxes, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]), reverse=True)
    target_box = sorted_bboxes[0]

    # Preprocess and Align
    face_tensor = face_utils.preprocess_face(rgb_frame, target_box)
    if face_tensor is None:
        return jsonify({"success": False, "message": "Face alignment failed."})

    # Generate Embedding
    face_embedding = face_utils.get_embedding_from_face_tensor(face_tensor)

    # Save to DB
    try:
        existing = User.query.filter_by(name=name).first()
        if existing:
            # Update existing? or Reject? Let's update.
            existing.set_encoding(face_embedding)
            # Update other fields if provided
            if class_name:
                existing.class_name = class_name
            if father_name:
                existing.father_name = father_name
            db.session.commit()
            msg = f"Updated registration for {name}."
        else:
            new_user = User(name=name, class_name=class_name, father_name=father_name)
            new_user.set_encoding(face_embedding)
            db.session.add(new_user)
            db.session.commit()
            msg = f"Successfully registered {name}!"

        # Auto-add class to StudentClass if it doesn't exist
        if class_name:
            try:
                # Check if it exists
                cls_obj = StudentClass.query.filter_by(name=class_name).first()
                if not cls_obj:
                    db.session.add(StudentClass(name=class_name))
                    db.session.commit()
                    print(f"[System] Added new class tag: {class_name}")
            except Exception as e:
                print(f"[Warning] Failed to auto-add class tag: {e}")


        # Reload to update memory
        load_face_encodings()

        return jsonify({"success": True, "message": msg})
    except Exception as e:
        db.session.rollback()
        print(f"[Error] DB Save: {e}")
        return jsonify({"success": False, "message": "Database error saving user."})


@app.route("/api/recognize", methods=["POST"])
def api_recognize():
    """
    API call to recognize faces in a frame and mark attendance.
    Validates with Pydantic.
    """
    if not face_utils:
        return jsonify(
            RecognizeResponse(success=False, matches=[], attendance_error="Server not initialized").model_dump()
        )

    try:
        req_data = RecognizeRequest(**request.json)
    except ValidationError as e:
        # return jsonify({"success": False, "matches": [], "attendance_error": str(e)}), 400
        return jsonify(RecognizeResponse(success=False, matches=[], attendance_error=str(e)).model_dump())

    image_data = req_data.image

    frame = decode_base64_to_image(image_data)
    if frame is None:
        return jsonify(RecognizeResponse(success=False, matches=[]).model_dump())

    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    face_bboxes = face_utils.detect_faces_rgb(rgb_frame)

    matches_payload = []
    attendance_error = None

    known_names = list(known_face_encodings.keys())

    if known_names:
        # Stack all known vectors for batch matrix multiplication
        # Shape: (N, 512)
        known_vectors = np.stack([known_face_encodings[n] for n in known_names], axis=0)

        for box in face_bboxes:
            # box is [x1, y1, x2, y2]
            face_tensor = face_utils.preprocess_face(rgb_frame, box)

            name = "Unknown"
            similarity_score = 0.0
            is_newly_marked = False

            if face_tensor is not None:
                # Get embedding for current face
                current_embedding = face_utils.get_embedding_from_face_tensor(face_tensor)

                # Compare with all known faces (Cosine Similarity)
                # Dot product of normalized vectors = Cosine Similarity
                similarities = np.dot(known_vectors, current_embedding)

                best_idx = int(np.argmax(similarities))
                best_similarity = float(similarities[best_idx])

                if best_similarity >= RECOGNITION_THRESHOLD:
                    name = known_names[best_idx]
                    similarity_score = best_similarity

                    # Attendance Logic
                    current_time = time.time()
                    last_time = last_seen_timestamps.get(name)

                    if (last_time is None) or (current_time - last_time > ATTENDANCE_COOLDOWN_SECONDS):
                        success, msg = mark_attendance(name)
                        if success:
                            last_seen_timestamps[name] = current_time
                            is_newly_marked = True
                            attendance_error = msg
                                # success case: keep `attendance_error` None -- we use `newly_marked` on the client
                        else:
                            attendance_error = msg
            
            # Retrieve metadata
            meta = known_face_metadata.get(name, {})
            
            matches_payload.append(
                AttendanceMatch(
                    box=box, 
                    name=name, 
                    class_name=meta.get("class_name"),
                    father_name=meta.get("father_name"),
                    similarity=float(similarity_score), 
                    newly_marked=is_newly_marked
                )
            )

    else:
        # No known encodings, but we detected faces
        for box in face_bboxes:
            matches_payload.append(
                AttendanceMatch(box=box, name="Unknown (Empty DB)", similarity=0.0, newly_marked=False)
            )

    # Logging outgoing payload for debug: show match names and newly_marked flags
    try:
        debug_matches = []
        for m in matches_payload:
            if hasattr(m, 'name'):
                debug_matches.append((m.name, m.newly_marked))
            else:
                debug_matches.append((m.get('name'), m.get('newly_marked')))
        # print(f"[DEBUG] Recognition response - matches: {debug_matches}, attendance_error: {attendance_error}")
    except Exception:
        print("[DEBUG] Recognition response - unable to inspect matches payload (non-serializable types)")

    return jsonify(RecognizeResponse(success=True, matches=matches_payload, attendance_error=attendance_error).model_dump())


@app.route("/settings")
def settings_page():
    """Renders the settings page."""
    return render_template("settings.html")


@app.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    """API to fetch or update system settings."""
    if request.method == "GET":
        return jsonify({
            "current_academic_year": get_setting("current_academic_year", "2023-2024"),
            "session_start_month": get_setting("session_start_month", "1"),
        })
    
    data = request.json
    if "current_academic_year" in data:
        set_setting("current_academic_year", data["current_academic_year"])
    if "session_start_month" in data:
        set_setting("session_start_month", data["session_start_month"])
        
    return jsonify({"success": True})


@app.route("/api/classes_mapping", methods=["GET", "POST"])
def api_classes_mapping():
    """API to fetch or update class promotion mappings."""
    if request.method == "GET":
        classes = StudentClass.query.all()
        return jsonify([
            {
                "id": c.id,
                "name": c.name,
                "next_class_id": c.next_class_id,
                "next_class_name": c.next_class.name if c.next_class else None
            } for c in classes
        ])
    
    data = request.json # Expecting list of {id, next_class_id}
    try:
        for item in data:
            cls = StudentClass.query.get(item["id"])
            if cls:
                cls.next_class_id = item.get("next_class_id")
        db.session.commit()
        return jsonify({"success": True})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/promote_session", methods=["POST"])
def api_promote_session():
    """Triggers the academic session promotion process."""
    try:
        # 1. Increment Academic Year if provided in body, else just use current
        current_year = get_setting("current_academic_year", "2023-2024")
        # Simple increment logic: "2023-2024" -> "2024-2025"
        try:
            start_yr, end_yr = map(int, current_year.split("-"))
            next_year = f"{start_yr + 1}-{end_yr + 1}"
            set_setting("current_academic_year", next_year)
        except:
            next_year = current_year # Fallback

        # 2. Promote Students
        users = User.query.all()
        promotion_log = []
        
        for user in users:
            # Find current class object
            curr_class = StudentClass.query.filter_by(name=user.class_name).first()
            if curr_class and curr_class.next_class:
                old_class = user.class_name
                user.class_name = curr_class.next_class.name
                user.academic_year = next_year
                promotion_log.append(f"Promoted {user.name}: {old_class} -> {user.class_name}")
            else:
                # If no next class, mark as Graduated (Archive them)
                old_class = user.class_name
                user.status = "graduated"
                user.academic_year = next_year
                promotion_log.append(f"Graduated {user.name} (from {old_class})")
        
        db.session.commit()
        load_face_encodings() # Update memory cache
        return jsonify({"success": True, "next_year": next_year, "log": promotion_log})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/students/<int:user_id>/edit", methods=["POST"])
def api_edit_student(user_id):
    """API to edit student information."""
    try:
        user = User.query.get(user_id)
        if not user:
            return jsonify({"success": False, "message": "Student not found"}), 404
        
        data = request.json
        if "name" in data:
            user.name = data["name"]
        if "father_name" in data:
            user.father_name = data["father_name"]
        if "class_name" in data:
            user.class_name = data["class_name"]
            # Auto-add class if missing
            if user.class_name:
                cls_obj = StudentClass.query.filter_by(name=user.class_name).first()
                if not cls_obj:
                    db.session.add(StudentClass(name=user.class_name))
        
        if "status" in data:
            user.status = data["status"]
        
        db.session.commit()
        load_face_encodings()
        return jsonify({"success": True})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/students/<int:user_id>", methods=["DELETE"])
def api_delete_student(user_id):
    """API to delete a student and their attendance records."""
    try:
        user = User.query.get(user_id)
        if not user:
            return jsonify({"success": False, "message": "Student not found"}), 404
        
        db.session.delete(user)
        db.session.commit()
        load_face_encodings()
        return jsonify({"success": True})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)}), 500


if __name__ == "__main__":
    # Ensure encodings directory exists
    os.makedirs("encodings", exist_ok=True)
    # Run the app
    # Debug=True is great for development
    app.run(host="0.0.0.0", port=5000, debug=True, threaded=True, ssl_context="adhoc")
