from __future__ import annotations

import subprocess

from app import config
from app.services import pdf_render


def _no_other_sources(monkeypatch) -> None:
    monkeypatch.setattr(config, "SOFFICE_PATH", "")
    monkeypatch.setattr(pdf_render.os.path, "isfile", lambda path: False)


def test_pdf_conversion_success(monkeypatch) -> None:
    _no_other_sources(monkeypatch)
    monkeypatch.setattr(pdf_render, "_word_converter", lambda: None)
    monkeypatch.setattr(pdf_render.shutil, "which", lambda name: "soffice")
    def run(args, **kwargs):
        output = args[args.index("--outdir") + 1]
        from pathlib import Path
        Path(output, "handover.pdf").write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(pdf_render.subprocess, "run", run)
    assert pdf_render.docx_to_pdf(b"docx") == b"%PDF-1.4"


def test_pdf_conversion_timeout_and_missing_binary(monkeypatch) -> None:
    _no_other_sources(monkeypatch)
    monkeypatch.setattr(pdf_render, "_word_converter", lambda: None)
    monkeypatch.setattr(pdf_render.shutil, "which", lambda name: None)
    assert pdf_render.docx_to_pdf(b"docx") is None
    monkeypatch.setattr(pdf_render.shutil, "which", lambda name: "soffice")
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("soffice", 60)
    monkeypatch.setattr(pdf_render.subprocess, "run", timeout)
    assert pdf_render.docx_to_pdf(b"docx") is None


def test_soffice_is_found_from_the_configured_path_first(monkeypatch) -> None:
    monkeypatch.setattr(config, "SOFFICE_PATH", r"D:\Office\soffice.exe")
    monkeypatch.setattr(pdf_render.os.path, "isfile", lambda path: path == r"D:\Office\soffice.exe")
    monkeypatch.setattr(pdf_render.shutil, "which", lambda name: "/usr/bin/soffice")

    assert pdf_render.find_soffice() == r"D:\Office\soffice.exe"


def test_soffice_is_found_in_the_standard_windows_folder_when_not_on_path(monkeypatch) -> None:
    standard = r"C:\Program Files\LibreOffice\program\soffice.exe"
    monkeypatch.setattr(config, "SOFFICE_PATH", "")
    monkeypatch.setattr(pdf_render.shutil, "which", lambda name: None)
    monkeypatch.setattr(pdf_render.os.path, "isfile", lambda path: path == standard)

    assert pdf_render.find_soffice() == standard


def test_a_bad_configured_path_falls_back_to_path(monkeypatch) -> None:
    monkeypatch.setattr(config, "SOFFICE_PATH", r"X:\missing\soffice.exe")
    monkeypatch.setattr(pdf_render.os.path, "isfile", lambda path: False)
    monkeypatch.setattr(pdf_render.shutil, "which", lambda name: "/usr/bin/soffice" if name == "soffice" else None)

    assert pdf_render.find_soffice() == "/usr/bin/soffice"


def test_nothing_installed_means_unavailable(monkeypatch) -> None:
    _no_other_sources(monkeypatch)
    monkeypatch.setattr(pdf_render.shutil, "which", lambda name: None)
    monkeypatch.setattr(pdf_render, "_word_converter", lambda: None)

    assert pdf_render.find_soffice() is None
    assert pdf_render.pdf_print_available() is False
    assert pdf_render.docx_to_pdf(b"docx") is None


def test_word_converts_when_libreoffice_is_missing(monkeypatch) -> None:
    from pathlib import Path

    _no_other_sources(monkeypatch)
    monkeypatch.setattr(pdf_render.shutil, "which", lambda name: None)

    def fake_word(source, output):
        Path(output).write_bytes(b"%PDF-from-word")

    monkeypatch.setattr(pdf_render, "_word_converter", lambda: fake_word)

    assert pdf_render.pdf_print_available() is True
    assert pdf_render.docx_to_pdf(b"docx") == b"%PDF-from-word"


def test_word_converter_is_never_used_off_windows(monkeypatch) -> None:
    monkeypatch.setattr(pdf_render.sys, "platform", "linux")

    assert pdf_render._word_converter() is None


def test_health_reports_pdf_print_state(sso_off_client, monkeypatch) -> None:
    monkeypatch.setattr("app.routers.health.pdf_print_available", lambda: False)
    assert sso_off_client.get("/api/health").json()["pdf_print"] == "unavailable"
    monkeypatch.setattr("app.routers.health.pdf_print_available", lambda: True)
    assert sso_off_client.get("/api/health").json()["pdf_print"] == "available"


def test_word_is_preferred_over_libreoffice(monkeypatch) -> None:
    from pathlib import Path

    _no_other_sources(monkeypatch)
    monkeypatch.setattr(pdf_render.shutil, "which", lambda name: "soffice")
    monkeypatch.setattr(pdf_render.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("LibreOffice must not run")))

    def fake_word(source, output):
        Path(output).write_bytes(b"%PDF-from-word")

    monkeypatch.setattr(pdf_render, "_word_converter", lambda: fake_word)
    assert pdf_render.docx_to_pdf(b"docx") == b"%PDF-from-word"


def test_libreoffice_is_used_when_word_fails(monkeypatch) -> None:
    _no_other_sources(monkeypatch)
    monkeypatch.setattr(pdf_render.shutil, "which", lambda name: "soffice")

    def broken_word(source, output):
        raise RuntimeError("COM error")

    monkeypatch.setattr(pdf_render, "_word_converter", lambda: broken_word)

    def run(args, **kwargs):
        from pathlib import Path
        Path(args[args.index("--outdir") + 1], "handover.pdf").write_bytes(b"%PDF-lo")

    monkeypatch.setattr(pdf_render.subprocess, "run", run)
    assert pdf_render.docx_to_pdf(b"docx") == b"%PDF-lo"
