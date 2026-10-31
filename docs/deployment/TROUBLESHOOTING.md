# Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Portal will not start; port 8080 already in use | Another process is listening on the portal port | Close the other process or choose an approved free port and update `APP_HOST`, `REDIRECT_URI`, and agent address consistently. |
| I see the Snipe-IT setup screen when I open the portal | You opened port 8081; the portal is on 8080 | Open `http://localhost:8080`. Snipe-IT development is `http://localhost:8081`. |
| `docker compose up -d` pull times out | Docker Hub/network unavailable or proxy blocks the pull | Check approved network/proxy access with IT and retry. Do not disable TLS verification or use unofficial mirrors. |
| Snipe-IT API returns HTTP 500; OAuth key error | Passport keys missing or unreadable by the web process | From `deploy/snipeit-dev`, run `docker compose exec snipeit php artisan passport:keys --force`, `docker compose exec snipeit php artisan passport:install --force`, then `docker compose exec snipeit sh -c "chmod 644 /var/lib/snipeit/keys/oauth-*"`. Restart and check logs. |
| Snipe-IT development login is unknown | Local database has different credentials | For the throwaway development instance only, run `docker compose down -v` in `deploy/snipeit-dev`, then run `scripts/setup.ps1` bootstrap path again. `down -v` deletes database and upload volumes. |
| Entra login reports redirect mismatch | `REDIRECT_URI` differs from the URI registered in the app | Make the URI match exactly, including scheme, host, port, and `/auth/callback`; ask the Entra administrator to register the chosen machine address. |
| A write reports `CSRF token missing` | The browser session lacks the expected CSRF token or the origin changed | Reload the portal and retry in the same browser origin. Do not bypass CSRF checks. |
| Startup refuses because the secret is empty or short | `SSO_ENABLED=true` with an empty or placeholder session secret | Generate `python -c "import secrets; print(secrets.token_hex(32))"` and set it as `SESSION_SECRET` in `.env`. Do not disclose it. |
| Agent command contains `localhost` on an employee's other PC | `APP_HOST` has its default local address | Set `APP_HOST` to the portal PC's reachable DNS name or IP and port; restart the portal and create a fresh session. |
| PowerShell refuses to run a script | Execution policy or downloaded-file mark blocks it | Use an approved signed script or ask IT for the approved policy. Do not weaken machine-wide execution policy. |
| SQLite reports locked or permission denied | Another portal process is using the DB or the account cannot write `data` | Stop duplicate portal processes; ensure the user can write the repository `data` folder; restart and rerun migrations. |
| Other PCs cannot reach port 8080 | Portal bound to loopback or firewall blocks inbound traffic | Bind to `0.0.0.0` only on an approved trusted network; ask IT to allow TCP 8080 for the internal subnet only. |
| Snipe-IT token returns unauthenticated / API health false | Wrong token, URL, or service-account permissions | Verify `SNIPEIT_URL` and token in the portal `.env`; use a dedicated account and required verified API permissions. Restart the portal. |

Docker-dependent fixes above are not verified in the current Windows session because its Docker engine was unavailable.
