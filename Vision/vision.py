import sys
import os
import json
import paho.mqtt.client as mqtt
from ultralytics import YOLO
from huggingface_hub import hf_hub_download
import cv2

os.environ["TF_USE_LEGACY_KERAS"] = "1"
try:
    import tensorflow as tf
    import tf_keras
    sys.modules['keras'] = tf_keras
    sys.modules['tensorflow.keras'] = tf_keras
except ImportError:
    pass

REPO_ID = "Subh775/Threat-Detection-YOLOv8n"
FILENAME = "weights/best.pt"
DANGEROUS_LABELS = ["knife", "handgun", "pistol", "razor", "shuriken", "weapon"]

model_path = hf_hub_download(repo_id=REPO_ID, filename=FILENAME)

class MiraRobot:
    def __init__(self):
        self.model = YOLO(model_path)
        self.mqtt_client = mqtt.Client()
        try:
            self.mqtt_client.connect("localhost", 1883, 60)
            self.mqtt_connected = True
        except:
            self.mqtt_connected = False

    def run(self):
        cap = cv2.VideoCapture(0)
        while True:
            ret, frame = cap.read()
            if not ret: break
            
            results = self.model(frame, conf=0.4, verbose=False)[0]
            annotated_frame = frame.copy()
            threat_detected = False

            if results.boxes:
                for box in results.boxes:
                    cls = int(box.cls[0])
                    label = results.names[cls]
                    conf = float(box.conf[0])
                    
                    if label == "person" or any(t in label.lower() for t in DANGEROUS_LABELS):
                        x1, y1, x2, y2 = map(int, box.xyxy[0])
                        
                        if label != "person":
                            threat_detected = True
                            color = (0, 0, 255)
                            display_text = f"ALERT: {label.upper()}"
                            if self.mqtt_connected:
                                self.mqtt_client.publish("mira/vision/detections", 
                                                        json.dumps({"status": "CRITICAL", "item": label, "conf": conf}))
                        else:
                            color = (0, 255, 0)
                            display_text = "HUMAN"

                        cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), color, 2)
                        cv2.putText(annotated_frame, display_text, (x1, y1 - 10), 
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

            overlay = annotated_frame.copy()
            header_color = (0, 0, 50) if not threat_detected else (0, 0, 100) 
            cv2.rectangle(overlay, (0, 0), (frame.shape[1], 80), header_color, -1)
            annotated_frame = cv2.addWeighted(overlay, 0.6, annotated_frame, 0.4, 0)
            
            status_text = "SYSTEM SECURE" if not threat_detected else "THREAT DETECTED"
            status_color = (0, 255, 0) if not threat_detected else (0, 0, 255)
            cv2.putText(annotated_frame, f"MIRA STATUS: {status_text}", (20, 45), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, status_color, 2)
            
            cv2.imshow("MIRA - SECURITY FEED", annotated_frame)
            if cv2.waitKey(1) & 0xFF == ord('q'): break
            
        cap.release()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    MiraRobot().run()