FROM python:3.10-slim

WORKDIR /app

# Dépendances système : mpg123 (lecteur MP3) + alsa (sortie audio)
RUN apt-get update && apt-get install -y \
    mpg123 \
    alsa-utils \
    pulseaudio-utils \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY tts.py .

ENV MQTT_BROKER=mira-mosquitto
ENV MQTT_PORT=1883
ENV MQTT_TOPIC=mira/tts/say
ENV TTS_LANG=fr
ENV TTS_SLOW=false

CMD ["python", "-u", "tts.py"]
