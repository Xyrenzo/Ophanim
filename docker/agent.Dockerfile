# Image for running an OPHANIM policy as an untrusted agent in its own container.
#
#   docker build -f docker/agent.Dockerfile -t ophanim-agent:local .
#   python -m ophanim run-agent --container ophanim-agent:local --policy reference_auditor --seed 7
#
# It holds the agent-side code only (the JSON-lines runtime, the policies and the stdlib auditor they use):
# no data/, no configs/, no tests, no generator or evaluator code, no evaluator outputs. The evaluator starts
# it with process_runner.container_agent_command(): no network, read-only root filesystem, no capabilities,
# no privilege escalation, user 65534, private IPC, PID/memory/CPU limits and no mounts.
# Policies need nothing beyond the Python standard library, so nothing is installed.
FROM python:3.11.15-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=0 \
    PYTHONPATH=/agent/src

WORKDIR /agent
COPY src/ophanim/__init__.py src/ophanim/version.py src/ophanim/rng.py src/ophanim/agent_runtime.py ./src/ophanim/
COPY src/ophanim/policies ./src/ophanim/policies
COPY src/ophanim/audit ./src/ophanim/audit

USER 65534:65534
ENTRYPOINT ["python", "-m", "ophanim.agent_runtime"]
CMD ["--policy", "reference_auditor"]
