"""
app.py
- Main Flask application for the Smart Attendance System (Biometric Registry Mode).
- Handles serving HTML pages and API endpoints for face registration.
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

# --- Configuration & Global State ---
KARACHI_TZ = pytz.timezone("Asia/Karachi")
app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///attendance.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)

# Initialize utilities (loads ONNX models)
try:
    face_utils = FaceRecognitionUtils()
except Exception as e:
    raise RuntimeError(f"CRITICAL: Failed to initialize FaceRecognitionUtils: {e}")

# Recognition State - REMOVED
# known_face_encodings = {}
# known_face_metadata = {} 
# last_seen_timestamps = {} 
# RECOGNITION_THRESHOLD = 0.5
# ATTENDANCE_COOLDOWN_SECONDS = 60


def load_face_encodings():
    """
    Loads all face encodings from the database into memory.
    (Kept for now if we need to validate uniqueness, but mostly unused in Registry Mode)
    """
    pass


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


@app.route("/api/classes")
def get_classes():
    """Returns list of all available student classes."""
    classes = StudentClass.query.order_by(StudentClass.name).all()
    data = [c.name for c in classes]
    try:
        data.sort(key=lambda x: int(x) if x.isdigit() else float('inf'))
    except:
        data.sort()
    return jsonify(data)


# --- Helper Functions ---

def decode_base64_to_image(data_url: str) -> np.ndarray:
    """
    Decodes a base64 data URL into an OpenCV image (BGR).
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


# --- Routes ---


@app.route("/")
def index():
    """Renders the home page with quick stats."""
    user_count = User.query.count()
    latest_user = User.query.order_by(User.id.desc()).first()
    latest_name = latest_user.name if latest_user else "None"
    return render_template("index.html", user_count=user_count, latest_name=latest_name)


@app.route("/register")
def register_page():
    """Renders the face registration page."""
    return render_template("register.html")


@app.route("/docs")
def docs_page():
    """Renders the documentation page."""
    return render_template("docs/index.html")


@app.route("/reports")
def reports_page():
    """Renders the registry reports page."""
    # Fetch all users to display in the registry
    users = User.query.order_by(desc(User.created_at)).all()
    return render_template("reports.html", users=users)


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
    gr_number = req_data.gr_number
    section = req_data.section
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
            user_msg = "Updated biometric registry."
            target_user = existing
            if class_name: existing.class_name = class_name
            if father_name: existing.father_name = father_name
            if gr_number: existing.gr_number = gr_number
            if section: existing.section = section
            existing.set_encoding(face_embedding)
            db.session.commit()
        else:
            user_msg = "Successfully registered!"
            new_user = User(
                name=name, 
                class_name=class_name, 
                father_name=father_name,
                gr_number=gr_number,
                section=section
            )
            new_user.set_encoding(face_embedding)
            db.session.add(new_user)
            db.session.commit()
            target_user = new_user

        # --- Generate and Save Visualizations ---
        if target_user and target_user.id:
            user_id = target_user.id
            
            # 1. Aligned Face
            aligned_face = face_utils.get_aligned_face(rgb_frame, target_box)
            if aligned_face is not None:
                # Save as BGR for cv2
                save_path = os.path.join("static", "faces", f"{user_id}_face.jpg")
                cv2.imwrite(save_path, cv2.cvtColor(aligned_face, cv2.COLOR_RGB2BGR))
            
            # 2. Face Map (Landmarks)
            # We need landmarks again (or could have returned them from get_aligned_face if we refactored, but this is fine)
            img_bgr_for_lms = cv2.cvtColor(rgb_frame, cv2.COLOR_RGB2BGR)
            lms = face_utils.get_face_landmarks_mediapipe(img_bgr_for_lms, target_box)
            if lms:
                # Create map on a black canvas of the same size as the aligned face usually, 
                # but let's base it on the aligned face size for consistency in reports.
                # Actually generate_face_map uses the original image size to plot points. 
                # Let's crop the map to the face box to make it look like a specific "face map".
                
                # Full frame map
                full_map = face_utils.generate_face_map(rgb_frame, lms)
                
                # Crop to face box with some padding
                x1, y1, x2, y2 = target_box
                h, w = full_map.shape[:2]
                pad_x = int((x2 - x1) * 0.2)
                pad_y = int((y2 - y1) * 0.2)
                x1 = max(0, x1 - pad_x)
                y1 = max(0, y1 - pad_y)
                x2 = min(w, x2 + pad_x)
                y2 = min(h, y2 + pad_y)
                
                cropped_map = full_map[y1:y2, x1:x2]
                save_path_map = os.path.join("static", "faces", f"{user_id}_map.jpg")
                cv2.imwrite(save_path_map, cropped_map)

        # Auto-add class
        if class_name:
            if not StudentClass.query.filter_by(name=class_name).first():
                db.session.add(StudentClass(name=class_name))
                db.session.commit()

        return jsonify({"success": True, "message": user_msg})
    except Exception as e:
        db.session.rollback()
        print(f"[Error] DB Save: {e}")
        return jsonify({"success": False, "message": "Database error saving user."})


@app.route("/api/detect_faces", methods=["POST"])
def api_detect_faces():
    """
    API call to detect faces in a frame (for UI feedback only).
    Does NOT perform recognition or mark attendance.
    """
    if not face_utils:
        return jsonify({"success": False, "boxes": []})

    try:
        # We can reuse RecognizeRequest schema since it just needs 'image'
        req_data = RecognizeRequest(**request.json)
    except ValidationError:
        return jsonify({"success": False, "boxes": []})

    image_data = req_data.image
    frame = decode_base64_to_image(image_data)
    if frame is None:
        return jsonify({"success": False, "boxes": []})

    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    face_bboxes = face_utils.detect_faces_rgb(rgb_frame)

    # Return simple boxes list
    # bboxes are [x1, y1, x2, y2]
    return jsonify({"success": True, "boxes": face_bboxes})


@app.route("/api/delete_user/<int:user_id>", methods=["DELETE"])
def delete_user(user_id):
    """
    Deletes a user and their associated biometric files.
    """
    try:
        user = db.session.get(User, user_id)
        if not user:
            return jsonify({"success": False, "message": "User not found."}), 404

        # Delete associated attendance records first to avoid integrity errors
        Attendance.query.filter_by(user_id=user_id).delete()

        # Delete files
        face_path = os.path.join("static", "faces", f"{user.id}_face.jpg")
        map_path = os.path.join("static", "faces", f"{user.id}_map.jpg")
        
        if os.path.exists(face_path):
            os.remove(face_path)
        if os.path.exists(map_path):
            os.remove(map_path)

        # Delete from DB
        db.session.delete(user)
        db.session.commit()
        
        return jsonify({"success": True, "message": f"Deleted user {user.name}."})
    except Exception as e:
        db.session.rollback()
        print(f"[Error] Delete User: {e}")
        return jsonify({"success": False, "message": "Database error deleting user."}), 500


@app.route("/api/export/excel")
def export_excel():
    """Exports the registry data to an Excel file."""
    try:
        users = User.query.all()
        wb = Workbook()
        ws = wb.active
        ws.title = "Biometric Registry"

        # Headers
        headers = ["ID", "Name", "Class", "Section", "Father Name", "GR Number", "Registration Date"]
        ws.append(headers)

        # Data
        for user in users:
            # Format date if available
            ws.append([user.id, user.name, user.class_name, user.section, user.father_name, user.gr_number, "N/A"])

        # Save to memory buffer
        out = io.BytesIO()
        wb.save(out)
        out.seek(0)
        
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"Registry_Export_{timestamp}.xlsx"

        return send_file(
            out,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        print(f"[Error] Export Excel: {e}")
        return f"Error exporting data: {e}", 500


@app.route("/api/export/db")
def export_db():
    """Downloads the SQLite database file."""
    try:
        # Check instance folder first (default for Flask-SQLAlchemy)
        db_path = os.path.join("instance", "attendance.db")
        if not os.path.exists(db_path):
            # Fallback to root if not in instance
            db_path = "attendance.db"
            
        if not os.path.exists(db_path):
            return "Database file not found.", 404
            
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"attendance_backup_{timestamp}.db"

        return send_file(
            db_path,
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        print(f"[Error] Export DB: {e}")
        return f"Error downloading database: {e}", 500


if __name__ == "__main__":
    # Ensure directories exist
    os.makedirs("encodings", exist_ok=True)
    os.makedirs(os.path.join("static", "faces"), exist_ok=True)
    
    # Run the app
    app.run(host="0.0.0.0", port=5000, debug=True, threaded=True, ssl_context="adhoc")
