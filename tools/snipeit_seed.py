"""Seed the local Snipe-IT dev instance with V2 TEST data (idempotent).

Reads SNIPEIT_URL and SNIPEIT_TOKEN from the environment (or .env at the repo
root). Safe to run twice: the second run prints only "exists" lines.

    python tools/snipeit_seed.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

BASE_URL = os.getenv("SNIPEIT_URL", "").rstrip("/")
TOKEN = os.getenv("SNIPEIT_TOKEN", "")

COMPANIES = ["B.tech", "Nexta", "Mylo"]
STATUS_LABELS = [
    {"name": "Maintenance", "type": "undeployable", "color": "#ff9900"},
    # Snipe-IT keeps a checked-out asset on its old status unless the checkout
    # call carries a status; the probe needs the usual "Deployed" label.
    {"name": "Deployed", "type": "deployable", "color": "#3c8dbc", "default_label": True},
]
CATEGORIES = ["Laptop"]
MANUFACTURERS = ["Dell"]
MODELS = [{"name": "Latitude 5440", "category": "Laptop", "manufacturer": "Dell"}]
ASSETS = [
    {"serial": "TEST-SN-0001", "company": "B.tech"},
    {"serial": "TEST-SN-0002", "company": "B.tech"},
    {"serial": "TEST-SN-0003", "company": "Mylo"},
    {"serial": "TEST-SN-0004", "company": "Nexta"},
    {"serial": "TEST-SN-0005", "company": "B.tech"},
]
USERS = [
    {"username": "test.btech1", "first_name": "TEST", "last_name": "Btech1", "company": "B.tech"},
    {"username": "test.btech2", "first_name": "TEST", "last_name": "Btech2", "company": "B.tech"},
    {"username": "test.mylo1", "first_name": "TEST", "last_name": "Mylo1", "company": "Mylo"},
    {"username": "test.nexta1", "first_name": "TEST", "last_name": "Nexta1", "company": "Nexta"},
]
USER_PASSWORD = "Test-Dev-Only-1"


class Seed:
    def __init__(self) -> None:
        if not BASE_URL or not TOKEN:
            raise SystemExit("SNIPEIT_URL and SNIPEIT_TOKEN must be set (see .env).")
        self.http = httpx.Client(
            base_url=BASE_URL,
            headers={
                "Authorization": f"Bearer {TOKEN}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )
        self.failed = False

    def close(self) -> None:
        self.http.close()

    # -- helpers ----------------------------------------------------------
    def _rows(self, path: str, **params: object) -> list[dict]:
        params = {"limit": 500, **params}
        response = self.http.get(path, params=params)
        self._check(response, path)
        data = response.json()
        if isinstance(data, dict):
            rows = data.get("rows")
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
            return [data]
        return [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []

    def _find(self, path: str, name: str) -> dict | None:
        needle = name.casefold()
        for row in self._rows(path):
            if str(row.get("name") or "").casefold() == needle:
                return row
        return None

    def _check(self, response: httpx.Response, label: str) -> None:
        if response.status_code >= 400:
            self.failed = True
            body = response.text[:300]
            print(f"FAIL {label}: HTTP {response.status_code} {body}")

    def _create(self, path: str, payload: dict, label: str) -> dict | None:
        response = self.http.post(path, json=payload)
        try:
            data = response.json()
        except ValueError:
            data = None
        if isinstance(data, dict) and str(data.get("status") or "").casefold() == "error":
            if response.status_code == 422 or self._already_exists(response):
                print(f"exists {label}")
                return None
            self.failed = True
            print(f"FAIL {label}: {str(data.get('messages') or data)[:300]}")
            return None
        if response.status_code >= 400:
            self._check(response, label)
            return None
        print(f"created {label}")
        if isinstance(data, dict):
            payload_row = data.get("payload")
            if isinstance(payload_row, dict):
                return payload_row
        return None

    @staticmethod
    def _already_exists(response: httpx.Response) -> bool:
        body = response.text.casefold()
        return "already" in body or "taken" in body or "unique" in body

    # -- objects ----------------------------------------------------------
    def company(self, name: str) -> dict | None:
        row = self._find("/api/v1/companies", name)
        if row:
            print(f"exists company {name}")
            return row
        created = self._create("/api/v1/companies", {"name": name}, f"company {name}")
        return created or self._find("/api/v1/companies", name)

    def status_label(self, spec: dict) -> dict | None:
        row = self._find("/api/v1/statuslabels", spec["name"])
        if row:
            print(f"exists status {spec['name']}")
            return row
        created = self._create("/api/v1/statuslabels", spec, f"status {spec['name']}")
        return created or self._find("/api/v1/statuslabels", spec["name"])

    def category(self, name: str) -> dict | None:
        row = self._find("/api/v1/categories", name)
        if row:
            print(f"exists category {name}")
            return row
        created = self._create(
            "/api/v1/categories",
            {"name": name, "category_type": "asset"},
            f"category {name}",
        )
        return created or self._find("/api/v1/categories", name)

    def manufacturer(self, name: str) -> dict | None:
        row = self._find("/api/v1/manufacturers", name)
        if row:
            print(f"exists manufacturer {name}")
            return row
        created = self._create("/api/v1/manufacturers", {"name": name}, f"manufacturer {name}")
        return created or self._find("/api/v1/manufacturers", name)

    def model(self, spec: dict, category_id: int, manufacturer_id: int) -> dict | None:
        row = self._find("/api/v1/models", spec["name"])
        if row:
            print(f"exists model {spec['name']}")
            return row
        payload = {
            "name": spec["name"],
            "category_id": category_id,
            "manufacturer_id": manufacturer_id,
            "model_number": spec["name"].replace(" ", "-"),
        }
        created = self._create("/api/v1/models", payload, f"model {spec['name']}")
        return created or self._find("/api/v1/models", spec["name"])

    def asset(self, spec: dict, model_id: int, status_id: int, company_id: int) -> dict | None:
        serial = spec["serial"]
        rows = self._rows("/api/v1/hardware", search=serial)
        for row in rows:
            if str(row.get("serial") or "").casefold() == serial.casefold():
                print(f"exists asset {serial}")
                return self._align_asset(row, serial, model_id, company_id)

        payload = {
            "asset_tag": serial,
            "serial": serial,
            "name": f"TEST {serial}",
            "model_id": model_id,
            "status_id": status_id,
            "company_id": company_id,
            "purchase_date": "2025-01-15",
        }
        created = self._create("/api/v1/hardware", payload, f"asset {serial}")
        if created:
            return created
        rows = self._rows("/api/v1/hardware", search=serial)
        for row in rows:
            if str(row.get("serial") or "").casefold() == serial.casefold():
                return row
        return None

    def _align_asset(
        self, row: dict, serial: str, model_id: int, company_id: int
    ) -> dict:
        """Keep an older TEST asset on the company/model the plan expects."""
        current_company = (row.get("company") or {}).get("id")
        current_model = (row.get("model") or {}).get("id")
        if current_company == company_id and current_model == model_id:
            return row
        response = self.http.patch(
            f"/api/v1/hardware/{row['id']}",
            json={"company_id": company_id, "model_id": model_id},
        )
        self._check(response, f"align asset {serial}")
        if response.status_code < 400:
            print(f"updated asset {serial}")
        rows = self._rows("/api/v1/hardware", search=serial)
        for fresh in rows:
            if str(fresh.get("serial") or "").casefold() == serial.casefold():
                return fresh
        return row

    def user(self, spec: dict, company_id: int) -> dict | None:
        row = self._find_user(spec["username"])
        if row:
            print(f"exists user {spec['username']}")
            return row
        payload = {
            "username": spec["username"],
            "first_name": spec["first_name"],
            "last_name": spec["last_name"],
            "email": f"{spec['username']}@example.test",
            "company_id": company_id,
            "password": USER_PASSWORD,
            "password_confirmation": USER_PASSWORD,
            "activated": True,
        }
        created = self._create("/api/v1/users", payload, f"user {spec['username']}")
        return created or self._find_user(spec["username"])

    def _find_user(self, username: str) -> dict | None:
        needle = username.casefold()
        for row in self._rows("/api/v1/users", search=username):
            if str(row.get("username") or "").casefold() == needle:
                return row
        return None

    def checkout(self, asset: dict, user: dict) -> None:
        if asset.get("assigned_to") and (asset.get("assigned_to") or {}).get("id") == user.get("id"):
            print(f"exists checkout {asset.get('serial')} -> {user.get('username')}")
            return
        response = self.http.post(
            f"/api/v1/hardware/{asset['id']}/checkout",
            # Snipe-IT rejects "assigned_to" here; the key is "assigned_user".
            json={"assigned_user": user["id"], "checkout_to_type": "user", "note": "V2 seed"},
        )
        try:
            data = response.json()
        except ValueError:
            data = {}
        if str((data or {}).get("status") or "").casefold() == "error":
            self.failed = True
            print(f"FAIL checkout {asset.get('serial')}: {response.text[:300]}")
            return
        self._check(response, f"checkout {asset.get('serial')}")
        if response.status_code < 400:
            print(f"created checkout {asset.get('serial')} -> {user.get('username')}")

    # -- run --------------------------------------------------------------
    def run(self) -> int:
        companies = {name: self.company(name) for name in COMPANIES}
        for name in COMPANIES:
            if companies.get(name) is None:
                self.failed = True
                print(f"FAIL company {name} could not be resolved")

        ready = self._find("/api/v1/statuslabels", "Ready to deploy")
        if ready:
            print("exists status Ready to deploy")
        else:
            self.failed = True
            print("FAIL status Ready to deploy is missing")
        status_ids = [ready]
        status_ids += [self.status_label(spec) for spec in STATUS_LABELS]
        ready_id = ready["id"] if ready else None
        for spec in STATUS_LABELS:
            row = self._find("/api/v1/statuslabels", spec["name"])
            if row is None:
                self.failed = True
        if ready_id is None:
            raise SystemExit("Ready to deploy status label is missing; cannot seed assets.")

        categories = {name: self.category(name) for name in CATEGORIES}
        manufacturers = {name: self.manufacturer(name) for name in MANUFACTURERS}
        model_rows = {}
        for spec in MODELS:
            category = categories.get(spec["category"])
            manufacturer = manufacturers.get(spec["manufacturer"])
            if not category or not manufacturer:
                self.failed = True
                print(f"FAIL model {spec['name']}: missing category or manufacturer")
                continue
            model_rows[spec["name"]] = self.model(spec, category["id"], manufacturer["id"])

        asset_rows = {}
        for spec in ASSETS:
            company = companies.get(spec["company"])
            model_row = model_rows.get(MODELS[0]["name"])
            if not company or not model_row:
                self.failed = True
                print(f"FAIL asset {spec['serial']}: missing company or model")
                continue
            asset_rows[spec["serial"]] = self.asset(spec, model_row["id"], ready_id, company["id"])

        user_rows = {}
        for spec in USERS:
            company = companies.get(spec["company"])
            if not company:
                self.failed = True
                print(f"FAIL user {spec['username']}: missing company")
                continue
            user_rows[spec["username"]] = self.user(spec, company["id"])

        asset_0005 = asset_rows.get("TEST-SN-0005")
        user_btech2 = user_rows.get("test.btech2")
        if asset_0005 and user_btech2:
            self.checkout(asset_0005, user_btech2)

        return 1 if self.failed else 0


def main() -> int:
    seed = Seed()
    try:
        return seed.run()
    finally:
        seed.close()


if __name__ == "__main__":
    sys.exit(main())
