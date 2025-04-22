FROM python:3.11.9-alpine3.19

# Set working directory
WORKDIR /app

# Copy simulator code and configs
COPY . /app/

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Make the script executable
RUN chmod +x /app/run_simulator.py

# Expose the simulator port
EXPOSE 10001

# Set environment variable for verbose logging
ENV VERBOSE="true"
ENV LOG_LEVEL="DEBUG"
ENV PYTHONUNBUFFERED=1

# Start the simulator with verbose flag
CMD ["python", "/app/run_simulator.py", "--verbose"] 