"""
camera.py — Threaded webcam capture + MediaPipe + dual-model prediction.
One background thread grabs frames; mode switching is atomic via a lock.
"""

import threading
import time
import logging
import cv2
import mediapipe as mp
import numpy as np
import base64

logger = logging.getLogger(__name__)

mp_hands = mp.solutions.hands
mp_draw  = mp.solutions.drawing_utils
mp_style = mp.solutions.drawing_styles

# Custom drawing specs for crisp, colourful landmarks
_LANDMARK_SPEC  = mp_draw.DrawingSpec(color=(0, 212, 170), thickness=2, circle_radius=3)
_CONNECTION_SPEC = mp_draw.DrawingSpec(color=(77, 158, 255), thickness=2)


class CameraStream:
    """
    Single background thread: reads frames → MediaPipe → predict → encode JPEG.
    The prediction mode (words / alpha) is toggled atomically — zero lag switch.
    """

    def __init__(self, camera_index: int = 0, dual_predictor=None):
        self.camera_index    = camera_index
        self.dual_predictor  = dual_predictor

        self.cap     = None
        self.running = False
        self._thread = None
        self._lock   = threading.Lock()

        self._mode           = "words"   # "words" | "alpha"
        self._last_frame_bytes = None
        self._last_prediction  = {
            "sign": None, "confidence": 0.0, "raw_confidence": 0.0,
            "all_probs": {}, "stable": False, "hand_count": 0,
            "fps": 0.0, "message": "Camera not started", "mode": "words"
        }
        self._fps        = 0.0
        self._frame_count = 0
        self._fps_time   = time.time()
        self._hands      = None

    # ── Public controls ───────────────────────────────────────────
    def start(self):
        if self.running:
            return {"ok": True, "message": "Already running"}

        self.cap = cv2.VideoCapture(self.camera_index)
        if not self.cap.isOpened():
            return {"ok": False, "message": "Could not open camera. Check permissions or try index 1."}

        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH,  1280)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT,  720)
        self.cap.set(cv2.CAP_PROP_FPS,            30)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE,      1)

        # model_complexity=0 = faster, still accurate enough for landmarks
        self._hands = mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=2,
            model_complexity=0,
            min_detection_confidence=0.65,
            min_tracking_confidence=0.55,
        )

        self.running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("Camera stream started.")
        return {"ok": True, "message": "Camera started"}

    def stop(self):
        self.running = False
        if self._thread:
            self._thread.join(timeout=3.0)
        if self.cap:
            self.cap.release()
            self.cap = None
        if self._hands:
            self._hands.close()
            self._hands = None
        with self._lock:
            self._last_frame_bytes = None
        logger.info("Camera stream stopped.")

    def set_mode(self, mode: str):
        """Switch detection mode instantly (called from Flask route)."""
        with self._lock:
            self._mode = mode
        if self.dual_predictor:
            self.dual_predictor.switch_mode(mode)

    def get_mode(self):
        with self._lock:
            return self._mode

    # ── Capture loop ──────────────────────────────────────────────
    def _loop(self):
        while self.running:
            if not self.cap or not self.cap.isOpened():
                logger.error("Camera disconnected.")
                self.running = False
                with self._lock:
                    self._last_prediction["message"] = "Camera disconnected"
                break

            ret, frame = self.cap.read()
            if not ret:
                time.sleep(0.005)
                continue

            frame = cv2.flip(frame, 1)

            # Reuse array: convert to RGB without extra alloc
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            rgb.flags.writeable = False
            try:
                results = self._hands.process(rgb)
            except Exception as e:
                logger.error(f"MediaPipe error: {e}")
                continue
            rgb.flags.writeable = True

            # ── Draw landmarks ────────────────────────────────────
            annotated = frame  # draw in-place for speed
            if results.multi_hand_landmarks:
                for idx, hand_lm in enumerate(results.multi_hand_landmarks):
                    # Use custom coloured specs
                    mp_draw.draw_landmarks(
                        annotated, hand_lm,
                        mp_hands.HAND_CONNECTIONS,
                        _LANDMARK_SPEC,
                        _CONNECTION_SPEC,
                    )
                    # Hand label badge
                    if results.multi_handedness:
                        wrist = hand_lm.landmark[0]
                        h, w  = annotated.shape[:2]
                        cx, cy = int(wrist.x * w), int(wrist.y * h)
                        label  = results.multi_handedness[idx].classification[0].label
                        color  = (0, 212, 170) if label == "Left" else (255, 150, 50)
                        cv2.circle(annotated, (cx, cy - 30), 16, color, -1)
                        cv2.putText(annotated, label[0], (cx - 5, cy - 24),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 2)

            # ── Predict ───────────────────────────────────────────
            with self._lock:
                mode = self._mode

            prediction = {"sign": None, "confidence": 0.0, "raw_confidence": 0.0,
                          "all_probs": {}, "stable": False, "hand_count": 0,
                          "message": "No model loaded", "mode": mode}

            if self.dual_predictor:
                try:
                    prediction = self.dual_predictor.predict(results, mode)
                    prediction["mode"] = mode
                except Exception as e:
                    logger.error(f"Predictor error: {e}")
                    prediction["message"] = str(e)

            # ── FPS ───────────────────────────────────────────────
            self._frame_count += 1
            now     = time.time()
            elapsed = now - self._fps_time
            if elapsed >= 1.0:
                self._fps        = self._frame_count / elapsed
                self._frame_count = 0
                self._fps_time   = now

            # ── Encode JPEG ───────────────────────────────────────
            _, jpeg = cv2.imencode('.jpg', annotated, [cv2.IMWRITE_JPEG_QUALITY, 78])

            with self._lock:
                self._last_frame_bytes = jpeg.tobytes()
                self._last_prediction  = prediction
                self._last_prediction["fps"] = round(self._fps, 1)

    # ── Accessors ─────────────────────────────────────────────────
    def get_frame(self):
        with self._lock:
            return self._last_frame_bytes

    def get_prediction(self):
        with self._lock:
            return dict(self._last_prediction)

    def get_snapshot(self):
        with self._lock:
            if self._last_frame_bytes:
                return base64.b64encode(self._last_frame_bytes).decode("utf-8")
        return None

    def is_running(self):
        return self.running
