#!/usr/bin/env bash
set -euo pipefail

DEV_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$DEV_DIR/../.." && pwd)"
DEV_ENV="$DEV_DIR/.env"
PORTAL_ENV="$REPO_ROOT/.env"

if [[ ! -f "$DEV_ENV" ]]; then
  cp "$DEV_DIR/.env.example" "$DEV_ENV"
  APP_KEY="base64:$(openssl rand -base64 32 | tr -d '\n')"
  DB_PASSWORD="$(openssl rand -hex 32)"
  DB_ROOT_PASSWORD="$(openssl rand -hex 32)"
  sed -i "s|^SNIPEIT_APP_KEY=.*|SNIPEIT_APP_KEY=$APP_KEY|; s|^SNIPEIT_DB_PASSWORD=.*|SNIPEIT_DB_PASSWORD=$DB_PASSWORD|; s|^SNIPEIT_DB_ROOT_PASSWORD=.*|SNIPEIT_DB_ROOT_PASSWORD=$DB_ROOT_PASSWORD|" "$DEV_ENV"
fi

if [[ ! -f "$PORTAL_ENV" ]]; then
  cp "$REPO_ROOT/.env.example" "$PORTAL_ENV"
fi

cd "$DEV_DIR"
export SNIPEIT_PORT=8081 SNIPEIT_APP_URL=http://localhost:8081
docker compose up -d

healthy=false
for _ in $(seq 1 60); do
  container_id="$(docker compose ps -q snipeit)"
  if [[ -n "$container_id" ]] && [[ "$(docker inspect --format '{{.State.Status}}' "$container_id" 2>/dev/null || true)" == running ]]; then
    if curl --fail --silent --output /dev/null --max-time 4 http://localhost:8081/login; then
      healthy=true
      break
    fi
  fi
  sleep 5
done
[[ "$healthy" == true ]] || { echo "Snipe-IT did not become healthy within five minutes." >&2; exit 1; }

if ! docker compose exec -T snipeit sh -c 'test -s /var/lib/snipeit/keys/oauth-private.key && test -s /var/lib/snipeit/keys/oauth-public.key' >/dev/null 2>&1; then
  docker compose exec -T snipeit php artisan passport:keys --force >/dev/null
  docker compose exec -T snipeit php artisan passport:install --force >/dev/null
fi
docker compose exec -T snipeit sh -c 'chmod 644 /var/lib/snipeit/keys/oauth-*' >/dev/null
docker compose exec -T snipeit php artisan tinker --execute='if (!DB::table("settings")->exists()) { DB::table("settings")->insert(["site_name" => "Snipe-IT", "per_page" => 20]); }' >/dev/null

admin_exists="$(docker compose exec -T snipeit php artisan tinker --execute='dump(DB::table("users")->where("username", "admin")->exists());' 2>/dev/null | tr -d '\r')"
if [[ "$admin_exists" != *true* ]]; then
  docker compose exec -T snipeit php artisan snipeit:create-admin --first_name=Dev --last_name=Admin --email=admin@example.test --username=admin --password=ChangeMe-Dev-Only-1 --no-interaction >/dev/null
fi

seed_code='$user = App\Models\User::firstOrCreate(["username" => "TEST-recipient"], ["first_name" => "TEST", "last_name" => "Recipient", "email" => "test.recipient@example.test", "password" => bcrypt(\Illuminate\Support\Str::random(48)), "activated" => 1]); $category = App\Models\Category::firstOrCreate(["name" => "TEST-Computer"], ["category_type" => "asset"]); $manufacturer = App\Models\Manufacturer::firstOrCreate(["name" => "TEST-Manufacturer"]); $model = App\Models\AssetModel::firstOrCreate(["name" => "TEST-Portal Model"], ["category_id" => $category->id, "manufacturer_id" => $manufacturer->id, "model_number" => "TEST-0001", "require_serial" => 1]); $status = App\Models\Statuslabel::firstOrCreate(["name" => "Ready to Deploy"], ["deployable" => 1]); App\Models\Asset::updateOrCreate(["serial" => "TEST-SN-0001"], ["asset_tag" => "TEST-A-0001", "name" => "TEST-Portal Asset", "model_id" => $model->id, "status_id" => $status->id]);'
docker compose exec -T snipeit php artisan tinker --execute="$seed_code" >/dev/null

portal_token="$(sed -n 's/^SNIPEIT_TOKEN=//p' "$PORTAL_ENV" | head -n 1)"
if [[ -z "$portal_token" ]]; then
  portal_token="$(docker compose exec -T snipeit php artisan snipeit:make-api-key --user_id=1 --name=dev-portal --key-only | tr -d '\r\n')"
fi
export PORTAL_SNIPEIT_TOKEN="$portal_token"
python - "$PORTAL_ENV" <<'PY'
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
lines = path.read_text(encoding="utf-8").splitlines()
values = {"SNIPEIT_URL": "http://localhost:8081", "SNIPEIT_TOKEN": os.environ["PORTAL_SNIPEIT_TOKEN"]}
for key, value in values.items():
    prefix = key + "="
    found = False
    updated = []
    for line in lines:
        if line.startswith(prefix):
            if not found:
                updated.append(prefix + value)
                found = True
        else:
            updated.append(line)
    if not found:
        updated.append(prefix + value)
    lines = updated
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
unset PORTAL_SNIPEIT_TOKEN portal_token
printf '%s\n' 'Snipe-IT is healthy at http://localhost:8081; TEST seed and portal configuration are ready.'
