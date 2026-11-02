# WatchMate in a container: Python + ffmpeg. Secrets are passed at run time (--env-file .env), never baked in.
#
#   docker build -t watchmate .
#   docker run --rm -it --env-file .env -v "$PWD/data:/app/data" -v "$PWD/sources:/app/sources" \
#       -p 127.0.0.1:8000:8000 watchmate                         # Control Room + watcher -> http://localhost:8000
#   docker run --rm -it --env-file .env -v "$PWD/data:/app/data" watchmate python -m bot.run   # Telegram bot
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN useradd --create-home watchmate && mkdir -p data sources && chown -R watchmate /app
USER watchmate

ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["python", "-m", "control.server", "--host", "0.0.0.0"]
