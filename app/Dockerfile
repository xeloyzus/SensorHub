FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

# Install dependencies first for better layer caching.
COPY app/requirements.txt app/requirements.lock ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the FastAPI package into /app/app so uvicorn can run "app.main:app".
COPY app ./app
RUN useradd --uid 10001 --create-home appuser
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
