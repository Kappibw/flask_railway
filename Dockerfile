# Use official Python image
FROM python:3.10

# Install FFmpeg
RUN apt-get update && apt-get install -y ffmpeg

# Set the working directory to the project's root
WORKDIR /flask_railway

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy everything else into the container
COPY . .

# Expose Flask's default port
EXPOSE 5000

# Run the application
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:8080", "--log-level=debug", "--access-logfile=-", "--error-logfile=-", "main:app"]


