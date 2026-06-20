FROM python:3.11-slim

# Install cron and other system deps
RUN apt-get update && \
    apt-get install -y --no-install-recommends cron && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create data directory for volume mount
# Mount /data with: credentials.json, token.json (Gmail OAuth2), .env
RUN mkdir -p /data

# Set up cron job
ARG CRON_SCHEDULE="0 */6 * * *"
RUN echo "${CRON_SCHEDULE} cd /app && /usr/local/bin/python main.py >> /data/cron.log 2>&1" > /etc/cron.d/job-agent-cron && \
    chmod 0644 /etc/cron.d/job-agent-cron && \
    crontab /etc/cron.d/job-agent-cron

# Create entrypoint that runs cron in foreground + allows one-shot execution
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

VOLUME ["/data"]

ENV DATA_DIR=/data
ENV CONFIG_PATH=/app/config.yaml
ENV ENV_PATH=/data/.env

ENTRYPOINT ["/entrypoint.sh"]
CMD ["cron"]
