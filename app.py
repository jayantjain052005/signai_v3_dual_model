"""
app.py — Sign Language AI Detector (Dual-Model Edition)
  Words mode  → sign_model_2hand.pkl
  Alphabet mode → sign_model_alpha.pkl
Run: python app.py
"""

import os
import time
import glob
import logging
from flask import Flask, render_template, Response, jsonify, request, send_file

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config["SECRET_KEY"] = "signai-dual-2024"

# ── Boot ──────────────────────────────────────────────────────────
from predictor import DualPredictor
from camera    import CameraStream

dual = DualPredictor()
camera = CameraStream(camera_index=0, dual_predictor=dual)

# ── Routes ────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template(
        "index.html",
        words_classes=dual.words_classes,
        alpha_classes=dual.alpha_classes,
        words_error=dual.words_error,
        alpha_error=dual.alpha_error,
    )


@app.route("/api/camera/start", methods=["POST"])
def camera_start():
    return jsonify(camera.start())


@app.route("/api/camera/stop", methods=["POST"])
def camera_stop():
    camera.stop()
    return jsonify({"ok": True})


@app.route("/api/camera/status")
def camera_status():
    return jsonify({
        "running":      camera.is_running(),
        "mode":         camera.get_mode(),
        "words_ready":  dual.words_pred is not None,
        "alpha_ready":  dual.alpha_pred is not None,
        "words_error":  dual.words_error,
        "alpha_error":  dual.alpha_error,
        "words_classes": dual.words_classes,
        "alpha_classes": dual.alpha_classes,
    })


@app.route("/api/mode/<mode>", methods=["POST"])
def set_mode(mode):
    if mode not in ("words", "alpha"):
        return jsonify({"ok": False, "message": "Unknown mode"}), 400
    camera.set_mode(mode)
    return jsonify({"ok": True, "mode": mode})


@app.route("/video_feed")
def video_feed():
    def generate():
        while True:
            if camera.is_running():
                frame = camera.get_frame()
                if frame:
                    yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n")
            time.sleep(0.030)
    return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/api/prediction")
def get_prediction():
    if not camera.is_running():
        return jsonify({"sign": None, "confidence": 0.0, "raw_confidence": 0.0,
                        "all_probs": {}, "stable": False, "hand_count": 0,
                        "fps": 0.0, "message": "Camera not running", "mode": camera.get_mode()})
    return jsonify(camera.get_prediction())


@app.route("/api/snapshot")
def snapshot():
    data = camera.get_snapshot()
    if data:
        return jsonify({"ok": True, "image": data})
    return jsonify({"ok": False, "message": "No frame available"}), 400


# ── Sign image serving ────────────────────────────────────────────
DATASETS = {
    "words": "dataset",
    "alpha": "dataset_alpha",
}

def _find_image(sign_name: str, mode: str) -> str | None:
    folder = os.path.join(DATASETS.get(mode, "dataset"), sign_name)
    if not os.path.isdir(folder):
        # Try other dataset as fallback
        for ds in DATASETS.values():
            folder = os.path.join(ds, sign_name)
            if os.path.isdir(folder):
                break
        else:
            return None
    imgs = []
    for ext in ("*.jpg", "*.jpeg", "*.png"):
        imgs.extend(glob.glob(os.path.join(folder, ext)))
    if not imgs:
        return None
    imgs.sort()
    return imgs[len(imgs) // 2]


@app.route("/api/sign_image/<mode>/<path:sign_name>")
def sign_image(mode, sign_name):
    path = _find_image(sign_name, mode)
    if path and os.path.exists(path):
        return send_file(path, mimetype="image/jpeg")
    # Coloured SVG placeholder
    colors = ["#00d4aa","#4d9eff","#a78bfa","#f472b6","#fb923c","#34d399","#60a5fa","#f87171"]
    color  = colors[abs(hash(sign_name)) % len(colors)]
    letter = sign_name[0].upper()
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="200" height="150" viewBox="0 0 200 150">'
           f'<rect width="200" height="150" fill="#161a22"/>'
           f'<circle cx="100" cy="62" r="44" fill="{color}" opacity="0.12"/>'
           f'<text x="100" y="76" font-family="Arial" font-size="44" font-weight="bold"'
           f' fill="{color}" text-anchor="middle">{letter}</text>'
           f'<text x="100" y="115" font-family="Arial" font-size="11" fill="#8b95a8"'
           f' text-anchor="middle">{sign_name}</text></svg>')
    from flask import Response as FR
    return FR(svg, mimetype="image/svg+xml")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"\n{'='*58}")
    print("  🤟  Sign Language AI Detector  —  Dual Model Edition")
    print(f"  ▶   http://localhost:{port}")
    print(f"  Words model  : {'✅ Ready' if dual.words_pred else '❌ ' + str(dual.words_error)}")
    print(f"  Alpha model  : {'✅ Ready' if dual.alpha_pred else '❌ ' + str(dual.alpha_error)}")
    print(f"{'='*58}\n")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
