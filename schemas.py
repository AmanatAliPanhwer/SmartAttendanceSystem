from typing import List, Optional

from pydantic import BaseModel


class RegisterRequest(BaseModel):
    name: str
    class_name: Optional[str] = None
    father_name: Optional[str] = None
    gr_number: Optional[str] = None
    section: Optional[str] = None
    gender: Optional[str] = None
    image: str  # Base64 string


class RecognizeRequest(BaseModel):
    image: str  # Base64 string


class AttendanceMatch(BaseModel):
    box: List[int]
    name: str
    class_name: Optional[str] = None
    father_name: Optional[str] = None
    gender: Optional[str] = None
    similarity: float
    newly_marked: bool


class RecognizeResponse(BaseModel):
    success: bool
    matches: List[AttendanceMatch]
    attendance_error: Optional[str] = None
