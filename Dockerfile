# Use a lightweight Python base image
FROM python:3.11-slim

# Set the working directory
WORKDIR /app

# Copy the backend requirements and install them
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire backend and frontend directories
COPY backend/ backend/
COPY frontend/ frontend/

# Directory where the SQLite database will live (mounted as a volume)
RUN mkdir -p /app/data

# Expose our highly obscure port
EXPOSE 54321

# Start the application using Uvicorn on port 54321
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "54321"]
