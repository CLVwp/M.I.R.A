# Base image: Python 3.10-slim
FROM python:3.10-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Working directory
WORKDIR /app

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Expose port 5000
EXPOSE 5000

# Command to run the application
# We use uvicorn to host the FastAPI app
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5000"]

# Note for running this image to access serial ports:
# Run with device mounting: docker run --device=/dev/ttyUSB0:/dev/ttyUSB0 -p 5000:5000 mira-orchestrator
