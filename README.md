# Smart Attendance System

A web-based smart attendance system using face recognition. It leverages a Flask backend, MediaPipe for face detection and alignment, and ONNX models for efficient face embedding generation.

## Features

- **Web Interface:** Easy-to-use browser-based interface for registration, recognition, and reporting.
- **Face Registration:** Register students by capturing their face via webcam directly from the browser.
- **Face Recognition:** Real-time face recognition from the webcam feed to mark attendance automatically.
- **Attendance Management & Reports:** View attendance records with advanced filtering and export them to CSV, JSON, or Excel.
- **Database Storage:** Uses SQLite and SQLAlchemy to robustly store user profiles, face encodings, and attendance logs.

## Technologies Used

- **Backend:** Python 3.11+, Flask, Flask-SQLAlchemy, Pydantic
- **Computer Vision:** `mediapipe` (face detection/landmarks), `opencv-python` (image processing), `numpy`, `onnxruntime` (Mobile-ArcFace/MobileFaceNet for embeddings)
- **Database:** SQLite
- **Package Management:** `uv`

## Setup and Installation

1. **Clone the repository:**

   ```bash
   git clone https://github.com/your-username/SmartAttendanceSystem.git
   cd SmartAttendanceSystem
   ```

2. **Install `uv` (if not already installed):**

   ```bash
   pip install uv
   ```

3. **Install dependencies using `uv`:**

   ```bash
   uv sync
   ```

4. **Download ONNX Model:**
   Place your `arcface_mobile.onnx` (a face embedding model) into the `models/` directory. This model is used to generate 512-dimensional face embeddings from aligned face crops.

   ```
   SmartAttendanceSystem/
   ├── models/
   │   └── arcface_mobile.onnx
   └── ...
   ```

5. **Run the application:**

   ```bash
   uv run app.py
   ```

6. **Access the Web App:**
   Open your browser and navigate to `https://localhost:5000` or `https://127.0.0.1:5000`. 
   
   *Note: Your browser might display a security warning because the app uses an ad-hoc self-signed SSL certificate (`ssl_context="adhoc"`). You can safely bypass this warning for local development. HTTPS is required by modern browsers to allow webcam access.*

## Usage

### 1. Register a Student
Navigate to the **Register** page from the navigation bar. Enter the student's name and capture their face using your webcam to save their face embedding to the database.

### 2. Start Attendance Recognition
Navigate to the **Recognize** page. The system will use your webcam to detect and recognize faces in real time. If a registered face is recognized, their attendance will be marked in the database.

### 3. View Reports
Navigate to the **Reports** page to view a table of attendance records. You can filter by date or specific user, and export the data in CSV, JSON, or Excel formats.

## Project Structure

- `app.py`: Main Flask application handling routes, APIs, and business logic.
- `models.py`: SQLAlchemy database models (`User` and `Attendance`).
- `schemas.py`: Pydantic schemas for strict API request/response validation.
- `utils.py`: Core computer vision utilities (MediaPipe face detection, ArcFace embedding).
- `templates/`: HTML templates for the web interface.
- `static/`: Static assets (CSS, JS).
- `models/`: Directory to store the ONNX face embedding model.
- `instance/`: Directory automatically created by Flask-SQLAlchemy to store the SQLite database (`attendance.db`).
- `pyproject.toml` & `uv.lock`: Dependency definitions and lock file.

## Development Conventions

- Python 3.11+ is required.
- Dependencies are strictly managed using `uv`.
- Face detection relies on MediaPipe Face Mesh (replacing older SCRFD implementations).
- Face embeddings are generated using a Mobile-ArcFace ONNX model and stored as pickled NumPy arrays (BLOBs) in the database.
