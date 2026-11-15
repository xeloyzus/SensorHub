FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

# Install dependencies first for better layer caching.
COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN useradd --uid 10001 --create-home appuser
USER appuser

CMD ["python", "main.py"]
