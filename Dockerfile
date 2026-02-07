# Python 3.11 full image (to avoid DNS/SSL issues in slim)
FROM python:3.11

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    ca-certificates \
    dnsutils \
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
