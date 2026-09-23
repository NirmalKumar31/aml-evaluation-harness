"""One dated cost table, computed from measured hours and PUBLISHED list prices.

WHY THIS EXISTS. The project had four different cost claims in four places --
"under $5", "roughly $21", "roughly $30", and "$0" -- with no scope attached to
any of them, so a reader could not tell whether they disagreed or described
different things. They described different things.

WHY IT IS AN ESTIMATE AND SAYS SO. The subscription is an Azure free trial, and
its consumption API returns `pretaxCost: null` for every meter -- credits are
not billed per meter, so there is no authoritative per-resource figure to read.
What can be established exactly is the elapsed resource time; what has to be
looked up is the price. So this multiplies measured hours by the PUBLIC retail
price list (prices.azure.com, no authentication, quoted with its fetch date)
and labels the result an estimate at list price. An account with credits pays
nothing; the table says what it would have cost.

Deliberately NOT read from the subscription: resource names, the subscription
id, the tenant. A cost table does not need them and a public document should
not carry them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

PRICES_API = "https://prices.azure.com/api/retail/prices"

# The resources actually deployed, by SKU. Checked against `az resource list`;
# the Bicep additionally declares a NAT gateway that this deployment does not
# have, and a table that priced the DESIGN rather than the DEPLOYMENT would be
# wrong in the expensive direction.
RESOURCES = [
    {"what": "VM (Standard_E4ds_v7, Linux)", "unit": "hour",
     "filter": "armRegionName eq 'eastus' and armSkuName eq 'Standard_E4ds_v7' "
               "and priceType eq 'Consumption'",
     # Spot and Low Priority share the SKU name and are ~80% cheaper. Matching
     # on the product name alone picked the spot price and reported the VM at
     # $0.077/h instead of $0.416/h -- an 82% understatement, in a table whose
     # entire purpose is to stop cost claims from disagreeing with each other.
     "match": lambda i: (i["productName"].endswith("Linux")
                         and "Spot" not in i["skuName"]
                         and "Low Priority" not in i["skuName"])},
    {"what": "OS disk (Premium SSD, 64 GB)", "unit": "month",
     "filter": "armRegionName eq 'eastus' and serviceName eq 'Storage' "
               "and skuName eq 'P6 LRS'",
     "match": lambda i: i["meterName"] == "P6 LRS Disk"},
    {"what": "spill disk (Standard SSD, 1024 GB)", "unit": "month",
     "filter": "armRegionName eq 'eastus' and serviceName eq 'Storage' "
               "and skuName eq 'E30 LRS'",
     "match": lambda i: i["meterName"] == "E30 LRS Disk"},
    {"what": "public IP (Standard, static)", "unit": "hour",
     "filter": "armRegionName eq 'eastus' and serviceName eq 'Virtual Network' "
               "and skuName eq 'Standard'",
     "match": lambda i: i["meterName"] == "Standard IPv4 Static Public IP"},
    # THE ACCOUNT THAT HELD THE RESULTS WAS NOT IN THIS TABLE. `blob_stored_gb`
    # was recorded in the output and then priced at nothing, so the artifact
    # quoted a stored volume and charged zero for it -- in a table whose whole
    # point is that a cost claim names its scope. Priced per GB-month against
    # the FIRST storage tier, scaled by the operator-supplied `--blob-bytes`.
    # ⛔ MATCH THE DEPLOYMENT, NOT THE FAMILY. This matched
    # "General Block Blob v2" ($0.0208), but `infra/main.bicep` sets
    # `isHnsEnabled: true`, so the account is ADLS Gen2 and its meter is the
    # Hierarchical Namespace one ($0.021). Same mistake shape as the VM spot
    # price: a plausible row that is not this deployment's row.
    {"what": "blob storage (Hot LRS, ADLS Gen2, data stored)", "unit": "month",
     "filter": "armRegionName eq 'eastus' and serviceName eq 'Storage' "
               "and skuName eq 'Hot LRS' and priceType eq 'Consumption'",
     "match": lambda i: (i["productName"]
                         == "General Block Blob v2 Hierarchical Namespace"
                         and i["meterName"] == "Hot LRS Data Stored"
                         and i.get("tierMinimumUnits", 0) == 0),
     # Per GB, unlike every other line, which bills per resource.
     "qty": lambda a: a.blob_bytes / 1e9},
    {"what": "container registry (Basic)", "unit": "day",
     "filter": "armRegionName eq 'eastus' and serviceName eq 'Container Registry' "
               "and skuName eq 'Basic'",
     "match": lambda i: "Registry Unit" in i["meterName"]},
]


# Every price response this run received, by request. An audit's point: the
# only INPUT to this artifact is an external API whose answer changes without
# notice, and the artifact recorded nothing about what it was told -- so a
# figure could not be traced back to the response that produced it, and two
# runs differing only because Azure repriced a meter were indistinguishable
# from two runs differing because of a bug.
_RESPONSES: list[dict] = []


def retail_price(flt: str, match) -> tuple[float, str]:
    url = f"{PRICES_API}?$filter={urllib.parse.quote(flt)}"
    with urllib.request.urlopen(url, timeout=30) as fh:
        raw = fh.read()
    items = json.loads(raw).get("Items", [])
    hits = [i for i in items if match(i)]
    if not hits:
        raise SystemExit(f"no retail price matched: {flt}")
    # AND A SILENT hits[0] IS HOW THE VM CAME BACK AT THE SPOT PRICE. The
    # filter matching more than one meter is not itself an error -- Azure
    # returns duplicate rows for the same meter -- but the matches DISAGREEING
    # on price means the selection is ambiguous and the first row won by
    # accident. Two of the six resources here legitimately match twice.
    distinct = {i["retailPrice"] for i in hits}
    if len(distinct) > 1:
        raise SystemExit(
            f"ambiguous retail price: {len(hits)} meters matched at prices "
            f"{sorted(distinct)} -- narrow the match. filter: {flt}")
    _RESPONSES.append({
        "filter": flt,
        "url": url,
        "response_sha256": hashlib.sha256(raw).hexdigest(),
        "response_bytes": len(raw),
        "items_returned": len(items),
        "matched": {k: hits[0].get(k) for k in
                    ("meterId", "meterName", "skuName", "armRegionName",
                     "retailPrice", "unitOfMeasure", "effectiveStartDate")},
    })
    return float(hits[0]["retailPrice"]), hits[0]["unitOfMeasure"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--created", required=True,
                    help="VM creation time, ISO-8601 UTC")
    ap.add_argument("--until", default=None, help="default: now")
    # REQUIRED, because the default made it worse. With `--blob-bytes`
    # omitted the storage row still printed, at quantity 0 and $0.00, under a
    # `basis` note asserting that blob storage IS priced -- a listed resource
    # silently costed at nothing, which is exactly what adding the row was
    # meant to stop. Enumerate it: `az storage blob list --account-name "$SA"
    # --auth-mode login -c aml --query "[].properties.contentLength" -o tsv`.
    ap.add_argument("--blob-bytes", type=int, required=True,
                    help="measured container size in bytes; enumerate it, "
                         "do not estimate it")
    ap.add_argument("--out", default="results_archive/derived/cost.json")
    a = ap.parse_args(argv)

    from aml.manifest import generator_provenance
    t0 = datetime.fromisoformat(a.created.replace("Z", "+00:00"))
    t1 = (datetime.fromisoformat(a.until.replace("Z", "+00:00")) if a.until
          else datetime.now(UTC))
    hours = (t1 - t0).total_seconds() / 3600

    lines, total = [], 0.0
    for r in RESOURCES:
        price, uom = retail_price(r["filter"], r["match"])
        per_hour = {"hour": price, "month": price / 730, "day": price / 24}[r["unit"]]
        qty = r.get("qty", lambda _a: 1.0)(a)
        cost = per_hour * hours * qty
        total += cost
        lines.append({"what": r["what"], "list_price": price, "unit": uom,
                      "usd_per_hour": round(per_hour * qty, 5),
                      "usd_per_hour_per_unit": round(per_hour, 5),
                      "quantity": round(qty, 4),
                      "hours": round(hours, 2), "usd": round(cost, 2)})

    out = {
        **generator_provenance(
            __file__,
            parameters={"created": a.created, "until": a.until,
                        "blob_bytes": a.blob_bytes,
                        "resources": [r["what"] for r in RESOURCES]}),
        "priced_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        # The request/response identity for every price used, so a number in
        # this file can be traced to the bytes Azure returned for it.
        "price_requests": _RESPONSES,
        "price_source": "https://prices.azure.com/api/retail/prices "
                        "(East US, pay-as-you-go list, USD)",
        "basis": "ELAPSED resource time since the VM was created, multiplied by "
                 "list price. It is NOT an upper bound on compute, and it "
                 "used to say it was: the justification given was that the VM "
                 "had been deallocated for part of the window, but the "
                 "subscription activity log for the whole window contains no "
                 "deallocate or powerOff operation at all -- the VM was shut "
                 "down from inside the guest OS, which holds the allocation "
                 "and bills compute in full. Treat the VM line as the elapsed "
                 "charge. The disks and the IP bill either way. The trial subscription reports pretaxCost: null for "
                 "every meter, so no authoritative per-resource figure exists. "
                 "SCOPE: the resources listed under `items` only. Blob storage "
                 "is priced for DATA AT REST at the first Hot LRS tier, scaled "
                 "by the --blob-bytes passed in; its transaction, egress and "
                 "early-deletion meters are NOT priced, and neither is any "
                 "resource outside the resource group -- notably the "
                 "Cloud Shell file share, which a resource-group delete does "
                 "not remove.",
        # PROVISIONAL UNTIL THE METER STOPS.
        #
        # `--until` is optional and defaults to now, so every regeneration
        # produced a larger number and every document that had copied the
        # previous one became wrong -- three snapshots were live in three
        # files at once. That is not a documentation problem to keep fixing;
        # it is a property of quoting a running total. The artifact now says
        # which kind of number it is, and a settled one requires naming the
        # end of the window explicitly.
        "snapshot_is_final": a.until is not None,
        "snapshot_note": (
            "FINAL: the window ends at the recorded window_end."
            if a.until else
            "PROVISIONAL: no end time was given, so this is elapsed time up to "
            "the moment of generation and it GROWS while the resources run. "
            "Regenerate with --until <ISO-8601> once they are stopped, and "
            "only then quote it as the project's cost."),
        "window_hours": round(hours, 2),
        "window_start": t0.isoformat(), "window_end": t1.isoformat(),
        "blob_stored_gb": round(a.blob_bytes / 1e9, 2),
        "items": lines,
        "total_usd_at_list": round(total, 2),
        # NOT A MEASUREMENT, and it used to be written as one.
        #
        # This field was `actually_charged_usd: 0.0`, hardcoded, in the same
        # object as a note saying the consumption API returns `pretaxCost:
        # null` for every meter on this subscription. A number no API returned,
        # sitting beside the sentence explaining that no API returns it, is the
        # kind of thing this project exists to stop. No invoice was retrieved,
        # so the charge is UNKNOWN and the zero is an inference from the
        # free-trial spending limit.
        "actually_charged_usd": None,
        "actually_charged_claim": "0.00 USD -- STATED, NOT MEASURED",
        "actually_charged_note": "An Azure free-trial subscription with the "
                                 "spending limit in place cannot bill a payment "
                                 "method, and the limit was never lifted -- so "
                                 "the charge is asserted to be zero on that "
                                 "basis. It is not an invoice figure: the "
                                 "consumption API returns pretaxCost: null for "
                                 "every meter here, and no billing statement "
                                 "was retrieved. Quote it as 'no charge "
                                 "expected under the trial credit', never as "
                                 "'$0 billed'.",
    }
    d = Path(a.out)
    d.parent.mkdir(parents=True, exist_ok=True)
    d.write_text(json.dumps(out, indent=1))
    for ln in lines:
        print(f"  {ln['what']:36s} {ln['usd_per_hour']:8.5f}/h x "
              f"{ln['hours']:7.2f}h = ${ln['usd']:7.2f}")
    print(f"  {'TOTAL at list price':36s} {'':19s} ${out['total_usd_at_list']:7.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
