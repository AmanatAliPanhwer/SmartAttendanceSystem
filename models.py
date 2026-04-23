import datetime
import pickle

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def utc_now():
    """Returns current UTC time as timezone-aware datetime."""
    return datetime.datetime.now(datetime.timezone.utc)


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    class_name = db.Column(db.String(50), nullable=True)
    father_name = db.Column(db.String(100), nullable=True)
    academic_year = db.Column(db.String(20), nullable=True) # e.g., "2023-2024"
    status = db.Column(db.String(20), default="active") # active, graduated, archived, inactive
    # Storing embedding as a pickled numpy array (BLOB)
    encoding = db.Column(db.LargeBinary, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now)

    # Relationship
    attendances = db.relationship("Attendance", backref="user", lazy=True, cascade="all, delete-orphan")

    def set_encoding(self, np_array):
        self.encoding = pickle.dumps(np_array)

    def get_encoding(self):
        return pickle.loads(self.encoding)


class Attendance(db.Model):
    __tablename__ = "attendance"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    timestamp = db.Column(db.DateTime(timezone=True), default=utc_now)
    class_name = db.Column(db.String(50), nullable=True) # Historical class name
    academic_year = db.Column(db.String(20), nullable=True) # Historical academic year


class StudentClass(db.Model):
    __tablename__ = "student_classes"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    next_class_id = db.Column(db.Integer, db.ForeignKey("student_classes.id"), nullable=True)

    # Relationship for easier access to next class name
    next_class = db.relationship("StudentClass", remote_side=[id], backref="previous_classes")


class SystemSetting(db.Model):
    __tablename__ = "system_settings"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False)
    value = db.Column(db.String(255), nullable=True)
