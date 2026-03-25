FROM python:3.12-slim

WORKDIR /app

# Install dependencies first for better layer caching
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy the rest of the application code
COPY . /app

ENV PYTHONUNBUFFERED=1

# Runs the long-lived Telegram bot (polling) inside the container.
CMD ["python", "main.py"]

