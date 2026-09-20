# syntax=docker/dockerfile:1
FROM python:3.13-slim

# Run as an unprivileged user. A compromised process should not be root, and the
# container never needs to write outside its own data directory.
RUN groupadd --gid 10001 verity \
 && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin verity

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first for layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Build the ground-truth store into the image: CPSC recalls plus openFDA food,
# drug and device enforcement records.
#
# Overridable so CI can build hermetically from the test fixture instead of
# hitting the live feeds:
#   docker build --build-arg VERITY_BUILD_ARGS="--cache tests/fixtures/recalls.json --max-recalls 50 --fda-limit 0" .
#
# `|| true` keeps the image buildable if an upstream feed is briefly
# unavailable; the service still starts and serves whatever was baked in.
ARG VERITY_BUILD_ARGS="--max-recalls 5000 --fda-limit 3000"
RUN python -m verity build ${VERITY_BUILD_ARGS} || true

# Hand ownership to the unprivileged user, then drop privileges.
RUN chown -R verity:verity /app
USER verity

EXPOSE 8000

# No shell, exec form so the process is PID 1 and receives signals directly.
CMD ["python", "-m", "verity", "serve", "--host", "0.0.0.0", "--port", "8000"]
