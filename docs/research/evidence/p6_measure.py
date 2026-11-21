"""P6 read-only measurements on the real environment. Does not modify the repository."""
import json
import math
import statistics
from collections import Counter

from ophanim.env import OphanimEnv
from ophanim.evaluator.evaluation import DEFAULT_SEED_BASE, derive_seed, load_suite
from ophanim.evaluator.runner import run_episode
from ophanim.generator import generate_episode
from ophanim.policies import ReferenceAuditor

out = {}

# A. Full-scan cost (pages of 50) and pointer-vocabulary size, by size class
for size in ("small", "medium", "large"):
    pages, ids, fx_share, rows = [], [], [], []
    for seed in range(60):
        ep = generate_episode(seed, {"size": size})
        c = ep.public.manifest["record_counts"]
        p = {t: math.ceil(n / 50) for t, n in c.items()}
        pages.append(sum(p.values()))
        fx_share.append(p["fx"] / sum(p.values()))
        rows.append(c)
        n_ids = c["ledger"] + 2 * c["invoices"] + 2 * c["payments"] + c["fx"]  # row/doc/invoice/payment ids + fx keys
        ids.append(n_ids)
    out[f"scan_{size}"] = {
        "full_scan_pages_min_med_max": [min(pages), statistics.median(pages), max(pages)],
        "fx_pages_share_mean": round(statistics.mean(fx_share), 3),
        "ledger_rows_min_max": [min(r["ledger"] for r in rows), max(r["ledger"] for r in rows)],
        "fx_rows_min_max": [min(r["fx"] for r in rows), max(r["fx"] for r in rows)],
        "pointer_vocab_min_med_max": [min(ids), statistics.median(ids), max(ids)],
    }

# B. Observation sizes (bytes of JSON; ~4 bytes/token is a rough heuristic, not a measurement of any tokenizer)
env = OphanimEnv()
obs, _ = env.reset(7, {"errors": {"duplicate_invoice": 1, "fx_rate": 1}})
reset_bytes = len(json.dumps(obs))
total, cursor_by = 0, {}
step_bytes = {}
for table in ("ledger", "invoices", "payments", "fx"):
    cursor, tb = None, 0
    while True:
        o, *_ = env.step({"action": "list_records", "table": table, "cursor": cursor, "limit": 50})
        b = len(json.dumps(o))
        tb += b
        cursor = o["result"]["next_cursor"]
        if cursor is None:
            break
    step_bytes[table] = tb
out["obs_bytes"] = {"reset": reset_bytes, "full_scan_by_table": step_bytes,
                    "full_scan_total": reset_bytes + sum(step_bytes.values())}


# C. Degenerate "silent" policy on the official suite (same settings as `ophanim verify`)
class Silent:
    name = "silent"

    def reset(self, o, i):
        self.eid = o["manifest"]["episode_id"]

    def act(self, o):
        return {"action": "submit", "findings": {"episode_id": self.eid, "findings": []}}


suite = load_suite("configs/eval/official_suite.json")
secret = b"ophanim-verify-local-secret"
silent = []
issues_per_ep, evidence_union, ev_sizes = [], [], Counter()
for i, e in enumerate(suite["episodes"]):
    seed = derive_seed(DEFAULT_SEED_BASE, "eval", i)
    rec = run_episode(OphanimEnv(mode="eval", secret=secret), Silent(), seed, e["config"])
    silent.append((e["category"], rec.reward))
    ep = generate_episode(seed, e["config"], secret=secret)
    issues_per_ep.append(len(ep.sealed.truth.issues))
    u = set()
    for t in ep.sealed.truth.issues:
        smallest = min(t.allowed_evidence_sets, key=len)
        ev_sizes[(t.type, len(smallest))] += 1
        u.update(smallest)
    evidence_union.append(len(u))
out["silent_policy_official_suite"] = {
    "mean_return": round(statistics.mean(r for _, r in silent), 4),
    "by_category": {c: round(statistics.mean(r for cc, r in silent if cc == c), 4) for c in ("clean", "interacting", "mixed")},
}
out["official_suite_issue_counts"] = issues_per_ep
out["min_evidence_set_size_by_type"] = {f"{k[0]}:{k[1]}": v for k, v in sorted(ev_sizes.items())}
out["evidence_union_per_episode"] = evidence_union

# D. Reference auditor steps on the official suite
ra_steps = []
for i, e in enumerate(suite["episodes"]):
    seed = derive_seed(DEFAULT_SEED_BASE, "eval", i)
    ra_steps.append(run_episode(OphanimEnv(mode="eval", secret=secret), ReferenceAuditor(), seed, e["config"]).steps)
out["reference_auditor_steps_official"] = [min(ra_steps), statistics.median(ra_steps), max(ra_steps)]

# E. Return variance of the random explorer on dirty official episodes (from the verify report)
rep = json.load(open("runs/verify/report.json"))
rr = [r["reward"] for r in rep["episode_records"]["random_explorer"] if r["category"] != "clean"]
out["random_explorer_dirty_returns_unique"] = sorted(set(rr))

print(json.dumps(out, indent=1))
