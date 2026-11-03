FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/data

# Chromium renders the HTML page; the fonts it needs are embedded in the page itself.
RUN apt-get update \
 && apt-get install -y --no-install-recommends chromium fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --uid 1000 --create-home dash

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY fridgedash ./fridgedash

USER dash
EXPOSE 8090
CMD ["uvicorn", "fridgedash.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8090"]
