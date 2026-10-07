"""Explicit local analyzer composition; no dotenv loading or inference at startup."""
import logging
import os

from openai import OpenAI

from .domain import AnalysisOutcome, Category, Certainty, Surface
from .images import InMemoryImageSource
from .inference import AnalysisOutput, FakePhotoAnalyzer, PhotoAnalyzer, ProposedFinding
from .openai_analyzer import AnalyzerConfig, OpenAIPhotoAnalyzer

PREPARED_IMAGE_LIMIT = 20971520
TIMEOUT_SECONDS = 90.0


def compose_analyzer(source: InMemoryImageSource) -> tuple[PhotoAnalyzer, OpenAI | None]:
    """Return analyzer and an owned client (closed by the app lifespan).

    Explicitly injected analyzers bypass environment composition entirely.
    Never put credentials in config objects, diagnostics, or provenance.
    """
    mode = os.environ.get("ROOMPROOF_ANALYZER", "fake")
    if mode == "fake":
        return FakePhotoAnalyzer(AnalysisOutput(
            AnalysisOutcome.FINDINGS_PRESENT,
            (ProposedFinding(Category.SCRATCH, Surface.WALL, "center",
                             "Synthetic example scratch; no image was inspected", Certainty.CLEAR),),
            ("Fake analyzer: no image bytes were inspected.",),
        )), None
    if mode != "openai":
        raise RuntimeError("ROOMPROOF_ANALYZER must be fake or openai")

    key = os.environ.get("OPENAI_API_KEY", "").strip()
    model = os.environ.get("ROOMPROOF_OPENAI_MODEL", "").strip()
    if not key or not model:
        raise RuntimeError("OpenAI mode requires OPENAI_API_KEY and ROOMPROOF_OPENAI_MODEL")

    # SDK debug logs can contain image payloads. Suppress provider/transport
    # diagnostics, without suppressing application or server logs.
    namespaces = ("openai", "httpx", "httpx2", "httpcore")
    for name in set(namespaces) | set(logging.root.manager.loggerDict):
        if any(name == root or name.startswith(root + ".") for root in namespaces):
            logger = logging.getLogger(name)
            logger.setLevel(logging.CRITICAL + 1)
            logger.disabled = True
    try:
        client = OpenAI(api_key=key, base_url="https://api.openai.com/v1",
                        timeout=TIMEOUT_SECONDS, max_retries=0)
    except Exception:
        raise RuntimeError("Unable to initialize OpenAI analyzer") from None
    config = AnalyzerConfig(model, TIMEOUT_SECONDS, PREPARED_IMAGE_LIMIT)
    return OpenAIPhotoAnalyzer(source, client, config), client
