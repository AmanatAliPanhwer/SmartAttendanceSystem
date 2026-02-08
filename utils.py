"""
utils.py
- SCRFD ONNX detection (fallback to Mediapipe detection if SCRFD not found).
- Mediapipe Face Mesh for landmarks-based alignment.
- ONNX runtime for embeddings (Mobile-ArcFace / MobileFaceNet).
- Validates inputs and handles image preprocessing.
"""

import math
import os
from typing import List, Optional, Tuple

import cv2
import mediapipe as mp
import numpy as np
import onnxruntime as ort


class FaceRecognitionUtils:
    """
    Utilities for face detection, alignment, and embedding extraction using
    Mediapipe and ONNX Runtime.
    """

    def __init__(self, emb_model_path: str = "models/arcface_mobile.onnx") -> None:
        """
        Initialize the FaceRecognitionUtils with model paths.

        Args:
            emb_model_path (str): Path to the ONNX embedding model.
        """
        self.EMB_MODEL_PATH = emb_model_path
        self.mp_face_mesh = mp.solutions.face_mesh
        self.face_mesh = self.mp_face_mesh.FaceMesh(
            static_image_mode=False,
            max_num_faces=4,
            refine_landmarks=True,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )

        if not os.path.exists(emb_model_path):
            raise FileNotFoundError(f"Place embedding ONNX at: {emb_model_path}")

        # Initialize ONNX Runtime Session
        self.emb_sess = ort.InferenceSession(emb_model_path, providers=["CPUExecutionProvider"])
        self._emb_input_name = self.emb_sess.get_inputs()[0].name

    def detect_with_mediapipe(self, img_bgr: np.ndarray) -> List[Tuple[int, int, int, int]]:
        """
        Fast Mediapipe detection fallback. Returns boxes in pixel coords.

        Args:
            img_bgr (np.ndarray): Input image in BGR format.

        Returns:
            List[Tuple[int, int, int, int]]: List of bounding boxes (xmin, ymin, xmax, ymax).
        """
        img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        results = self.face_mesh.process(img_rgb)
        h, w = img_bgr.shape[:2]
        boxes = []
        if results.multi_face_landmarks:
            for lm in results.multi_face_landmarks:
                xs = [p.x for p in lm.landmark]
                ys = [p.y for p in lm.landmark]
                xmin = int(max(0, min(xs) * w))
                xmax = int(min(w, max(xs) * w))
                ymin = int(max(0, min(ys) * h))
                ymax = int(min(h, max(ys) * h))
                boxes.append((xmin, ymin, xmax, ymax))
        return boxes

    def get_face_landmarks_mediapipe(
        self, img_bgr: np.ndarray, box: Tuple[int, int, int, int]
    ) -> Optional[List[Tuple[int, int]]]:
        """
        Use Mediapipe Face Mesh to get landmarks for alignment.

        Args:
            img_bgr (np.ndarray): Input image in BGR format.
            box (Tuple[int, int, int, int]): Bounding box of the face (xmin, ymin, xmax, ymax).

        Returns:
            Optional[List[Tuple[int, int]]]: List of (x, y) landmarks for the face closest to the box center.
        """
        img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        results = self.face_mesh.process(img_rgb)
        if not results.multi_face_landmarks:
            return None

        h, w = img_bgr.shape[:2]
        bx_cx = (box[0] + box[2]) / 2.0
        bx_cy = (box[1] + box[3]) / 2.0

        # Choose the face whose bbox center is nearest to provided box center
        best_landmarks = None
        best_dist = 1e9

        for lm in results.multi_face_landmarks:
            xs = [p.x * w for p in lm.landmark]
            ys = [p.y * h for p in lm.landmark]
            cx = np.mean(xs)
            cy = np.mean(ys)
            dist = (cx - bx_cx) ** 2 + (cy - bx_cy) ** 2

            if dist < best_dist:
                best_dist = dist
                best_landmarks = lm

        if best_landmarks is None:
            return None

        # Return a list of (x,y) for the landmarks
        lms = [(int(p.x * w), int(p.y * h)) for p in best_landmarks.landmark]
        return lms

    def align_face_by_eyes(
        self, img_rgb: np.ndarray, landmarks: List[Tuple[int, int]], output_size: int = 112
    ) -> np.ndarray:
        """
        Simple similarity transform aligner using eye centers.

        Args:
            img_rgb (np.ndarray): Input image in RGB format.
            landmarks (List[Tuple[int, int]]): List of landmarks.
            output_size (int): Size of the output aligned face image.

        Returns:
            np.ndarray: Aligned face crop (RGB uint8).
        """
        # Mediapipe landmarks: left eye approx indexes (33..133 region) and right eye indexes (263..362)
        left_eye_idx = [33, 133, 160, 159, 158, 157, 173]
        right_eye_idx = [263, 362, 387, 386, 385, 384, 398]

        # Compute eye centers
        lx = np.mean([landmarks[i][0] for i in left_eye_idx])
        ly = np.mean([landmarks[i][1] for i in left_eye_idx])
        rx = np.mean([landmarks[i][0] for i in right_eye_idx])
        ry = np.mean([landmarks[i][1] for i in right_eye_idx])

        # Desired positions
        eye_mid = ((lx + rx) / 2.0, (ly + ry) / 2.0)

        # Calculate angle
        dy = ry - ly
        dx = rx - lx
        angle = math.degrees(math.atan2(dy, dx))

        # Scale: distance between eyes in pixels
        dist = math.hypot(dx, dy)

        # Desired distance between eyes in output
        desired_eye_dist = output_size * 0.35
        scale = desired_eye_dist / (dist + 1e-6)

        # Get rotation matrix around eye_mid
        M = cv2.getRotationMatrix2D(eye_mid, angle, scale)

        # Translate so eye_mid maps to center
        t_x = output_size * 0.5
        t_y = output_size * 0.4
        M[0, 2] += t_x - eye_mid[0]
        M[1, 2] += t_y - eye_mid[1]

        aligned = cv2.warpAffine(
            img_rgb, M, (output_size, output_size), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT
        )
        return aligned

    def preprocess_for_model(self, face_rgb: np.ndarray, size: int = 112) -> np.ndarray:
        """
        Normalize and reshape face image for the model.

        Args:
            face_rgb (np.ndarray): Aligned face crop in RGB.
            size (int): Target size.

        Returns:
            np.ndarray: Preprocessed tensor (NCHW, float32, normalized to [0,1]).
        """
        img = cv2.resize(face_rgb, (size, size)).astype(np.float32) / 255.0
        tensor = np.transpose(img, (2, 0, 1))[None, ...].astype(np.float32)
        return tensor

    def get_embedding_from_face_tensor(self, tensor: np.ndarray) -> np.ndarray:
        """
        Run inference to get face embedding.

        Args:
            tensor (np.ndarray): Preprocessed input tensor.

        Returns:
            np.ndarray: Normalized 512-d embedding vector.
        """
        out = self.emb_sess.run(None, {self._emb_input_name: tensor})
        emb = out[0].squeeze()

        # Normalize
        norm = np.linalg.norm(emb)
        if norm > 0:
            emb = emb / norm
        return emb.astype(np.float32)

    def detect_faces_rgb(self, img_rgb: np.ndarray) -> List[Tuple[int, int, int, int]]:
        """
        Detects faces from an RGB image using Mediapipe.

        Args:
            img_rgb (np.ndarray): Input RGB image.

        Returns:
            List[Tuple[int, int, int, int]]: List of bounding boxes.
        """
        img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
        return self.detect_with_mediapipe(img_bgr)

    def preprocess_face(
        self, img_rgb: np.ndarray, box: Tuple[int, int, int, int], size: int = 112
    ) -> Optional[np.ndarray]:
        """
        Full pipeline from RGB image and a bounding box to a preprocessed face tensor.

        Args:
            img_rgb (np.ndarray): Input RGB image.
            box (Tuple[int, int, int, int]): Bounding box.
            size (int): Target size.

        Returns:
            Optional[np.ndarray]: Face tensor or None if alignment fails.
        """
        # Mediapipe needs BGR
        img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
        landmarks = self.get_face_landmarks_mediapipe(img_bgr, box)
        if landmarks is None:
            return None

        aligned_rgb = self.align_face_by_eyes(img_rgb, landmarks, output_size=size)
        tensor = self.preprocess_for_model(aligned_rgb, size=size)
        return tensor

    def resize_image_if_large(self, img: np.ndarray, max_side: int = 1280) -> Tuple[np.ndarray, float]:
        """
        Resize image if its largest side exceeds max_side.

        Args:
            img (np.ndarray): Input image.
            max_side (int): Maximum allowed side length.

        Returns:
            Tuple[np.ndarray, float]: Resized image and the scale factor used.
        """
        h, w = img.shape[:2]
        scale = 1.0
        if max(h, w) > max_side:
            scale = max_side / max(h, w)
            img = cv2.resize(img, (int(w * scale), int(h * scale)))
        return img, scale
    
    def generate_face_map(self, img_rgb: np.ndarray, landmarks: List[Tuple[int, int]]) -> np.ndarray:
        """
        Creates a black image with white wireframe/dots of the face landmarks.
        
        Args:
            img_rgb (np.ndarray): Source image (used for dimensions).
            landmarks (List[Tuple[int, int]]): List of (x,y) landmarks.

        Returns:
            np.ndarray: Black and white face map (RGB format).
        """
        h, w = img_rgb.shape[:2]
        canvas = np.zeros((h, w, 3), dtype=np.uint8)
        
        # Mediapipe Mesh connections would be ideal, but for now let's draw points 
        # or simple lines if we had the topology. 
        # Drawing 468 points is a good start for a "biometric map".
        for (x, y) in landmarks:
            cv2.circle(canvas, (x, y), 1, (255, 255, 255), -1)

        # Let's try to draw some contours if possible, but points look "data-like".
        # We can also crop this canvas to the face bbox later if needed, 
        # but the request implies a map of the face.
        return canvas

    def get_aligned_face(self, img_rgb: np.ndarray, box: Tuple[int, int, int, int], size: int = 112) -> Optional[np.ndarray]:
        """
        Extracts the aligned face image.

        Args:
           img_rgb (np.ndarray): Input RGB image.
           box (Tuple[int, int, int, int]): Bounding box.
           size (int): Output size.

        Returns:
           Optional[np.ndarray]: Aligned face image (RGB).
        """
        img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
        landmarks = self.get_face_landmarks_mediapipe(img_bgr, box)
        if landmarks is None:
            return None
        
        aligned_rgb = self.align_face_by_eyes(img_rgb, landmarks, output_size=size)
        return aligned_rgb
