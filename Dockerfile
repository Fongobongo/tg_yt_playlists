# Use an official Python runtime as a parent image
FROM python:3.12-slim

# Install system dependencies: ffmpeg for yt-dlp, gcc and libpq-dev for building asyncpg if needed
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Run the bot
CMD ["python", "-m", "src.bot"]