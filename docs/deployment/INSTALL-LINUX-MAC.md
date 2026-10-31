# Install the Handover Portal on Linux or macOS

**NOT VERIFIED.** This draft has not been run on Linux or macOS. Do not treat these steps as verified.

1. Install Git, Python 3.10 or newer (3.11+ recommended), and Docker Engine with the Compose plugin if using the local Snipe-IT development instance.
2. Clone the published `docs/deployment-guide` branch from `https://github.com/adelromany/auto-check-asset-management.git`.
3. Create a Python virtual environment, install `requirements.txt`, copy `.env.example` to `.env`, create a random `SESSION_SECRET`, then run `python -m alembic upgrade head`.
4. Use `SSO_ENABLED=false` only for loopback development. Configure Entra SSO and HTTPS before shared use.
5. Review `deploy/snipeit-dev/README.md` before starting the development Docker Compose stack. It is not verified on Linux or macOS.
6. Run `python -m pytest -q` and confirm `/api/health` reports `status: ok`.

Every command and expected result in this draft needs clean-machine verification before it is published as a supported installation path.
