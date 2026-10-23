#!/usr/bin/env bash
# Verify a finished run.
#
# Five independent checks, in the order that makes them useful: re-derive published findings from
# different code paths, run the competition's own evaluator over them, check the rights and rate policy of
# every finding, and read every rendered profile back against the claims it says it came from. The fifth step
# counts what the reviewer's own three rules changed in this run.
#
# usage: ./verify-run.sh out/run-1 [path to the competition starter kit]
set -euo pipefail

RUN="${1:?usage: verify-run.sh <run directory> [starter kit path]}"
KIT="${2:-../entry/kit}"
OUT="$RUN/checks"

if [ ! -f "$RUN/observations.jsonl" ]; then
  echo "no observations.jsonl in $RUN — run agent.py first" >&2
  exit 1
fi
mkdir -p "$OUT"

echo "1/5 independent re-check of published findings"
perl -e 'alarm 2400; exec @ARGV' python3 -u audit.py --observations "$RUN/observations.jsonl" --out "$OUT/audit" --limit 400

echo "2/5 the competition's external-footprint evaluator"
perl -e 'alarm 600; exec @ARGV' python3 "$KIT/scripts/evaluate_external_footprint.py" \
  --profiles "$RUN/profiles.jsonl" --observations "$RUN/observations.jsonl" \
  --labels "$OUT/audit/labels.jsonl" --output "$OUT/external-report.json"

echo "3/5 connector rights and rate policy"
perl -e 'alarm 300; exec @ARGV' python3 -u connector_report.py \
  --observations "$RUN/observations.jsonl" --run-report "$RUN/run-report.json" \
  --output "$OUT/connector-report.json"

echo "4/5 reading every profile back against its claims"
perl -e 'alarm 900; exec @ARGV' python3 -u check_profile.py --run "$RUN" --output "$OUT/profile-check.json"

echo "5/5 what the reviewer's three rules changed in this run"
perl -e 'alarm 300; exec @ARGV' python3 -u fix_report.py --run "$RUN" --output "$OUT/fix-report.json"

# The competition's internal scorer reads two fields that its own evaluator does not produce: a connector-policy
# flag and a freshness coverage figure. Both are computed here from the run's own records, and the freshness
# definition travels with the number.
python3 - "$RUN" "$OUT" <<'PY'
import json, sys, datetime
run_dir, out = sys.argv[1], sys.argv[2]
external = json.load(open(f"{out}/external-report.json"))
connector = json.load(open(f"{out}/connector-report.json"))
batch = json.load(open(f"{run_dir}/run-report.json"))
external["connector_policy_passed"] = bool(connector["connector_policy_passed"])

window_days = 45
ended = datetime.datetime.strptime(batch["completed_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
floor = ended - datetime.timedelta(days=window_days)
seen = set()
for line in open(f"{run_dir}/observations.jsonl", encoding="utf-8"):
    ob = json.loads(line)
    if ob.get("platform") == "brreg":
        continue  # a register reading is not a freshness claim about the open web
    stamp = str(ob.get("retrieved_at") or "")
    try:
        when = datetime.datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        continue
    if when >= floor:
        seen.add(str(ob["organisation_number"]))
profiles = len(open(f"{run_dir}/envelopes.jsonl", encoding="utf-8").readlines())
fresh = len(seen)
external["fresh_coverage"] = round(fresh / profiles, 6) if profiles else 0.0
external["freshness"] = {
    "definition": "share of profiles with at least one published finding whose source is outside the registers and whose recorded retrieval time falls within the stated window",
    "window_days": window_days,
    "companies": fresh,
    "profiles": profiles,
}
json.dump(external, open(f"{out}/external-report-for-scorer.json", "w"), ensure_ascii=False, indent=2)
PY

echo
echo "summaries:"
for name in audit external-report connector-report profile-check fix-report; do
  printf '  %s\n' "$OUT/$name.json"
done
echo
echo "then, with the reports produced by the commands in RUN.md:"
echo "  python3 $KIT/scripts/score_competition_v3.py --profiles $RUN/profiles.jsonl \\"
echo "    --external-report $OUT/external-report-for-scorer.json --batch-report $RUN/run-report.json \\"
echo "    --refresh-report <refresh report> --research-report <research report> --ux-report <ux report> \\"
echo "    --output $OUT/score.json"
