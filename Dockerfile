# OPHANIM - reproducible offline evaluation image.
# Python 3.11, CPU only, no network needed at run time, no GPU, no paid APIs.
#
#   docker build -t ophanim .
#   docker run --rm --network none --cpus 2 --memory 4g ophanim            # one-command verify
#   docker run --rm --network none ophanim evaluate --seed-base <hidden>   # closed evaluation
#   docker run --rm --network none ophanim demo --seed 7                   # scripted demo
#   docker run --rm --network none --entrypoint python ophanim judge_adapter.py --smoke   # jury adapter
FROM python:3.11.15-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock

COPY pyproject.toml README.md LICENSE judge_adapter.py ./
COPY src ./src
COPY tests ./tests
COPY configs ./configs
COPY data ./data
COPY docs ./docs
COPY examples ./examples
COPY docker ./docker

# Run as an unprivileged user; /app/runs is the only place the evaluator writes.
RUN useradd --create-home --uid 10001 ophanim && mkdir -p /app/runs && chown -R ophanim /app
USER ophanim

ENTRYPOINT ["python", "-m", "ophanim"]
CMD ["verify"]
