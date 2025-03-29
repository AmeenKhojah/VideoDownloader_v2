# Use an official Python runtime as a parent image
FROM python:3.10-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1 # Prevents python creating .pyc files
ENV PYTHONUNBUFFERED 1      # Prevents python buffering stdout/stderr

# Install system dependencies including ffmpeg
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code into the container
COPY . .

# Define the command to run the application using Gunicorn
# Simpler CMD - Remove --bind, let Gunicorn try to detect $PORT
# *** ALTERNATIVE CMD - TRY IF PREVIOUS STEPS FAILED ***
CMD gunicorn app:app --preload --timeout 180 --workers 3
