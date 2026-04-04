#!/usr/bin/env python3
"""
Module mira-vision — Détection d'objets via Raspberry Pi AI Camera (Sony IMX500).
Publie les détections sur MQTT (mira/vision/output) avec un cooldown.
Sert en option un flux MJPEG HTTP pour le dashboard (iframe streamUrl).
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
MQTT_TOPIC        = os.getenv("MQTT_TOPIC_VISION", "mira/vision/output")
CONFIDENCE_THRESH = float(os.getenv("CONFIDENCE_THRESHOLD", "0.55"))
COOLDOWN_SECONDS  = int(os.getenv("COOLDOWN_SECONDS", "10"))
MODEL_PATH        = os.getenv("IMX500_MODEL",
                    "/usr/share/imx500-models/imx500_network_ssd_mobilenetv2_fpnlite_320x320_pp.rpk")

# Flux MJPEG pour le dashboard (RPI_STREAM_URL = http://<IP_PI>:<port>/stream)
STREAM_MJPEG_ENABLE = os.getenv("STREAM_MJPEG_ENABLE", "1").lower() in ("1", "true", "yes")
STREAM_MJPEG_PORT   = int(os.getenv("STREAM_MJPEG_PORT", "8080"))
STREAM_MJPEG_PATH   = os.getenv("STREAM_MJPEG_PATH", "/stream")
STREAM_FRAME_MIN_S  = float(os.getenv("STREAM_FRAME_MIN_INTERVAL_SEC", "0.15"))  # ~6–7 fps max capture


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


def _encode_jpeg_bgr(bgr) -> bytes | None:
    ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
    return buf.tobytes() if ok else None


def update_mjpeg_frame(picam2: Picamera2) -> None:
    """Met à jour le dernier JPEG servi sur /stream (appelé depuis la boucle principale)."""
    global _stream_jpeg
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
        jpg = _encode_jpeg_bgr(bgr)
        if jpg:
            with _stream_lock:
                _stream_jpeg = jpg
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
                try:
                    while True:
                        with _stream_lock:
                            jpg = _stream_jpeg
                        if jpg:
                            self.wfile.write(
                                b"--" + boundary + b"\r\n"
                                b"Content-Type: image/jpeg\r\n\r\n" + jpg + b"\r\n"
                            )
                        time.sleep(0.04)
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
    global last_publish_time
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

                # Créer liste de détections filtrées
                class Detection:
                    def __init__(self, cat, conf):
                        self.category = cat
                        self.conf = conf

                last_detections = [
                    Detection(cat, score)
                    for _, score, cat in zip(boxes, scores, classes)
                    if score > CONFIDENCE_THRESH
                ]

            # Cooldown + publication
            now = time.time()
            if STREAM_MJPEG_ENABLE and (now - last_stream_t) >= STREAM_FRAME_MIN_S:
                update_mjpeg_frame(picam2)
                last_stream_t = now

            if last_detections and (now - last_publish_time) >= COOLDOWN_SECONDS:
                phrase = detections_to_phrase(last_detections, labels)
                if phrase:
                    print(f"{C_CYAN}[VISION] {phrase}{C_RESET}")
                    mqtt_client.publish(MQTT_TOPIC, phrase)
                    last_publish_time = now

            time.sleep(0.1)

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
