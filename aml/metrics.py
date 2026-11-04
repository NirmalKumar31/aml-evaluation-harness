"""Stage 7: budget-aware evaluation at the (account, calendar-day) grain.

Each day an investigator can review k account-days. So every transaction
contributes to BOTH endpoints' account-day, an account-day's score is the max
over that day's transactions, and its label is the max (any laundering = 1).
Account-days are ranked within each day and the top k are "alerted".

Every number is reported beside two references:
  recall_ceiling@k  = sum_d min(P_d, k) / P            best any ranker can do
  null_precision@k  = sum_d min(k,N_d)*P_d/N_d / slots  what a random ranker scores
and the count of non-binding days (N_d <= k), where every ranker alerts the
whole day, so precision there equals prevalence and says nothing about the model.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

BUDGETS = (10, 25, 50, 100, 200, 500, 1000)


def to_account_days(df: pd.DataFrame, score: np.ndarray) -> pd.DataFrame:
    """Transactions -> (day, acct) rows: the UNION ALL + GROUP BY of the SQL version."""
    t = pd.DataFrame({"day": df.event_date.to_numpy(), "score": score,
                      "y": df.is_laundering.to_numpy(), "ring_id": df.ring_id.to_numpy()})
    both = pd.concat([t.assign(acct=df.sender_id.to_numpy()),
                      t.assign(acct=df.receiver_id.to_numpy())], ignore_index=True)
    ad = both.groupby(["day", "acct"], observed=True, sort=False).agg(
        score=("score", "max"), y=("y", "max")).reset_index()
    # Ring membership is many-to-many (one account-day can sit in several rings),
    # so it is kept as its own (day, acct, ring_id) relation, never collapsed.
    ad.attrs["membership"] = both.loc[both.ring_id.notna(), ["day", "acct", "ring_id"]].drop_duplicates()
    return ad


def _ranks(ad: pd.DataFrame) -> dict:
    g = ad.groupby("day")["score"]
    return {m: g.rank(ascending=False, method=m).to_numpy() for m in ("first", "min", "max")}


def budget_metrics(ad: pd.DataFrame, k: int, ranks: dict | None = None) -> dict:
    rk = ranks or _ranks(ad)
    y = (ad.y == 1).to_numpy()
    top = rk["first"] <= k                      # published tie policy: row order
    P, tp, alerts = int(y.sum()), int((y & top).sum()), int(top.sum())

    per_day = ad.groupby("day").agg(N=("y", "size"), P=("y", "sum"))
    N_d, P_d = per_day.N.to_numpy(np.int64), per_day.P.to_numpy(np.int64)   # y is TINYINT: widen first
    slots = np.minimum(k, N_d)
    ceiling = np.minimum(P_d, k).sum() / P if P else np.nan
    null = (slots * P_d / N_d).sum() / slots.sum()
    precision = tp / alerts if alerts else np.nan
    out = {
        f"precision@{k}": precision,
        f"recall@{k}": tp / P if P else np.nan,
        f"recall_ceiling@{k}": ceiling,
        f"null_precision@{k}": float(null),
        f"lift_over_null@{k}": precision / null if null else np.nan,
        f"nonbinding_days@{k}": int((N_d <= k).sum()),
        # ties: 'min' resolves every tie in a row's favour, 'max' against it
        f"recall_tie_optimistic@{k}": int((y & (rk["min"] <= k)).sum()) / P if P else np.nan,
        f"recall_tie_pessimistic@{k}": int((y & (rk["max"] <= k)).sum()) / P if P else np.nan,
    }
    mem = ad.attrs.get("membership")
    if mem is not None and len(mem):
        alerted = ad.loc[top, ["day", "acct"]]
        hit = mem.merge(alerted, on=["day", "acct"], how="left", indicator=True)
        out[f"ring_recall@{k}"] = float((hit["_merge"] == "both").groupby(hit.ring_id).any().mean())
    return out


def evaluate(df: pd.DataFrame, score: np.ndarray, budgets=BUDGETS) -> dict:
    if len(score) != len(df) or not np.isfinite(score).all():
        raise ValueError("score must be finite and align with the frame")
    ad = to_account_days(df, score)
    rk = _ranks(ad)
    out = {"n_account_days": len(ad), "n_positive_account_days": int((ad.y == 1).sum()),
           # transaction-level, so suffixed: a different denominator from the budget metrics
           "average_precision__txn": float(average_precision_score(df.is_laundering, score)),
           "roc_auc_footnote_only__txn": float(roc_auc_score(df.is_laundering, score))}
    for k in budgets:
        out.update(budget_metrics(ad, k, rk))
    return out
