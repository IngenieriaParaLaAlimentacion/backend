"""Reevaluate historical measurements with an installed SAP reference."""

import argparse
import asyncio
from uuid import UUID

from app.db.unit_of_work import UnitOfWork
from app.reference_data.sap_reference import SapRuleset, configured_ruleset
from app.services.measurements.assessment_service import persist_assessments

SUBJECT_PAGE_SIZE = 100


async def backfill(ruleset: SapRuleset, *, apply: bool) -> int:
    """Report coverage and optionally fill missing assessments."""
    async with UnitOfWork() as uow:
        missing = await uow.measurement_assessment_repo.count_missing(ruleset.version)
    print(f"ruleset={ruleset.version} missing_before={missing} apply={apply}")
    if not apply:
        return 0

    after: UUID | None = None
    processed = 0
    while True:
        async with UnitOfWork() as uow:
            subject_ids = await uow.measurement_assessment_repo.list_subjects_missing(
                ruleset.version, after, SUBJECT_PAGE_SIZE
            )
        if not subject_ids:
            break

        for subject_id in subject_ids:
            async with UnitOfWork() as uow:
                subject = await uow.subject_repo.get_for_update(subject_id)
                if subject is None:
                    continue
                missing_rows = (
                    await uow.measurement_assessment_repo.list_missing_for_subject(
                        ruleset.version, subject_id
                    )
                )
                for measurement in missing_rows:
                    await persist_assessments(uow, measurement, subject, ruleset)
                await uow.commit()
                processed += len(missing_rows)
        after = subject_ids[-1]

    async with UnitOfWork() as uow:
        remaining = await uow.measurement_assessment_repo.count_missing(ruleset.version)
    print(f"evaluated={processed} missing_after={remaining}")
    return int(remaining != 0)


def main() -> int:
    """Run the requested coverage or backfill operation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ruleset-version", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    ruleset = configured_ruleset()
    if ruleset is None or ruleset.version != args.ruleset_version:
        parser.error("--ruleset-version must match the configured write version")
    return asyncio.run(backfill(ruleset, apply=args.apply))


if __name__ == "__main__":
    raise SystemExit(main())
