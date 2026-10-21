"""Stage 5 (code only): the contract's baseline ranking. Integer arithmetic; mean is Decimal half-up."""
import csv
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path


def mean_str(total, n):
    return str((Decimal(total) / Decimal(n)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))


def rank(membership, severity_by_id):
    members = defaultdict(list)
    for iid, rid in membership:
        members[iid].append(severity_by_id[rid])
    rows = [{"issue_id": iid, "complaint_count": len(v), "severity_sum": sum(v),
             "mean_severity": mean_str(sum(v), len(v)), "priority_score": sum(v)} for iid, v in members.items()]
    rows.sort(key=lambda r: (-r["priority_score"], r["issue_id"]))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


def write_ranking(rows, path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    cols = ["rank", "issue_id", "complaint_count", "severity_sum", "mean_severity", "priority_score"]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore"); w.writeheader(); w.writerows(rows)
