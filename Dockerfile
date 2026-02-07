# Python 3.11 slim image
FROM python:3.11-slim

# Install system dependencies (ffmpeg required for yt-dlp)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first (for caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create directory for data (optional specific volume mounting)
RUN mkdir -p /data

# Run the bot
CMD ["python", "bot.py"]
