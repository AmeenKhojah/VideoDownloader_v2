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

# *** TEMPORARY DEBUGGING CMD ***
# Explicitly use shell to print the PORT variable and all env vars
# Then sleep so we can see the logs before the container potentially exits
CMD ["/bin/sh", "-c", "echo \"DEBUG: Checking PORT variable. Value is: [$PORT]\" && echo \"DEBUG: Listing environment variables:\" && env && echo \"DEBUG: Sleeping for 60 seconds...\" && sleep 60 && echo \"DEBUG: Exiting after sleep.\""]
