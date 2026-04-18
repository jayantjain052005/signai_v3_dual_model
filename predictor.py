"""
predictor.py — Dual-Model Inference Engine
  - sign_model_2hand.pkl  → Words/Phrases  (126 features, 2-hand pipeline)
  - sign_model_alpha.pkl  → Alphabet       (63 features, 1-hand pipeline)
"""

import numpy as np
import joblib
import os
from collections import Counter, deque
import logging

logger = logging.getLogger(__name__)

ALPHA_FEATURE_DIM = 63
WORDS_FEATURE_DIM = 126


class SignPredictor:
    SMOOTHING_WINDOW     = 8
    CONFIDENCE_THRESHOLD = 0.40

    def __init__(self, model_path: str, feature_dim: int = 126):
        self.model_path  = model_path
        self.feature_dim = feature_dim
        self.model         = None
        self.label_encoder = None
        self.classes       = []
        self._pred_buf  = deque(maxlen=self.SMOOTHING_WINDOW)
        self._conf_buf  = deque(maxlen=self.SMOOTHING_WINDOW)
        self._load()

    def _load(self):
        if not os.path.exists(self.model_path):
            raise FileNotFoundError(f"Model not found: '{self.model_path}'")
        bundle = joblib.load(self.model_path)
        if not isinstance(bundle, dict):
            raise ValueError("Model bundle must be a dict.")
        for key in ("model", "label_encoder"):
            if key not in bundle:
                raise KeyError(f"Bundle missing key: '{key}'")
        self.model         = bundle["model"]
        self.label_encoder = bundle["label_encoder"]
        self.feature_dim   = bundle.get("feature_dim", self.feature_dim)
        self.classes       = list(self.label_encoder.classes_)
        if not hasattr(self.model, "predict_proba"):
            raise AttributeError("Model must support predict_proba.")
        logger.info(f"Loaded '{self.model_path}' | dim={self.feature_dim} | classes={self.classes}")

    @staticmethod
    def _hand_features(hand_landmarks) -> np.ndarray:
        lm    = hand_landmarks.landmark
        wrist = lm[0]
        pts   = np.array([[p.x - wrist.x, p.y - wrist.y, p.z - wrist.z] for p in lm])
        scale = np.max(np.linalg.norm(pts, axis=1))
        if scale > 0:
            pts /= scale
        return pts.flatten()

    def build_vector(self, results) -> np.ndarray:
        if self.feature_dim == ALPHA_FEATURE_DIM:
            return self._build_1hand(results)
        return self._build_2hand(results)

    def _build_1hand(self, results) -> np.ndarray:
        vec = np.zeros(63)
        if results.multi_hand_landmarks:
            vec = self._hand_features(results.multi_hand_landmarks[0])
        return vec.reshape(1, -1)

    def _build_2hand(self, results) -> np.ndarray:
        left  = np.zeros(63)
        right = np.zeros(63)
        if results.multi_hand_landmarks:
            for i, hl in enumerate(results.multi_hand_landmarks):
                feats = self._hand_features(hl)
                label = results.multi_handedness[i].classification[0].label
                if label == "Left":
                    right = feats
                else:
                    left  = feats
        return np.concatenate([left, right]).reshape(1, -1)

    def predict(self, results) -> dict:
        hand_count = len(results.multi_hand_landmarks) if results.multi_hand_landmarks else 0
        if hand_count == 0:
            self._pred_buf.clear()
            self._conf_buf.clear()
            return self._empty(0, "No hands detected")

        features = self.build_vector(results)
        if not np.any(features):
            msg = "Show both hands" if self.feature_dim == WORDS_FEATURE_DIM else "Show your hand"
            return self._empty(hand_count, msg)

        try:
            pred_idx = self.model.predict(features)[0]
            probas   = self.model.predict_proba(features)[0]
        except Exception as e:
            logger.error(f"Prediction error: {e}")
            return self._empty(hand_count, f"Error: {e}")

        raw_conf  = float(probas[pred_idx])
        all_probs = {self.label_encoder.classes_[i]: float(p) for i, p in enumerate(probas)}

        self._pred_buf.append(pred_idx)
        self._conf_buf.append(raw_conf)

        smooth_idx  = Counter(self._pred_buf).most_common(1)[0][0]
        smooth_conf = float(np.mean(self._conf_buf))
        sign        = self.label_encoder.inverse_transform([smooth_idx])[0]
        stable      = (raw_conf >= self.CONFIDENCE_THRESHOLD
                       and len(self._pred_buf) >= max(2, self.SMOOTHING_WINDOW // 2))

        msg = sign if stable else "Detecting…"
        if self.feature_dim == WORDS_FEATURE_DIM and hand_count == 1:
            msg = "Show both hands for best accuracy"

        return {
            "sign":           sign,
            "confidence":     smooth_conf,
            "raw_confidence": raw_conf,
            "all_probs":      all_probs,
            "stable":         stable,
            "hand_count":     hand_count,
            "message":        msg,
        }

    def reset_buffer(self):
        self._pred_buf.clear()
        self._conf_buf.clear()

    @staticmethod
    def _empty(hand_count, msg):
        return {"sign": None, "confidence": 0.0, "raw_confidence": 0.0,
                "all_probs": {}, "stable": False, "hand_count": hand_count, "message": msg}


class DualPredictor:
    MODE_WORDS = "words"
    MODE_ALPHA = "alpha"

    def __init__(self):
        self.words_pred  = None
        self.alpha_pred  = None
        self.words_error = None
        self.alpha_error = None
        self._load_all()

    def _load_all(self):
        for attr, path, dim, err_attr in [
            ("words_pred", "sign_model_2hand.pkl", WORDS_FEATURE_DIM, "words_error"),
            ("alpha_pred", "sign_model_alpha.pkl", ALPHA_FEATURE_DIM, "alpha_error"),
        ]:
            try:
                setattr(self, attr, SignPredictor(path, dim))
            except FileNotFoundError as e:
                setattr(self, err_attr, str(e))
                logger.warning(str(e))
            except Exception as e:
                setattr(self, err_attr, f"Load error: {e}")
                logger.error(f"Load error ({path}): {e}")

    def predict(self, results, mode: str) -> dict:
        predictor = self.alpha_pred if mode == self.MODE_ALPHA else self.words_pred
        if predictor is None:
            err = self.alpha_error if mode == self.MODE_ALPHA else self.words_error
            return SignPredictor._empty(0, f"Model not loaded: {err}")
        result = predictor.predict(results)
        result["mode"] = mode
        return result

    def switch_mode(self, new_mode: str):
        if new_mode == self.MODE_ALPHA and self.alpha_pred:
            self.alpha_pred.reset_buffer()
        elif new_mode == self.MODE_WORDS and self.words_pred:
            self.words_pred.reset_buffer()

    @property
    def words_classes(self):
        return self.words_pred.classes if self.words_pred else []

    @property
    def alpha_classes(self):
        return self.alpha_pred.classes if self.alpha_pred else []

    @property
    def any_model_ready(self):
        return self.words_pred is not None or self.alpha_pred is not None
