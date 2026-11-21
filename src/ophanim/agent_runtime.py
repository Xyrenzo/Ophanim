"""Agent-side process for closed evaluation (runs in a SEPARATE process).

The evaluator starts this program as a child process and talks to it with JSON
lines over stdin/stdout:

    evaluator -> agent   {"type": "reset", "observation": {...}, "info": {...}}
    agent -> evaluator   {"action": {...}}
    evaluator -> agent   {"type": "step", "observation": {...}, "reward": 0.0,
                          "terminated": false, "truncated": false, "info": {}}
    ...
    evaluator -> agent   {"type": "end"}

The agent process never receives truth, provenance, seeds or the evaluation
secret, and it holds no reference to the environment object. Any program that
speaks this protocol can be evaluated (``--agent-cmd`` in the evaluation runner),
so the organisers can plug in their own policies.

Usage: python -m ophanim.agent_runtime --policy random_explorer --policy-seed 0
"""

from __future__ import annotations

import argparse
import json
import sys


def serve(policy, stdin=None, stdout=None) -> int:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        msg = json.loads(line)
        kind = msg.get("type")
        if kind == "end":
            return 0
        if kind == "reset":
            policy.reset(msg["observation"], msg["info"])
            action = policy.act(msg["observation"])
        elif kind == "step":
            if msg["terminated"] or msg["truncated"]:
                continue
            action = policy.act(msg["observation"])
        else:
            continue
        stdout.write(json.dumps({"action": action}) + "\n")
        stdout.flush()
    return 0


def main(argv: list[str] | None = None) -> int:
    from ophanim.policies import make_policy  # agent-side code only

    parser = argparse.ArgumentParser(description="OPHANIM agent-side runtime")
    parser.add_argument("--policy", required=True)
    parser.add_argument("--policy-seed", type=int, default=0)
    args = parser.parse_args(argv)
    return serve(make_policy(args.policy, args.policy_seed))


if __name__ == "__main__":
    sys.exit(main())
