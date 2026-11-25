"""Locate handover form templates by Snipe-IT company name."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.company_rules import normalize_company
from app.domain.errors import FormTemplateNotFound
from app.domain.form_fill import fill_engineer
from app.domain.stages import Operation, StageStatus
from app.services.handovers import HandoverService


def find_template(forms_dir: Path, company: str | None) -> Path | None:
    """Return the DOCX template whose filename matches the company."""
    normalized = normalize_company(company)
    if not normalized:
        return None
    if not forms_dir.is_dir():
        return None
    for path in sorted(forms_dir.glob("*.docx")):
        if normalize_company(path.stem) == normalized:
            return path
    return None


@dataclass(frozen=True)
class GeneratedForm:
    """A filled Word form and its download metadata."""

    content: bytes
    filename: str
    template: str
    engineer_name: str


class FormService:
    """Generate a handover form and record the form operation."""

    def __init__(self, session: AsyncSession, *, forms_dir: Path | str):
        self._session = session
        self._core = HandoverService(session)
        self._forms_dir = Path(forms_dir)

    async def generate(
        self,
        handover_id,
        *,
        actor: str,
        fallback_engineer_name: str = "",
    ) -> GeneratedForm:
        handover = await self._core.get(handover_id, with_details=True)
        company = handover.device_company
        template = find_template(self._forms_dir, company)
        if template is None:
            reason = f"No form template for {company or 'unknown company'}"
            await self._core.record_operation(
                handover_id,
                Operation.REPORT_PRINTED,
                status=StageStatus.FAILED,
                reason=reason,
                detail={},
                actor=actor,
                input_checks=False,
            )
            await self._session.commit()
            raise FormTemplateNotFound(reason)

        engineer_name = handover.engineer_name or fallback_engineer_name
        content = fill_engineer(template.read_bytes(), engineer_name)
        await self._core.record_operation(
            handover_id,
            Operation.REPORT_PRINTED,
            status=StageStatus.PASSED,
            reason=None,
            detail={"template": template.stem, "engineer": engineer_name},
            actor=actor,
            input_checks=False,
        )
        filename = f"{company or 'handover'}-{handover.device_serial}.docx"
        return GeneratedForm(
            content=content,
            filename=filename,
            template=template.stem,
            engineer_name=engineer_name,
        )
