# Use an official Python runtime as a parent image
FROM python:3.10-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Install system dependencies including ffmpeg
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Set the working directory
WORKDIR /app

# Copy requirements first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Define the command to run the application using Gunicorn
# Use JSON form but explicitly call /bin/sh -c to ensure shell expansion of $PORT
# *** THIS IS THE CORRECTED LINE ***
CMD ["/bin/sh", "-c", "gunicorn app:app --bind 0.0.0.0:$PORT --preload --timeout 180 --workers 3"]
