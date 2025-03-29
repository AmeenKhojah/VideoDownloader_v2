# Use an official Python runtime as a parent image
FROM python:3.10-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1 # Prevents python creating .pyc files
ENV PYTHONUNBUFFERED 1      # Prevents python buffering stdout/stderr

# Install system dependencies including ffmpeg
# Use apt-get for Debian-based images like python:slim
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
# Consider using --no-cache-dir for slightly smaller image size
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code into the container
COPY . .

# Define the command to run the application using Gunicorn
# Use the "shell" form so $PORT gets expanded by the shell
# *** THIS IS THE CORRECTED LINE ***
CMD gunicorn app:app --bind 0.0.0.0:$PORT --preload --timeout 180 --workers 3
