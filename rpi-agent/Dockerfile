FROM python:3.12-slim-bookworm

# docker inspect (état des conteneurs sur la Pi)
RUN apt-get update \
  && apt-get install -y --no-install-recommends docker.io \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY agent.py .
CMD ["python", "-u", "agent.py"]
