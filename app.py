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
from sqlalchemy import desc, extract

from models import Attendance, StudentClass, User, db
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
            users = User.query.all()
            known_face_encodings = {u.name: u.get_encoding() for u in users}
            known_face_metadata = {
                u.name: {"class_name": u.class_name, "father_name": u.father_name} 
                for u in users
            }
            print(f"[System] Loaded {len(known_face_encodings)} encodings from DB.")
    except Exception as e:
        print(f"[Error] Loading encodings from DB: {e}")
        known_face_encodings = {}
        known_face_metadata = {}


def initialize_database():
    """Creates database tables if they don't exist."""
    try:
        with app.app_context():
            db.create_all()
            print("[System] Database initialized (Tables created if missing).")
    except Exception as e:
        print(f"[Error] Database initialization failed: {e}")


def seed_classes():
    """Seeds the StudentClass table with initial values (1-12) if empty."""
    try:
        with app.app_context():
            # Check if classes exist by trying to query.
            # If table doesn't exist, this might fail, but since we use db.create_all (or assume it exists), 
            # we should be careful. 
            # In this setup, we assume tables are created manually or exist. 
            # If we were using db.create_all(), we would do it before this.
            if StudentClass.query.first() is None:
                print("[System] Seeding initial classes...")
                initial_classes = [str(i) for i in range(1, 13)]
                for c_name in initial_classes:
                    db.session.add(StudentClass(name=c_name))
                db.session.commit()
                print("[System] Seeding complete.")
    except Exception as e:
        print(f"[Warning] Could not seed classes (Table might not exist yet): {e}")

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


if __name__ == "__main__":
    # Ensure encodings directory exists
    os.makedirs("encodings", exist_ok=True)
    # Run the app
    # Debug=True is great for development
    app.run(host="0.0.0.0", port=5000, debug=True, threaded=True, ssl_context="adhoc")
