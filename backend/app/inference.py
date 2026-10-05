"""Provider-neutral analysis values and an explicitly configured fake, not AI."""
from dataclasses import dataclass
from typing import Protocol

from .domain import (AnalysisOutcome, AnalysisProvenance, Category, Certainty, FailureCode,
                     InvalidDomainData, Photo, Surface)


class AnalyzerContractError(InvalidDomainData):
    """Analyzer output violates the contract, including during construction.

    Adapters translate output parsing/shape errors into this exception; execution
    failures must not be wrapped in it. Diagnostic text is never persisted.
    """

    def __init__(self, message: str = "Invalid analyzer response", *, provenance=None):
        self.provenance = _safe_provenance(provenance)
        super().__init__("Invalid analyzer response")


def _safe_provenance(value):
    try:
        return value.validated() if type(value) is AnalysisProvenance else None
    except (InvalidDomainData, AttributeError, TypeError):
        return None


@dataclass(frozen=True)
class ProposedFinding:
    category: Category
    surface: Surface
    location: str
    description: str
    certainty: Certainty


@dataclass(frozen=True)
class AnalysisOutput:
    outcome: AnalysisOutcome
    findings: tuple[ProposedFinding, ...] = ()
    limitations: tuple[str, ...] = ()

    def __post_init__(self):
        if not isinstance(self.outcome, AnalysisOutcome):
            raise AnalyzerContractError("invalid analysis outcome")
        for name, expected in (("findings", ProposedFinding), ("limitations", str)):
            values = getattr(self, name)
            if not isinstance(values, (tuple, list)):
                raise AnalyzerContractError(f"{name} must be a list or tuple")
            if any(type(value) is not expected for value in values):
                raise AnalyzerContractError(f"invalid {name} member")
            object.__setattr__(self, name, tuple(values))
        if self.outcome == AnalysisOutcome.NO_VISIBLE_FINDINGS and self.findings:
            raise AnalyzerContractError("empty outcome cannot contain findings")
        if self.outcome == AnalysisOutcome.FINDINGS_PRESENT and not self.findings:
            raise AnalyzerContractError("findings outcome requires findings")


class AnalyzerFailure(Exception):
    """Only a safe failure code crosses into stored workflow state."""
    def __init__(self, code: FailureCode, *, provenance=None):
        if not isinstance(code, FailureCode):
            raise InvalidDomainData("invalid analyzer failure code")
        self.provenance = _safe_provenance(provenance)
        self.code = code
        super().__init__(code.value)


@dataclass(frozen=True)
class AnalyzerExecution:
    output: AnalysisOutput
    provenance: AnalysisProvenance

    def __post_init__(self):
        if type(self.output) is not AnalysisOutput or type(self.provenance) is not AnalysisProvenance:
            raise AnalyzerContractError()
        try:
            object.__setattr__(self, "provenance", self.provenance.validated())
        except InvalidDomainData:
            raise AnalyzerContractError() from None


class PhotoAnalyzer(Protocol):
    analyzer_id: str
    analyzer_version: str

    @property
    def configured_provenance(self) -> AnalysisProvenance: ...

    def analyze(self, photo: Photo) -> AnalyzerExecution: ...


@dataclass(frozen=True)
class FakePhotoAnalyzer:
    """Returns the configured scenario regardless of filename or photo metadata."""
    scenario: AnalysisOutput | FailureCode
    analyzer_id: str = "fake"
    analyzer_version: str = "1"

    def __post_init__(self):
        if not isinstance(self.scenario, (AnalysisOutput, FailureCode)):
            raise InvalidDomainData("fake requires an output or failure code")

    @property
    def configured_provenance(self) -> AnalysisProvenance:
        return AnalysisProvenance(self.analyzer_id, self.analyzer_version)

    def analyze(self, photo: Photo) -> AnalyzerExecution:
        if isinstance(self.scenario, FailureCode):
            raise AnalyzerFailure(self.scenario, provenance=self.configured_provenance)
        return AnalyzerExecution(self.scenario, self.configured_provenance)
