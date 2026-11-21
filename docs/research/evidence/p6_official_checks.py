"""P6 evidence: run the published Block-3 matcher tests (1-20), examples M01-M12 and selected contract
checks against the CURRENT implementation. Read-only: builds fixtures in memory, writes nothing."""
from fractions import Fraction

from ophanim.env import OphanimEnv
from ophanim.evaluator.judge import Judge
from ophanim.generator import generate_episode
from ophanim.schemas import TruthFile, TruthIssue


class Sealed:
    def __init__(self, truth, universe):
        self.truth, self.evidence_universe = truth, universe


# Base public data: an existing episode supplies real ids (R1 = an invoice id, D1/D2/D3 = doc ids).
ep = generate_episode(1001, {"profile": "retail"})
inv = ep.public.tables["invoices"]
R1, R2, R3 = inv[0]["invoice_id"], inv[1]["invoice_id"], inv[2]["invoice_id"]
D1, D2, D3 = inv[0]["doc_id"], inv[1]["doc_id"], inv[2]["doc_id"]
U = "DOC-ZZZZZZZZZZ"
UNIVERSE = ep.public.evidence_universe()
assert U not in UNIVERSE
EID = ep.public.episode_id


def truth(issues, tol=0):
    return TruthFile(schema_version="1.0", episode_id=EID, base_currency="KZT", tolerance_minor=tol, issues=issues)


def issue(iid="A", ids=(R1,), amount=10000, ev=(D1, D2), type_="duplicate_invoice"):
    return TruthIssue(issue_id=iid, type=type_, affected_ids=list(ids), expected_amount_minor=amount,
                      currency="KZT", allowed_evidence_sets=[list(ev)], scenario="single")


def F(ids=(R1,), amount=10000, cur="KZT", ev=(D1, D2), type_="duplicate_invoice", text="short"):
    return {"type": type_, "affected_ids": list(ids), "claimed_amount_minor": amount, "currency": cur,
            "evidence_ids": list(ev), "explanation": text}


def score(t, findings, steps=10, universe=UNIVERSE):
    j = Judge(sealed=Sealed(t, universe))
    o = j.submit({"episode_id": EID, "findings": findings}, steps)
    return o


def show(name, o, exp):
    got = (o.tp, o.fp, o.fn, round(o.reward, 10)) if o.valid else ("INVALID", o.reward)
    ok = got == exp
    print(f"{'PASS' if ok else 'FAIL'}  {name:<62} got={got} expected={exp}")
    return ok


A = issue("A")
B = issue("B", ids=(R2,), ev=(D2, D3))
res = []
res.append(show("1 one correct F", score(truth([A]), [F()]), (1, 0, 0, 0.98)))
res.append(show("2 empty findings", score(truth([A]), []), (0, 0, 1, -1.0)))
res.append(show("3 empty truth, empty findings", score(truth([]), []), (0, 0, 0, 0.98)))
res.append(show("4 empty truth, one false finding", score(truth([]), [F()]), (0, 1, 0, -1.0)))
res.append(show("5 two identical F", score(truth([A]), [F(), F()]), (1, 1, 0, round(float(Fraction(47, 150)), 10))))
res.append(show("6 wrong type", score(truth([A]), [F(type_="fx_rate")]), (0, 1, 1, -1.0)))
res.append(show("7 other existing record in affected_ids", score(truth([A]), [F(ids=(R2,))]), (0, 1, 1, -1.0)))
res.append(show("8 amount 10001 with tau=0", score(truth([A], tol=0), [F(amount=10001)]), (0, 1, 1, -1.0)))
res.append(show("9 other currency", score(truth([A]), [F(cur="USD")]), (0, 1, 1, -1.0)))
res.append(show("10 only D1", score(truth([A]), [F(ev=(D1,))]), (0, 1, 1, -1.0)))
res.append(show("11 non-existent evidence instead of D2", score(truth([A]), [F(ev=(D1, U))]), (0, 1, 1, -1.0)))
mass = [F(ids=(r,), type_=t) for r in (R1, R2, R3, inv[3]["invoice_id"], inv[4]["invoice_id"])
        for t in ("duplicate_invoice", "payment_allocation", "fx_rate", "period_attribution")]
res.append(show("12 mark 5 records x 4 types", score(truth([A]), mass), (1, 19, 0, round(float(Fraction(-871, 1050)), 10))))
res.append(show("13 A and B, only F for A", score(truth([A, B]), [F()]), (1, 0, 1, round(float(Fraction(47, 150)), 10))))
res.append(show("14 A and B, F for A + one false", score(truth([A, B]), [F(), F(ids=(R3,))]), (1, 1, 1, -0.02)))
res.append(show("15 steps=0", score(truth([A]), [F()], steps=0), (1, 0, 0, 1.0)))
res.append(show("16 steps=50", score(truth([A]), [F()], steps=50), (1, 0, 0, 0.9)))
res.append(show("17 steps=100", score(truth([A]), [F()], steps=100), (1, 0, 0, 0.8)))
res.append(show("18 31 findings", score(truth([A]), [F()] * 31), ("INVALID", -1.0)))
res.append(show("19 11 distinct evidence ids", score(truth([A]), [F(ev=tuple(sorted(UNIVERSE))[:11])]), ("INVALID", -1.0)))
res.append(show("20 explanation 1001 ASCII", score(truth([A]), [F(text="x" * 1001)]), ("INVALID", -1.0)))
print(f"Block 3: {sum(res)}/20 pass\n")

# M01-M12 (single issue A: affected {R1,R2}, amount 10000 KZT, evidence {D1,D2}, tau=0)
AM = issue("A", ids=(R1, R2))
m = []
m.append(show("M01 affected [R2,R1,R1]", score(truth([AM]), [F(ids=(R2, R1, R1))]), (1, 0, 0, 0.98)))
m.append(show("M02 affected [R1,R2,R3]", score(truth([AM]), [F(ids=(R1, R2, R3))]), (0, 1, 1, -1.0)))
m.append(show("M03 evidence [D2,D1,D3]", score(truth([AM]), [F(ids=(R1, R2), ev=(D2, D1, D3))]), (1, 0, 0, 0.98)))
m.append(show("M04 evidence [D1,D2,U]", score(truth([AM]), [F(ids=(R1, R2), ev=(D1, D2, U))]), (0, 1, 1, -1.0)))
m.append(show("M05 11 evidence ids (10x D1)", score(truth([AM]), [F(ids=(R1, R2), ev=(D1,) * 10 + (D2,))]), ("INVALID", -1.0)))
m.append(show("M06a currency 'kzt' (case)", score(truth([AM]), [F(ids=(R1, R2), cur="kzt")]), (0, 1, 1, -1.0)))
m.append(show("M06b currency ' KZT' (space)", score(truth([AM]), [F(ids=(R1, R2), cur=" KZT")]), (0, 1, 1, -1.0)))
m.append(show("M07 amount 10001, tau=0", score(truth([AM], tol=0), [F(ids=(R1, R2), amount=10001)]), (0, 1, 1, -1.0)))
m.append(show("M08a tau=1, amount 10001", score(truth([AM], tol=1), [F(ids=(R1, R2), amount=10001)]), (1, 0, 0, 0.98)))
m.append(show("M08b tau=1, amount 10002", score(truth([AM], tol=1), [F(ids=(R1, R2), amount=10002)]), (0, 1, 1, -1.0)))
m.append(show("M09a amount '10000' string", score(truth([AM]), [F(ids=(R1, R2), amount="10000")]), ("INVALID", -1.0)))
m.append(show("M09b amount true", score(truth([AM]), [F(ids=(R1, R2), amount=True)]), ("INVALID", -1.0)))
# M10: F0 fits A and B, F1 fits only A  -> TP=2
A10 = issue("A", ids=(R1,), ev=(D1,)); B10 = issue("B", ids=(R1,), ev=(D2,))
o = score(truth([A10, B10]), [F(ids=(R1,), ev=(D1, D2)), F(ids=(R1,), ev=(D1,))])
m.append(show("M10 augmenting path F1->A, F0->B", o, (2, 0, 0, 0.98)))
print("     M10 pairs:", o.match.pairs)
# M11: F0, F1 both fit A and B; spec tie-break: A->F0, B->F1
A11 = issue("A", ids=(R1,), ev=(D1,)); B11 = issue("B", ids=(R1,), ev=(D1,))
o = score(truth([A11, B11]), [F(ids=(R1,), ev=(D1,)), F(ids=(R1,), ev=(D1,))])
m.append(show("M11 TP=2", o, (2, 0, 0, 0.98)))
spec_pairs = [(0, "A"), (1, "B")]
print(f"     M11 pairs (finding, issue): got {o.match.pairs}, spec requires {spec_pairs} ->",
      "PASS" if o.match.pairs == spec_pairs else "FAIL (tie-break differs; TP/FP/FN/reward unaffected)")
m.append(show("M12 two identical correct", score(truth([AM]), [F(ids=(R1, R2))] * 2), (1, 1, 0, round(float(Fraction(47, 150)), 10))))
print(f"M01-M12 (incl. split cases): {sum(m)}/{len(m)} pass\n")

# Normalisation rules beyond the numbered examples
print("== exact-match / structure rules from the 'exact matcher conventions' section ==")
show("ID case: affected ['r1'-style lowercase] must be FP", score(truth([A]), [F(ids=(R1.lower(),))]), (0, 1, 1, -1.0))
show("ID whitespace: affected [' R1'] must be FP", score(truth([A]), [F(ids=(" " + R1,))]), (0, 1, 1, -1.0))
show("unknown type string 'fraud' must be FP (not structural)", score(truth([A]), [F(type_="fraud")]), (0, 1, 1, -1.0))
show("negative integer amount must be FP (valid JSON int)", score(truth([A]), [F(amount=-5)]), (0, 1, 1, -1.0))
show("empty affected_ids must be FP (not a listed limit)", score(truth([A]), [F(ids=())]), (0, 1, 1, -1.0))
show("21 affected ids must be FP (not a listed limit)", score(truth([A]), [F(ids=tuple(i['invoice_id'] for i in inv[:21]))]), (0, 1, 1, -1.0))
show("65-char id must be FP (not a listed limit)", score(truth([A]), [F(ids=("X" * 65,))]), (0, 1, 1, -1.0))
show("evidence cites invoice ids (accessible via get_record)", score(truth([issue('A', ev=(R2, R3))]), [F(ev=(R2, R3))]), (1, 0, 0, 0.98))
show("1000 non-ASCII code points accepted", score(truth([A]), [F(text="ж" * 1000)]), (1, 0, 0, 0.98))

print("\n== contract checks on the current environment ==")
env = OphanimEnv(mode="eval")
obs, info = env.reset(1001, {"profile": "retail"})
print("C02 first-observation keys:", sorted(obs))
o, r, t, tr, i = env.step({"action": "get_record", "table": "invoices", "id": R1.lower()})
print("C11 get_record with a case-variant of an existing id (absent from data as a string): ok =", o["ok"],
      "-> FAIL (exact ids required; U is any string not in the data)" if o["ok"] else "-> PASS")
o, *_ = env.step({"action": "get_record", "table": "invoices", "id": R1})
print("C07 get_record result shape:", sorted(o["result"]), "(spec: the record object itself)")
o, *_ = env.step({"action": "list_records", "table": "ledger", "cursor": None, "limit": 50})
print("C05 list_records result keys:", sorted(o["result"]), "(spec: records, next_cursor)")
o, *_ = env.step({"action": "calculator", "expression": "0.1+0.2"})
print("C09 calculator result:", o["result"], "(spec: decimal string)")
o, *_ = env.step({"name": "list_records", "args": {"table": "ledger"}})
print("Envelope {'name','args'} accepted natively:", o["ok"], "(needs judge_adapter translation)")
try:
    env.reset(0, {"mode": "closed", "episode_dir": "x", "team_config": {}})
    print("reset(config with episode_dir): accepted")
except Exception as e:
    print("reset(config with mode/episode_dir/team_config):", type(e).__name__, "-> loading an episode_dir is NOT supported")
