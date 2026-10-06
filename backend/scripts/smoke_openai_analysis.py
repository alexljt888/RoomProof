"""Manual one-image smoke. Importing this module never runs inference."""
import argparse
import json
import logging
import os
from pathlib import Path

from openai import OpenAI

from backend.app.domain import AnalysisStatus, PropertyDetails
from backend.app.images import InMemoryImageSource, MAX_INPUT_BYTES
from backend.app.openai_analyzer import AnalyzerConfig, OpenAIPhotoAnalyzer
from backend.app.repository import InMemoryInspectionRepository
from backend.app.services import InspectionService

MODEL = "gpt-4.1-mini-2025-04-14"
MAX_PREPARED_IMAGE_BYTES = 20971520


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's normal message can echo private paths supplied as arguments.
        self.exit(2, "An explicit local JPEG/PNG image path is required.\n")


def summary(state):
    """Allowlist output; never serialize the inspection or provider objects."""
    analysis = next(iter(state.analyses.values()))
    result = analysis.result
    provenance = result.provenance
    findings = []
    for finding in state.findings.values():
        proposal = finding.original_proposal
        findings.append(dict(
            category=proposal.category, surface=proposal.surface,
            location=proposal.location, description=proposal.description,
            certainty=proposal.certainty, state=finding.state,
            eligible_for_report=finding.eligible_for_report,
        ))
    return dict(
        analysis_id=str(analysis.id), status=analysis.status,
        outcome=result.outcome, failure_code=result.failure_code,
        finding_count=len(findings), findings=findings,
        analyzer_id=provenance.analyzer_id, analyzer_version=provenance.analyzer_version,
        requested_model=provenance.requested_model, provider_model=provenance.provider_model,
        prompt_version=provenance.prompt_version, schema_version=provenance.schema_version,
        preparation_version=provenance.preparation_version,
    )


def main(argv=None):
    parser = SafeArgumentParser(description="Manual single-image provider smoke; requires separate execution authorization.")
    parser.add_argument("image", help="local JPEG/PNG image (never printed or sent as a path)")
    args = parser.parse_args(argv)
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        print("Required API key is not configured.")
        return 2

    try:
        # Bound the read before binding or decoding; never load an arbitrary-size file.
        with Path(args.image).open("rb") as stream:
            raw = stream.read(MAX_INPUT_BYTES + 1)
        if not raw or len(raw) > MAX_INPUT_BYTES:
            raise ValueError()
        if raw.startswith(b"\x89PNG\r\n\x1a\n"):
            filename, media_type = "smoke.png", "image/png"
        elif raw.startswith(b"\xff\xd8"):
            filename, media_type = "smoke.jpg", "image/jpeg"
        else:
            raise ValueError()
    except (OSError, ValueError):
        print("Image could not be read as a supported input.")
        return 2

    # SDK debug logging can expose payloads. Restore logging after this manual run.
    previous_logging = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        source = InMemoryImageSource()
        config = AnalyzerConfig(model=MODEL, max_prepared_image_bytes=MAX_PREPARED_IMAGE_BYTES)
        with OpenAI(api_key=key, base_url="https://api.openai.com/v1", max_retries=0) as client:
            service = InspectionService(InMemoryInspectionRepository(), OpenAIPhotoAnalyzer(source, client, config))
            state = service.create_inspection(PropertyDetails("Synthetic smoke property"), "Synthetic smoke renter")
            iid = state.inspection.id
            state = service.add_room(iid, "Synthetic smoke room")
            rid = next(iter(state.rooms))
            state = service.register_photo(iid, rid, filename, media_type)
            pid = next(iter(state.photos))
            source.bind(pid, raw)
            state = service.analyze_photo(iid, pid)  # Exactly one attempt. Never retry.
        print(json.dumps(summary(state), indent=2, ensure_ascii=True))
        return 0 if next(iter(state.analyses.values())).status == AnalysisStatus.SUCCEEDED else 1
    except Exception:
        # Includes client setup/cleanup failures; no raw exception or traceback.
        print("Smoke could not complete.")
        return 1
    finally:
        logging.disable(previous_logging)


if __name__ == "__main__":
    raise SystemExit(main())
