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

# Build the application
RUN make clean && make

# Run the application
# Note: Audio device must be passed to container at runtime
CMD ["./stt_app"]
