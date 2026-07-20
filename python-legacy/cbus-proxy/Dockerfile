# C-Bus Protocol Analyzer Proxy
FROM python:3.10-slim

# Install required packages
RUN apt-get update && apt-get install -y \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements from parent directory
COPY ../requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install colorama for colored output
RUN pip install --no-cache-dir colorama

# Copy the cbus library from parent directory
COPY ../cbus/ ./cbus/
COPY ../setup.py .
COPY ../setup.cfg .

# Install the package
RUN pip install -e .

# Copy the proxy module
COPY . ./cbus-proxy/

# Expose default proxy port
EXPOSE 10001

# Set environment variables for better Python output
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Default command
ENTRYPOINT ["python", "-m", "cbus-proxy.proxy"] 