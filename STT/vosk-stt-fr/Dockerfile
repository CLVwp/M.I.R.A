# Use a lightweight Debian image
FROM debian:bookworm-slim

# Install dependencies
# - build-essential: for gcc, make
# - curl: for llm_client
# - libportaudio2, alsa-utils: for audio
# - libatomic1: sometimes needed for atomic operations on some archs
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    portaudio19-dev \
    alsa-utils \
    libatomic1 \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy source code
COPY . .

# Copy aarch64 library before building
RUN cp vosk-linux-aarch64-0.3.45/vosk-linux-aarch64-0.3.45/libvosk.so vosk-api/src/libvosk.so && \
    cp vosk-linux-aarch64-0.3.45/vosk-linux-aarch64-0.3.45/vosk_api.h vosk-api/src/vosk_api.h

# Build the application
RUN make clean && make

# Run the application
# Note: Audio device must be passed to container at runtime
CMD ["./stt_app"]
