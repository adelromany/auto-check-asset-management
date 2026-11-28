# Install the Handover Portal on Linux or macOS

**NOT VERIFIED.** This draft has not been run on Linux or macOS. Do not treat these steps as verified.

1. Install Git, Python 3.10 or newer (3.11+ recommended), and Docker Engine with the Compose plugin if using the local Snipe-IT development instance.
2. Clone the published `docs/deployment-guide` branch from `https://github.com/adelromany/auto-check-asset-management.git`.
3. Create a Python virtual environment, install `requirements.txt`, copy `.env.example` to `.env`, create a random `SESSION_SECRET`, then run `python -m alembic upgrade head`.
4. Use `SSO_ENABLED=false` only for loopback development. Configure Entra SSO and HTTPS before shared use.
5. Review `deploy/snipeit-dev/README.md` before starting the development Docker Compose stack. It is not verified on Linux or macOS.
6. Run `python -m pytest -q` and confirm `/api/health` reports `status: ok`.

For PDF printing on Debian/Ubuntu, install the headless Writer converter and Arabic-capable fonts:
`apt-get install -y --no-install-recommends libreoffice-writer-nogui fonts-noto-core fonts-noto-ui-core fonts-dejavu-core fonts-kacst`.
Confirm `soffice` is on the portal service account's `PATH`, then run
`python tools/check_pdf_render.py`. Download Word does not require LibreOffice.
On macOS, install LibreOffice and make its `soffice` executable available on `PATH`.
These conversion commands have not been verified in this Windows run.

Every command and expected result in this draft needs clean-machine verification before it is published as a supported installation path.
