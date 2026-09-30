"""Provider-neutral analysis values and an explicitly configured fake, not AI."""
from dataclasses import dataclass
from typing import Protocol

from .domain import (AnalysisOutcome, Category, Certainty, FailureCode,
                     InvalidDomainData, Photo, Surface)


class AnalyzerContractError(InvalidDomainData):
    """Analyzer output violates the contract, including during construction.

    Adapters translate output parsing/shape errors into this exception; execution
    failures must not be wrapped in it. Diagnostic text is never persisted.
    """


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
    def __init__(self, code: FailureCode):
        if not isinstance(code, FailureCode):
            raise InvalidDomainData("invalid analyzer failure code")
        self.code = code
        super().__init__(code.value)


class PhotoAnalyzer(Protocol):
    analyzer_id: str
    analyzer_version: str

    def analyze(self, photo: Photo) -> AnalysisOutput: ...


@dataclass(frozen=True)
class FakePhotoAnalyzer:
    """Returns the configured scenario regardless of filename or photo metadata."""
    scenario: AnalysisOutput | FailureCode
    analyzer_id: str = "fake"
    analyzer_version: str = "1"

    def __post_init__(self):
        if not isinstance(self.scenario, (AnalysisOutput, FailureCode)):
            raise InvalidDomainData("fake requires an output or failure code")

    def analyze(self, photo: Photo) -> AnalysisOutput:
        if isinstance(self.scenario, FailureCode):
            raise AnalyzerFailure(self.scenario)
        return self.scenario
