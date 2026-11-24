#!/usr/bin/env bash
# Exercise the actual launcher without a real Docker daemon or user .env.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
task_tmp="$(mktemp -d /tmp/sensorhub-launcher.XXXXXXXX)"
trap 'rm -rf -- "$task_tmp"' EXIT
mkdir "$task_tmp/bin"
cp "$root/run.sh" "$task_tmp/run.sh"

cat > "$task_tmp/bin/docker" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$DOCKER_TRACE"
case "$*" in
  'context show') echo default ;;
  'info --format '*) echo /var/lib/docker ;;
  *'ps -q chirpstack-postgres') echo test-container ;;
  inspect*) echo healthy ;;
esac
STUB
cat > "$task_tmp/bin/python3" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$PYTHON_TRACE"
if [ "$1" = 'scripts/setup_env.py' ]; then
  printf 'DOMAIN=http://\n' > .env
fi
STUB
cat > "$task_tmp/bin/id" <<'STUB'
#!/usr/bin/env bash
echo 0
STUB
chmod +x "$task_tmp/bin/"*
export PATH="$task_tmp/bin:$PATH"
export PYTHON_TRACE="$task_tmp/python.trace" DOCKER_TRACE="$task_tmp/docker.trace"
cd "$task_tmp"

printf 'DOMAIN=http://\n' > .env
bash run.sh > /dev/null
if grep -q provision_chirpstack "$PYTHON_TRACE"; then
  echo 'FAIL: ordinary startup invoked ChirpStack provisioning' >&2
  exit 1
fi
echo 'PASS: ordinary startup never invokes ChirpStack provisioning or key preparation'

: > "$PYTHON_TRACE"
bash run.sh --reset-database > /dev/null
if grep -q provision_chirpstack "$PYTHON_TRACE"; then
  echo 'FAIL: application database reset invoked ChirpStack provisioning' >&2
  exit 1
fi
echo 'PASS: application database reset leaves ChirpStack provisioning alone'

: > "$PYTHON_TRACE"
bash run.sh --bootstrap-chirpstack > /dev/null
test "$(grep -c provision_chirpstack "$PYTHON_TRACE")" -eq 2
echo 'PASS: explicit bootstrap prepares credentials and runs create-only bootstrap'

rm .env
: > "$PYTHON_TRACE"
bash run.sh --local > /dev/null
test "$(grep -c provision_chirpstack "$PYTHON_TRACE")" -eq 2
test "$(grep -c 'scripts/setup_env.py --local' "$PYTHON_TRACE")" -eq 1
echo 'PASS: first-time local setup bootstraps automatically'
