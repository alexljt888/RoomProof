"""One offline compatibility regression against the pinned SDK, never a live API."""
import base64
import json
import socket
import unittest
from unittest.mock import patch

import httpx2
from openai import OpenAI

from backend.app.domain import FailureCode, Inspection, Photo, PropertyDetails, Room
from backend.app.images import InMemoryImageSource, prepare_image
from backend.app.inference import AnalyzerExecution, AnalyzerFailure
from backend.app.openai_analyzer import AnalyzerConfig, OpenAIPhotoAnalyzer, PROMPT, SCHEMA_SHA256
from test_openai_analyzer import image_bytes, payload


class SDKCompatibilityTests(unittest.TestCase):
    def setUp(self):
        # Guard the resolver too: DNS precedes socket.connect in a real transport.
        self.network_guards = {}
        for owner, name in ((socket, 'getaddrinfo'), (socket.socket, 'connect'),
                            (socket.socket, 'connect_ex')):
            guard = patch.object(owner, name, side_effect=AssertionError('network forbidden'))
            self.network_guards[name] = guard.start()
            self.addCleanup(guard.stop)

    def test_guard_blocks_unmocked_transport_before_dns(self):
        # Deliberately omit MockTransport to prove a setup regression fails closed.
        with httpx2.Client(trust_env=False, timeout=1) as client:
            with self.assertRaisesRegex(AssertionError, 'network forbidden'):
                client.get('https://example.invalid')
        self.network_guards['getaddrinfo'].assert_called_once()
        self.network_guards['connect'].assert_not_called()
        self.network_guards['connect_ex'].assert_not_called()

    def test_structured_success_and_retry_override(self):
        photo = Photo(Room(Inspection(PropertyDetails('Example'), 'Renter'), 'Room'), 'a.png', 'image/png')
        raw = image_bytes()
        prepared = prepare_image(raw)
        source = InMemoryImageSource()
        source.bind(photo.id, raw)
        for status in (200, 500):
            with self.subTest(status=status):
                requests = []
                def respond(request):
                    requests.append(request)
                    return httpx2.Response(status, json={
                        'id': 'resp_synthetic', 'object': 'response', 'created_at': 0,
                        'status': 'completed', 'model': 'synthetic-model',
                        'output': [{'id': 'msg_synthetic', 'type': 'message', 'role': 'assistant',
                                    'status': 'completed', 'content': [{'type': 'output_text',
                                    'text': json.dumps(payload()), 'annotations': []}]}],
                        'parallel_tool_calls': False, 'tools': [], 'tool_choice': 'auto',
                    })
                with OpenAI(api_key='synthetic-placeholder', base_url='https://example.invalid/v1',
                            max_retries=3, http_client=httpx2.Client(transport=httpx2.MockTransport(respond))) as client:
                    adapter = OpenAIPhotoAnalyzer(source, client, AnalyzerConfig('requested-model', 12,
                                                                                 len(prepared.encoded_bytes)))
                    if status == 200:
                        execution = adapter.analyze(photo)
                        self.assertIsInstance(execution, AnalyzerExecution)
                        self.assertEqual(execution.provenance.provider_model, 'synthetic-model')
                        self.assertEqual(execution.provenance.prepared_sha256, prepared.prepared_sha256)
                        self.assertEqual(execution.provenance.schema_sha256, SCHEMA_SHA256)
                        self.assertEqual(len(execution.output.findings), 1)
                    else:
                        with self.assertRaises(AnalyzerFailure) as raised:
                            adapter.analyze(photo)
                        self.assertEqual(raised.exception.code, FailureCode.UNAVAILABLE)
                    self.assertEqual(client.max_retries, 3)
                self.assertEqual(len(requests), 1)
                request = requests[0]
                body = json.loads(request.content)
                self.assertEqual(request.url.path, '/v1/responses')
                self.assertEqual(body['instructions'], PROMPT)
                self.assertEqual(body['model'], 'requested-model')
                self.assertFalse(body['store'])
                self.assertEqual(body['text']['format']['type'], 'json_schema')
                self.assertTrue(body['text']['format']['strict'])
                self.assertIn('findings', body['text']['format']['schema']['properties'])
                image = body['input'][0]['content'][0]
                self.assertEqual(image['type'], 'input_image')
                self.assertEqual(base64.b64decode(image['image_url'].split(',', 1)[1]), prepared.encoded_bytes)
                self.assertEqual(set(request.extensions['timeout'].values()), {12})

        for guard in self.network_guards.values():
            guard.assert_not_called()
