FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 SAJADAI_DATA_DIR=/data
WORKDIR /app
# ffmpeg: frames and audio for the pre-publish reel critique
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# data (database, encryption key, each user's numbers) lives in the mounted volume
VOLUME /data
EXPOSE 8000
CMD ["python", "-m", "sajadai", "serve", "--host", "0.0.0.0", "--port", "8000"]
