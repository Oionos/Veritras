#!/usr/bin/env bash
set -euo pipefail
umask 077
cd "$(dirname "$0")/.."
rehearsal_project="${TESTING_COMPOSE_PROJECT:-veritras-testing}"
[[ "$rehearsal_project" =~ ^[a-z0-9_-]+$ ]] || exit 1
compose=(docker compose -p "$rehearsal_project" -f compose.testing.yml)
rehearsal_tag="$(python3 -c 'import uuid;print(uuid.uuid4().hex[:8])')"
rehearsal_db="veritras_rehearsal_$rehearsal_tag"
rehearsal_dir=".testing/release-rehearsal-$rehearsal_tag"
mkdir -p "$rehearsal_dir"
# Guard the environment, RPC and source database, then hold the existing writer
# lock across the backup and both fingerprints. No API writes run concurrently
# in this serial local rehearsal. Closing stdin also releases the database lock.
coproc rehearsal_lock { "${compose[@]}" exec -T backend python rehearse_local_release.py --hold-writer-lock; }
rehearsal_lock_pid="$rehearsal_lock_PID"
exec {rehearsal_input}>&"${rehearsal_lock[1]}"
cleanup() { printf 'release\n' >&"$rehearsal_input" || true; exec {rehearsal_input}>&-; wait "$rehearsal_lock_pid" || true; }
trap cleanup EXIT
read -r rehearsal_source <&"${rehearsal_lock[0]}"
printf '%s\n' "$rehearsal_source" > "$rehearsal_dir/source.json"
"${compose[@]}" exec -T postgres pg_dump -U veritras_test -d veritras_test -Fc --no-owner --no-acl > "$rehearsal_dir/backup.dump"
# createdb refuses an existing name; a previous/user database is never overwritten.
"${compose[@]}" exec -T postgres createdb -U veritras_test "$rehearsal_db"
"${compose[@]}" exec -T postgres pg_restore -U veritras_test -d "$rehearsal_db" --no-owner --no-acl --exit-on-error < "$rehearsal_dir/backup.dump"
"${compose[@]}" exec -T backend python rehearse_local_release.py --database "$rehearsal_db" > "$rehearsal_dir/restored.log"
"${compose[@]}" exec -T backend python rehearse_local_release.py > "$rehearsal_dir/source-after.json"
cleanup
trap - EXIT
python3 - "$rehearsal_dir" "$rehearsal_db" <<'PY'
import json,sys
from pathlib import Path
path=Path(sys.argv[1]);before=json.loads((path/'source.json').read_text());after=json.loads((path/'source-after.json').read_text())
restored=json.loads((path/'restored.log').read_text().splitlines()[-1])
assert restored['passed'] and before==after
assert restored['digest']==before['digest'] and restored['counts']==before['counts']
(path/'result.json').write_text(json.dumps({'passed':True,'database':sys.argv[2],'digest':before['digest'],'counts':before['counts']},indent=2)+'\n')
print('PASS: isolated backup/restore, schema admission and read-only identity/history reconciliation preserved all business and journal data')
PY
# Keep the named rehearsal database and private backup for review. No database
# drop, source reset, wallet material or hosted credentials are involved.
