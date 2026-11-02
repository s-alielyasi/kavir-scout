FROM mcr.microsoft.com/playwright/python:v1.64.1-noble

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HEADLESS=true \
    BROWSER_CHANNEL="" \
    USER_DATA_DIR=/app/data/telegram_profile

WORKDIR /app

# Keep the package version aligned with the browsers in the base image.
COPY requirements.txt requirements-tested.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt -c requirements-tested.txt \
    && install -d -o pwuser -g pwuser -m 0700 /app/data /app/logs

COPY --chown=pwuser:pwuser config.py main.py ./
COPY --chown=pwuser:pwuser kavirtire/ ./kavirtire/
COPY --chown=pwuser:pwuser telegram_bot/ ./telegram_bot/

USER pwuser

ENTRYPOINT ["python", "-m", "telegram_bot"]
