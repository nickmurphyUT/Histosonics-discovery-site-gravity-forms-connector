# Use official Python image
FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY . .

# Expose Flask port
ENV PORT=8080

# Run with Gunicorn for production
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 app:app
