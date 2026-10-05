"""Offline adapter tests: injected stubs, synthetic memory images, no credentials."""
import base64
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
import hashlib
from io import BytesIO
import json
from threading import Barrier
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx2
from openai import (APITimeoutError, APIConnectionError, RateLimitError,
                    AuthenticationError, APIResponseValidationError)
from PIL import Image

from backend.app.domain import (AnalysisOutcome, Category, Certainty, FailureCode,
                                Inspection, Photo, PropertyDetails, Room, Surface)
from backend.app.images import InMemoryImageSource, prepare_image
from backend.app.inference import AnalyzerContractError, AnalyzerFailure
from backend.app.openai_analyzer import (AnalyzerConfig, OpenAIPhotoAnalyzer,
    ProviderResult, PROMPT, PROMPT_SHA256, SCHEMA_SHA256, PROMPT_VERSION, SCHEMA_VERSION)


def image_bytes(color="red", fmt="PNG"):
    with Image.new("RGB", (4, 3), color) as image, BytesIO() as buffer:
        image.save(buffer, format=fmt)
        return buffer.getvalue()


def finding(**changes):
    value = dict(category="scratch", surface="wall", location="lower left",
                 description="Visible linear mark", certainty="clear")
    value.update(changes)
    return value


def payload(outcome="findings_present", findings=None, limitations=None):
    return dict(outcome=outcome, findings=[finding()] if findings is None else findings,
                limitations=[] if limitations is None else limitations)


def response(data=None, **changes):
    value = dict(status="completed", model="synthetic-reported-model", output=[],
                 output_parsed=ProviderResult.model_validate(data or payload()))
    value.update(changes)
    return SimpleNamespace(**value)


class StubClient:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []
        self.options = []
        self.responses = self

    def with_options(self, **options):
        self.options.append(options)
        return self

    def parse(self, **request):
        self.calls.append(request)
        if self.error:
            raise self.error
        return self.result


class OpenAIAnalyzerTests(unittest.TestCase):
    def setUp(self):
        inspection = Inspection(PropertyDetails("Private synthetic address"), "Private synthetic renter")
        self.room = Room(inspection, "Private room")
        self.photo = Photo(self.room, "private-filename.jpg", "image/jpeg")
        self.raw = image_bytes()
        self.source = InMemoryImageSource()
        self.source.bind(self.photo.id, self.raw)
        self.client = StubClient(response())
        self.adapter = OpenAIPhotoAnalyzer(self.source, self.client, AnalyzerConfig("explicit-test-model", 12))

    def test_request_uses_prepared_pixels_and_no_private_metadata(self):
        result = self.adapter.analyze(self.photo).output
        self.assertEqual(result.outcome, AnalysisOutcome.FINDINGS_PRESENT)
        self.assertEqual(len(self.client.calls), 1)
        request = self.client.calls[0]
        self.assertEqual(request['model'], 'explicit-test-model')
        self.assertEqual(request['instructions'], PROMPT)
        self.assertIs(request['text_format'], ProviderResult)
        self.assertFalse(request['store'])
        self.assertEqual(self.client.options, [dict(timeout=12, max_retries=0)])
        content = request['input'][0]['content']
        self.assertEqual(len(content), 1)
        self.assertEqual(content[0]['type'], 'input_image')
        self.assertEqual(content[0]['detail'], 'high')
        self.assertEqual(base64.b64decode(content[0]['image_url'].split(',', 1)[1]),
                         prepare_image(self.raw).encoded_bytes)
        for private in ('Private synthetic', 'Private room', 'private-filename', str(self.photo.id), '/Users/', '/home/'):
            self.assertNotIn(private, str(request))
        self.assertEqual(set(request), {'model', 'instructions', 'input', 'text_format', 'store'})

    def test_all_vocabulary_and_multiple_findings_translate(self):
        findings = [finding(category=c.value, surface=s.value,
                            certainty='clear' if i % 2 == 0 else 'possible')
                    for i, c in enumerate(Category) for s in Surface]
        self.client.result = response(payload(findings=findings, limitations=['Glare']))
        out = self.adapter.analyze(self.photo).output
        self.assertEqual(len(out.findings), 40)
        self.assertEqual({f.category for f in out.findings}, set(Category))
        self.assertEqual({f.surface for f in out.findings}, set(Surface))
        self.assertEqual({f.certainty for f in out.findings}, set(Certainty))
        self.assertEqual(out.limitations, ('Glare',))
        for original, translated in zip(findings, out.findings):
            self.assertEqual(translated.category.value, original['category'])
            self.assertEqual(translated.surface.value, original['surface'])
            self.assertEqual(translated.location, original['location'])
            self.assertEqual(translated.description, original['description'])

    def test_empty_and_uncertain_results(self):
        for outcome, findings in [('no_visible_findings', []), ('uncertain', []),
                                  ('uncertain', [finding(certainty='possible')])]:
            self.client.result = response(payload(outcome, findings))
            out = self.adapter.analyze(self.photo).output
            self.assertEqual(out.outcome.value, outcome)
            self.assertEqual(len(out.findings), len(findings))

    def test_contract_inconsistencies_and_unknown_fields(self):
        invalid = [payload(findings=[]), payload(findings=[finding(certainty='possible')]),
                   payload('no_visible_findings', [finding()]), payload('uncertain', [finding()]),
                   payload(findings=[finding(category='dent')]), payload(findings=[finding(surface='ceiling')]),
                   payload(findings=[finding(location=' ')]), payload(findings=[finding(description='')]),
                   payload(limitations=[' ']), payload(findings=[finding(certainty='certain')]),
                   dict(payload(), reportable=True), payload(findings=[finding(approved=True)]),
                   dict(outcome='unknown', findings=[], limitations=[]), {'malformed': True}]
        for data in invalid:
            with self.subTest(data=data):
                # SDK parse executes Pydantic validation inside the request call.
                class ParsingStub(StubClient):
                    def parse(self, **request):
                        self.calls.append(request)
                        return response(data)
                client = ParsingStub()
                adapter = OpenAIPhotoAnalyzer(self.source, client, self.adapter.config)
                with self.assertRaises(AnalyzerContractError) as raised:
                    adapter.analyze(self.photo)
                self.assertEqual(str(raised.exception), 'Invalid analyzer response')
                self.assertEqual(len(client.calls), 1)

    def test_constructed_invalid_model_revalidated(self):
        self.client.result = response(output_parsed=ProviderResult.model_construct(
            outcome='findings_present', findings=[], limitations=[]))
        with self.assertRaises(AnalyzerContractError):
            self.adapter.analyze(self.photo)

    def test_missing_refused_incomplete_and_malformed_envelopes(self):
        for result in (response(output_parsed=None), response(output_parsed=payload()),
                       response(status='incomplete'), response(status='failed'),
                       response(output=[SimpleNamespace(content=[SimpleNamespace(type='refusal')])]),
                       SimpleNamespace(), response(model=123)):
            self.client.result = result
            with self.assertRaises(AnalyzerContractError):
                self.adapter.analyze(self.photo)

    def test_image_failures_never_invoke_provider(self):
        for raw in (None, b'private corrupt bytes', image_bytes(fmt='GIF')):
            photo = Photo(self.room, 'another.png', 'image/png')
            if raw is not None:
                self.source.bind(photo.id, raw)
            with self.assertRaises(AnalyzerFailure) as raised:
                self.adapter.analyze(photo)
            self.assertEqual(raised.exception.code, FailureCode.UNREADABLE_IMAGE)
            self.assertEqual(str(raised.exception), 'unreadable_image')
        with patch('backend.app.images.MAX_PIXELS', 1):
            with self.assertRaises(AnalyzerFailure) as raised:
                self.adapter.analyze(self.photo)
            self.assertEqual(raised.exception.code, FailureCode.UNREADABLE_IMAGE)
        self.assertEqual(self.client.calls, [])
        self.assertEqual(self.client.options, [])

    def test_provider_failures_safe_single_attempt(self):
        request = httpx2.Request('POST', 'https://example.invalid/responses')
        for error in (APITimeoutError(request=request), APIConnectionError(request=request),
                      RateLimitError('private diagnostic', response=httpx2.Response(429, request=request), body=None),
                      AuthenticationError('private diagnostic', response=httpx2.Response(401, request=request), body=None),
                      RuntimeError('private diagnostic')):
            client = StubClient(error=error)
            adapter = OpenAIPhotoAnalyzer(self.source, client, self.adapter.config)
            with self.assertRaises(AnalyzerFailure) as raised:
                adapter.analyze(self.photo)
            self.assertEqual(raised.exception.code, FailureCode.UNAVAILABLE)
            self.assertEqual(str(raised.exception), 'unavailable')
            self.assertTrue(raised.exception.__suppress_context__)
            self.assertEqual(len(client.calls), 1)
            self.assertEqual(client.options[0]['max_retries'], 0)

    def test_sdk_parse_errors_are_contract_failures(self):
        request = httpx2.Request('POST', 'https://example.invalid/responses')
        errors = [json.JSONDecodeError('private detail', 'private body', 0),
                  APIResponseValidationError(response=httpx2.Response(200, request=request), body='private')]
        for error in errors:
            self.client.error = error
            with self.assertRaises(AnalyzerContractError):
                self.adapter.analyze(self.photo)

    def test_provider_contract_error_keeps_classification_and_hides_details(self):
        self.client.error = AnalyzerContractError('synthetic private provider detail')
        with self.assertRaises(AnalyzerContractError) as raised:
            self.adapter.analyze(self.photo)
        self.assertEqual(str(raised.exception), 'Invalid analyzer response')
        self.assertTrue(raised.exception.__suppress_context__)
        self.assertEqual(len(self.client.calls), 1)

    def test_metadata_hashes_and_immutability(self):
        execution = self.adapter.analyze(self.photo)
        meta = execution.provenance
        prepared = prepare_image(self.raw)
        self.assertEqual(meta.requested_model, 'explicit-test-model')
        self.assertEqual(meta.provider_model, 'synthetic-reported-model')
        self.assertEqual(meta.analyzer_id, self.adapter.analyzer_id)
        self.assertEqual(meta.analyzer_version, self.adapter.analyzer_version)
        self.assertEqual(meta.prompt_version, PROMPT_VERSION)
        self.assertEqual(meta.schema_version, SCHEMA_VERSION)
        self.assertEqual(meta.prompt_sha256, hashlib.sha256(PROMPT.encode()).hexdigest())
        self.assertEqual(meta.prompt_sha256, PROMPT_SHA256)
        schema = json.dumps(ProviderResult.model_json_schema(), sort_keys=True, separators=(',', ':'), ensure_ascii=False)
        self.assertEqual(meta.schema_sha256, hashlib.sha256(schema.encode()).hexdigest())
        self.assertEqual(meta.schema_sha256, SCHEMA_SHA256)
        self.assertEqual(meta.original_sha256, prepared.original_sha256)
        self.assertEqual(meta.prepared_sha256, prepared.prepared_sha256)
        self.assertEqual(meta.preparation_version, prepared.preparation_version)
        self.assertEqual(meta, self.adapter.analyze(self.photo).provenance)
        with self.assertRaises(FrozenInstanceError):
            meta.requested_model = 'changed'
        self.assertNotIn(repr(self.raw), repr(execution))
        self.assertNotIn('image_source=', repr(self.adapter))
        self.assertNotIn('client=', repr(self.adapter))

    def test_provider_model_may_be_absent(self):
        self.client.result = response(model=None)
        self.assertIsNone(self.adapter.analyze(self.photo).provenance.provider_model)
        del self.client.result.model
        self.assertIsNone(self.adapter.analyze(self.photo).provenance.provider_model)

    def test_concurrent_execution_metadata_is_call_local(self):
        barrier = Barrier(2)
        class ConcurrentStub:
            def with_options(self, **options):
                return self
            @property
            def responses(self):
                return self
            def parse(self, **request):
                barrier.wait(timeout=3)
                data = base64.b64decode(request['input'][0]['content'][0]['image_url'].split(',', 1)[1])
                return response(model=hashlib.sha256(data).hexdigest())
        second = Photo(self.room, 'second.png', 'image/png')
        second_raw = image_bytes('blue')
        self.source.bind(second.id, second_raw)
        adapter = OpenAIPhotoAnalyzer(self.source, ConcurrentStub(), self.adapter.config)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(adapter.analyze, (self.photo, second)))
        for execution, raw in zip(results, (self.raw, second_raw)):
            self.assertEqual(execution.provenance.original_sha256, hashlib.sha256(raw).hexdigest())
            self.assertEqual(execution.provenance.provider_model, execution.provenance.prepared_sha256)
        self.assertNotEqual(results[0].provenance.original_sha256, results[1].provenance.original_sha256)

    def test_configuration_requires_model_and_finite_timeout(self):
        for model in ('', ' ', None):
            with self.assertRaises(ValueError):
                AnalyzerConfig(model)
        for timeout in (0, -1, float('nan'), float('inf'), True, '12'):
            with self.assertRaises(ValueError):
                AnalyzerConfig('explicit', timeout)
        with self.assertRaises(FrozenInstanceError):
            self.adapter.config.model = 'changed'

    def test_size_bound_before_encoding_retains_preparation(self):
        from dataclasses import replace
        prepared = prepare_image(self.raw)
        for bound in (len(prepared.encoded_bytes), len(prepared.encoded_bytes) + 1):
            adapter = replace(self.adapter, config=replace(self.adapter.config, max_prepared_image_bytes=bound))
            self.assertEqual(adapter.analyze(self.photo).provenance.prepared_sha256, prepared.prepared_sha256)
        client = StubClient(response())
        adapter = replace(self.adapter, client=client,
                          config=replace(self.adapter.config, max_prepared_image_bytes=len(prepared.encoded_bytes) - 1))
        with patch('backend.app.openai_analyzer.base64.b64encode', side_effect=AssertionError('must not encode')):
            with self.assertRaises(AnalyzerFailure) as raised:
                adapter.analyze(self.photo)
        self.assertEqual(raised.exception.code, FailureCode.UNREADABLE_IMAGE)
        self.assertEqual(raised.exception.provenance.prepared_sha256, prepared.prepared_sha256)
        self.assertFalse(client.calls)
        self.assertFalse(client.options)
        for invalid in (0, -1, True, 1.5, '100'):
            with self.assertRaises(ValueError):
                replace(self.adapter.config, max_prepared_image_bytes=invalid)

    def test_failure_provenance_by_stage(self):
        missing = Photo(self.room, 'missing.png', 'image/png')
        with self.assertRaises(AnalyzerFailure) as raised:
            self.adapter.analyze(missing)
        self.assertEqual(raised.exception.provenance, self.adapter.configured_provenance)
        for error, expected in ((RuntimeError('private'), AnalyzerFailure),
                                (AnalyzerContractError('private'), AnalyzerContractError)):
            self.client.error = error
            with self.assertRaises(expected) as raised:
                self.adapter.analyze(self.photo)
            self.assertEqual(raised.exception.provenance.prepared_sha256, prepare_image(self.raw).prepared_sha256)
            self.assertIsNone(raised.exception.provenance.provider_model)
