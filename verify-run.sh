#!/usr/bin/env bash
# Verify a finished run.
#
# Four independent checks, in the order that makes them useful: re-derive published findings from
# different code paths, run the competition's own evaluator over them, check the rights and rate policy of
# every finding, and read every rendered profile back against the claims it says it came from.
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

echo "1/4 independent re-check of published findings"
perl -e 'alarm 2400; exec @ARGV' python3 -u audit.py --observations "$RUN/observations.jsonl" --out "$OUT/audit" --limit 400

echo "2/4 the competition's external-footprint evaluator"
perl -e 'alarm 600; exec @ARGV' python3 "$KIT/scripts/evaluate_external_footprint.py" \
  --profiles "$RUN/profiles.jsonl" --observations "$RUN/observations.jsonl" \
  --labels "$OUT/audit/labels.jsonl" --output "$OUT/external-report.json"

echo "3/4 connector rights and rate policy"
perl -e 'alarm 300; exec @ARGV' python3 -u connector_report.py \
  --observations "$RUN/observations.jsonl" --run-report "$RUN/run-report.json" \
  --output "$OUT/connector-report.json"

echo "4/4 reading every profile back against its claims"
perl -e 'alarm 900; exec @ARGV' python3 -u check_profile.py --run "$RUN" --output "$OUT/profile-check.json"

# The competition's internal scorer reads a connector-policy field that its own evaluator does not produce,
# so the two reports are combined here for that one field. Nothing else is changed.
python3 - "$OUT" <<'PY'
import json, sys
out = sys.argv[1]
external = json.load(open(f"{out}/external-report.json"))
connector = json.load(open(f"{out}/connector-report.json"))
external["connector_policy_passed"] = bool(connector["connector_policy_passed"])
json.dump(external, open(f"{out}/external-report-for-scorer.json", "w"), ensure_ascii=False, indent=2)
PY

echo
echo "summaries:"
for name in audit external-report connector-report profile-check; do
  printf '  %s\n' "$OUT/$name.json"
done
echo
echo "then, with the reports produced by the commands in RUN.md:"
echo "  python3 $KIT/scripts/score_competition_v3.py --profiles $RUN/profiles.jsonl \\"
echo "    --external-report $OUT/external-report-for-scorer.json --batch-report $RUN/run-report.json \\"
echo "    --refresh-report <refresh report> --research-report <research report> --ux-report <ux report> \\"
echo "    --output $OUT/score.json"
