#!/usr/bin/env python3
"""
Module mira-vision — Détection d'objets via Raspberry Pi AI Camera (Sony IMX500).
Publie les détections sur MQTT : JSON sur mira/robots/<ROBOT_ID>/vision/text + texte brut sur mira/vision/output (rétrocompat).
Sert en option un flux MJPEG HTTP pour le dashboard (iframe streamUrl), avec boîtes et scores si STREAM_DRAW_DETECTIONS=1.
"""

import threading
import time
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

import cv2
import paho.mqtt.client as mqtt
from picamera2 import Picamera2
from picamera2.devices import IMX500
from picamera2.devices.imx500 import NetworkIntrinsics, postprocess_nanodet_detection


MQTT_BROKER       = os.getenv("MQTT_BROKER", "mira-mosquitto")
MQTT_PORT         = int(os.getenv("MQTT_PORT", "1883"))
ROBOT_ID          = os.getenv("ROBOT_ID", "mira-robot")
MQTT_TOPIC        = os.getenv("MQTT_TOPIC_VISION", "mira/vision/output")
# Topic par robot (JSON) — consommé par le dashboard / contexte LLM
MQTT_TOPIC_ROBOT  = os.getenv(
    "MQTT_TOPIC_VISION_ROBOT",
    f"mira/robots/{ROBOT_ID}/vision/text",
)
CONFIDENCE_THRESH = float(os.getenv("CONFIDENCE_THRESHOLD", "0.55"))
COOLDOWN_SECONDS  = int(os.getenv("COOLDOWN_SECONDS", "10"))
MODEL_PATH        = os.getenv("IMX500_MODEL",
                    "/usr/share/imx500-models/imx500_network_ssd_mobilenetv2_fpnlite_320x320_pp.rpk")

# Flux MJPEG pour le dashboard (RPI_STREAM_URL = http://<IP_PI>:<port>/stream)
STREAM_MJPEG_ENABLE = os.getenv("STREAM_MJPEG_ENABLE", "1").lower() in ("1", "true", "yes")
STREAM_MJPEG_PORT   = int(os.getenv("STREAM_MJPEG_PORT", "8080"))
STREAM_MJPEG_PATH   = os.getenv("STREAM_MJPEG_PATH", "/stream")
# Intervalle mini entre deux captures pour le flux (plus bas = plus fluide, plus de CPU)
STREAM_FRAME_MIN_S = float(os.getenv("STREAM_FRAME_MIN_INTERVAL_SEC", "0.04"))
STREAM_JPEG_QUALITY = int(os.getenv("STREAM_JPEG_QUALITY", "72"))
# Largeur max du flux (0 = taille caméra ; ex. 960 ou 720 pour alléger encodage + réseau)
STREAM_PREVIEW_MAX_WIDTH = int(os.getenv("STREAM_PREVIEW_MAX_WIDTH", "960"))
# Pause fin de boucle principale (impacte détection + MJPEG ; trop bas = CPU↑)
VISION_LOOP_SLEEP_SEC = float(os.getenv("VISION_LOOP_SLEEP_SEC", "0.05"))
# Boîtes + labels sur le flux MJPEG (même logique que la détection MQTT)
STREAM_DRAW_DETECTIONS = os.getenv("STREAM_DRAW_DETECTIONS", "1").lower() in (
    "1",
    "true",
    "yes",
)


C_RESET  = "\033[0m"
C_GREEN  = "\033[1;32m"
C_CYAN   = "\033[0;36m"
C_YELLOW = "\033[1;33m"
C_RED    = "\033[1;31m"


COCO_FR = {
    'person': 'une personne', 'bicycle': 'un vélo', 'car': 'une voiture',
    'motorcycle': 'une moto', 'airplane': 'un avion', 'bus': 'un bus',
    'train': 'un train', 'truck': 'un camion', 'boat': 'un bateau',
    'traffic light': 'un feu', 'fire hydrant': 'une borne incendie',
    'stop sign': 'un panneau stop', 'bench': 'un banc',
    'bird': 'un oiseau', 'cat': 'un chat', 'dog': 'un chien',
    'horse': 'un cheval', 'sheep': 'un mouton', 'cow': 'une vache',
    'elephant': 'un éléphant', 'bear': 'un ours', 'zebra': 'un zèbre',
    'giraffe': 'une girafe', 'backpack': 'un sac à dos',
    'umbrella': 'un parapluie', 'handbag': 'un sac à main',
    'suitcase': 'une valise', 'frisbee': 'un frisbee',
    'skis': 'des skis', 'snowboard': 'un snowboard',
    'sports ball': 'un ballon', 'kite': 'un cerf-volant',
    'bottle': 'une bouteille', 'wine glass': 'un verre',
    'cup': 'une tasse', 'fork': 'une fourchette',
    'knife': 'un couteau', 'spoon': 'une cuillère', 'bowl': 'un bol',
    'banana': 'une banane', 'apple': 'une pomme',
    'sandwich': 'un sandwich', 'orange': 'une orange',
    'pizza': 'une pizza', 'donut': 'un donut', 'cake': 'un gâteau',
    'chair': 'une chaise', 'couch': 'un canapé',
    'potted plant': 'une plante', 'bed': 'un lit',
    'dining table': 'une table', 'toilet': 'des toilettes',
    'tv': 'une télévision', 'laptop': 'un portable',
    'mouse': 'une souris', 'remote': 'une télécommande',
    'keyboard': 'un clavier', 'cell phone': 'un téléphone',
    'microwave': 'un micro-ondes', 'oven': 'un four',
    'toaster': 'un grille-pain', 'sink': 'un évier',
    'refrigerator': 'un frigo', 'book': 'un livre',
    'clock': 'une horloge', 'vase': 'un vase',
    'scissors': 'des ciseaux', 'teddy bear': 'un ours en peluche',
}


last_publish_time = 0.0
mqtt_client = None

_stream_jpeg: bytes | None = None
_stream_lock = threading.Lock()
_stream_frame_gen = 0
_stream_overlay_lock = threading.Lock()
# Liste de (x1, y1, x2, y2, cat_index, score) en coordonnées espace réseau (input_w × input_h)
_stream_overlay: list[tuple[float, float, float, float, int, float]] = []
_stream_overlay_input_size: tuple[int, int] = (0, 0)


def _encode_jpeg_bgr(bgr) -> bytes | None:
    q = max(40, min(95, STREAM_JPEG_QUALITY))
    ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), q])
    return buf.tobytes() if ok else None


def _maybe_downscale_bgr(bgr):
    if STREAM_PREVIEW_MAX_WIDTH <= 0:
        return bgr
    h, w = bgr.shape[:2]
    if w <= STREAM_PREVIEW_MAX_WIDTH:
        return bgr
    scale = STREAM_PREVIEW_MAX_WIDTH / float(w)
    nw = STREAM_PREVIEW_MAX_WIDTH
    nh = max(1, int(h * scale))
    return cv2.resize(bgr, (nw, nh), interpolation=cv2.INTER_AREA)


def _draw_detections_on_bgr(
    bgr,
    overlay: list[tuple[float, float, float, float, int, float]],
    labels: list,
    input_w: int,
    input_h: int,
) -> None:
    """Dessine les boîtes (espace input réseau) sur l’image BGR (taille caméra)."""
    if not overlay or input_w <= 0 or input_h <= 0:
        return
    fh, fw = bgr.shape[0], bgr.shape[1]
    sx = fw / float(input_w)
    sy = fh / float(input_h)
    thickness = max(1, min(4, fw // 320))
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.45 * (fw / 640.0)
    font_scale = max(0.35, min(0.9, font_scale))
    for x1, y1, x2, y2, cat_i, sc in overlay:
        px1 = int(round(x1 * sx))
        py1 = int(round(y1 * sy))
        px2 = int(round(x2 * sx))
        py2 = int(round(y2 * sy))
        px1, px2 = min(px1, px2), max(px1, px2)
        py1, py2 = min(py1, py2), max(py1, py2)
        px1 = max(0, min(fw - 1, px1))
        px2 = max(0, min(fw - 1, px2))
        py1 = max(0, min(fh - 1, py1))
        py2 = max(0, min(fh - 1, py2))
        cv2.rectangle(bgr, (px1, py1), (px2, py2), (0, 220, 0), thickness, cv2.LINE_AA)
        name_en = ""
        if 0 <= int(cat_i) < len(labels):
            name_en = str(labels[int(cat_i)]).strip() or "?"
        else:
            name_en = "?"
        name = COCO_FR.get(name_en, name_en)
        txt = f"{name} {sc:.2f}"
        (tw, th), baseline = cv2.getTextSize(txt, font, font_scale, 1)
        ty = max(py1 - 4, th + 4)
        cv2.rectangle(
            bgr,
            (px1, ty - th - 4),
            (px1 + tw + 4, ty + baseline),
            (0, 220, 0),
            -1,
        )
        cv2.putText(bgr, txt, (px1 + 2, ty - 2), font, font_scale, (0, 0, 0), 1, cv2.LINE_AA)


def update_mjpeg_frame(picam2: Picamera2, labels: list) -> None:
    """Met à jour le dernier JPEG servi sur /stream (appelé depuis la boucle principale)."""
    global _stream_jpeg, _stream_frame_gen
    try:
        arr = picam2.capture_array("main")
        if arr is None or arr.size == 0:
            return
        if arr.ndim == 2:
            bgr = cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
        elif arr.shape[2] == 4:
            bgr = cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR)
        else:
            bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        if STREAM_DRAW_DETECTIONS:
            with _stream_overlay_lock:
                snap = list(_stream_overlay)
                iw, ih = _stream_overlay_input_size
            if snap and iw > 0 and ih > 0:
                _draw_detections_on_bgr(bgr, snap, labels, iw, ih)
        bgr = _maybe_downscale_bgr(bgr)
        jpg = _encode_jpeg_bgr(bgr)
        if jpg:
            with _stream_lock:
                _stream_jpeg = jpg
                _stream_frame_gen += 1
    except Exception as e:
        print(f"{C_YELLOW}[STREAM] capture_array: {e}{C_RESET}")


def _start_mjpeg_server() -> None:
    path = STREAM_MJPEG_PATH.rstrip("/") or "/stream"
    boundary = b"frame"

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            req = self.path.split("?", 1)[0]
            if req in ("/", path):
                self.send_response(200)
                self.send_header(
                    "Content-Type",
                    "multipart/x-mixed-replace; boundary=" + boundary.decode("ascii"),
                )
                self.send_header("Cache-Control", "no-cache, no-store")
                self.send_header("Pragma", "no-cache")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                last_gen = -1
                try:
                    while True:
                        with _stream_lock:
                            jpg = _stream_jpeg
                            gen = _stream_frame_gen
                        if jpg and gen != last_gen:
                            self.wfile.write(
                                b"--" + boundary + b"\r\n"
                                b"Content-Type: image/jpeg\r\n\r\n" + jpg + b"\r\n"
                            )
                            last_gen = gen
                            time.sleep(0.001)
                        else:
                            time.sleep(0.004)
                except (BrokenPipeError, ConnectionResetError):
                    pass
            else:
                self.send_error(404)

        def log_message(self, fmt, *args):
            pass

    def run():
        srv = HTTPServer(("0.0.0.0", STREAM_MJPEG_PORT), Handler)
        print(
            f"{C_GREEN}[STREAM] MJPEG http://0.0.0.0:{STREAM_MJPEG_PORT}{path}{C_RESET}"
        )
        srv.serve_forever()

    t = threading.Thread(target=run, daemon=True)
    t.start()


def on_mqtt_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print(f"{C_GREEN}[MQTT] Connecté au broker {MQTT_BROKER}{C_RESET}")
    else:
        print(f"{C_RED}[MQTT] Échec connexion (code {rc}){C_RESET}")

def init_mqtt():
    global mqtt_client
    try:
        mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    except (AttributeError, TypeError):
        mqtt_client = mqtt.Client()

    mqtt_client.on_connect = on_mqtt_connect

    while True:
        try:
            print(f"{C_YELLOW}[MQTT] Connexion à {MQTT_BROKER}:{MQTT_PORT}...{C_RESET}")
            mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
            mqtt_client.loop_start()
            return
        except Exception as e:
            print(f"{C_RED}[MQTT] Erreur: {e} — retry dans 5s...{C_RESET}")
            time.sleep(5)


def detections_to_phrase(detections, labels):
    """Convertit les détections filtrées en phrase descriptive française."""
    detected = set()
    for det in detections:
        cat_index = int(det.category)
        if 0 <= cat_index < len(labels):
            label = labels[cat_index]
            if label and label != "-":
                detected.add(label)

    if not detected:
        return None

    fr = [COCO_FR.get(lbl, lbl) for lbl in detected]
    if len(fr) == 1:
        return f"Je vois {fr[0]}"
    last = fr.pop()
    return f"Je vois {', '.join(fr)} et {last}"



def main():
    global last_publish_time, _stream_overlay_input_size
    init_mqtt()
    print(f"{C_CYAN}[INIT] Chargement du modèle IMX500: {MODEL_PATH}{C_RESET}")
    imx500 = IMX500(MODEL_PATH)
    intrinsics = imx500.network_intrinsics or NetworkIntrinsics()
    intrinsics.task = "object detection"
    if intrinsics.labels is None:
        labels_path = os.getenv("LABELS_FILE", "/usr/share/imx500-models/coco_labels.txt")
        if os.path.exists(labels_path):
            with open(labels_path) as f:
                intrinsics.labels = f.read().splitlines()
        else:
            intrinsics.labels = list(COCO_FR.keys())
    intrinsics.update_with_defaults()

    labels = intrinsics.labels

    picam2 = Picamera2(imx500.camera_num)
    config = picam2.create_preview_configuration(
        controls={"FrameRate": intrinsics.inference_rate},
        buffer_count=12
    )

    print(f"{C_CYAN}[INIT] Démarrage de la caméra AI...{C_RESET}")
    imx500.show_network_fw_progress_bar()
    picam2.start(config, show_preview=False)

    if intrinsics.preserve_aspect_ratio:
        imx500.set_auto_aspect_ratio()

    print(f"{C_GREEN}[VISION] ✓ Caméra AI prête. Détection en cours...{C_RESET}")

    if STREAM_MJPEG_ENABLE:
        _start_mjpeg_server()

    last_detections = []
    last_stream_t = 0.0
    while True:
        try:
            metadata = picam2.capture_metadata()
            np_outputs = imx500.get_outputs(metadata, add_batch=True)
            input_w, input_h = imx500.get_input_size()

            overlay: list[tuple[float, float, float, float, int, float]] = []

            if np_outputs is not None:
                if intrinsics.postprocess == "nanodet":
                    boxes, scores, classes = postprocess_nanodet_detection(
                        outputs=np_outputs[0],
                        conf=CONFIDENCE_THRESH,
                        iou_thres=0.65,
                        max_out_dets=10
                    )[0]
                    from picamera2.devices.imx500.postprocess import scale_boxes
                    boxes = scale_boxes(boxes, 1, 1, input_h, input_w, False, False)
                else:
                    boxes   = np_outputs[0][0]
                    scores  = np_outputs[1][0]
                    classes = np_outputs[2][0]

                    if intrinsics.bbox_normalization:
                        boxes = boxes / input_h
                    if intrinsics.bbox_order == "xy":
                        boxes = boxes[:, [1, 0, 3, 2]]

                class Detection:
                    def __init__(self, cat, conf):
                        self.category = cat
                        self.conf = conf

                last_detections = []
                n = min(len(boxes), len(scores), len(classes))
                for i in range(n):
                    score = float(scores[i])
                    if score <= CONFIDENCE_THRESH:
                        continue
                    cat = int(classes[i])
                    row = boxes[i]
                    last_detections.append(Detection(cat, score))
                    overlay.append(
                        (
                            float(row[0]),
                            float(row[1]),
                            float(row[2]),
                            float(row[3]),
                            cat,
                            score,
                        )
                    )
            else:
                last_detections = []

            with _stream_overlay_lock:
                _stream_overlay[:] = overlay
                _stream_overlay_input_size = (int(input_w), int(input_h))

            # Cooldown + publication
            now = time.time()
            if STREAM_MJPEG_ENABLE and (now - last_stream_t) >= STREAM_FRAME_MIN_S:
                update_mjpeg_frame(picam2, labels)
                last_stream_t = now

            if last_detections and (now - last_publish_time) >= COOLDOWN_SECONDS:
                phrase = detections_to_phrase(last_detections, labels)
                if phrase:
                    print(f"{C_CYAN}[VISION] {phrase}{C_RESET}")
                    payload = json.dumps(
                        {
                            "text": phrase,
                            "ts": now,
                            "source": "imx500",
                        },
                        ensure_ascii=False,
                    )
                    mqtt_client.publish(MQTT_TOPIC_ROBOT, payload)
                    # Rétrocompatibilité (texte brut)
                    mqtt_client.publish(MQTT_TOPIC, phrase)
                    last_publish_time = now

            time.sleep(VISION_LOOP_SLEEP_SEC)

        except KeyboardInterrupt:
            print(f"\n{C_YELLOW}[VISION] Arrêt...{C_RESET}")
            break
        except Exception as e:
            print(f"{C_RED}[ERREUR] {e}{C_RESET}")
            time.sleep(1)

    picam2.stop()
    mqtt_client.loop_stop()
    mqtt_client.disconnect()
    print(f"{C_GREEN}[VISION] Arrêté proprement.{C_RESET}")

if __name__ == "__main__":
    main()
