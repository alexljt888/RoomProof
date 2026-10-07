"""Offline runtime-to-HTTP integration with the real SDK and synthetic pixels."""
import base64
import json
import os
import socket
import unittest
from unittest.mock import patch
from uuid import UUID

import httpx2
from fastapi.testclient import TestClient
from openai import OpenAI

from backend.app.images import prepare_image
from backend.app.inference import FakePhotoAnalyzer
from backend.app.main import create_app
from backend.app.openai_analyzer import OpenAIPhotoAnalyzer
from test_openai_analyzer import image_bytes, payload


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {}, clear=True)
        env.start(); self.addCleanup(env.stop)
        self.guards = []
        for owner, name in ((socket, 'getaddrinfo'), (socket.socket, 'connect'),
                            (socket.socket, 'connect_ex')):
            guard = patch.object(owner, name, side_effect=AssertionError('network forbidden'))
            self.guards.append(guard.start()); self.addCleanup(guard.stop)

    def tearDown(self):
        for guard in self.guards:
            guard.assert_not_called()

    def configure(self):
        os.environ.update(ROOMPROOF_ANALYZER='openai', OPENAI_API_KEY='synthetic-placeholder',
                          ROOMPROOF_OPENAI_MODEL='gpt-6-luna')

    def envelope(self, variant='success'):
        text = json.dumps(payload()) if variant != 'malformed' else '{broken'
        content = [{'type': 'output_text', 'text': text, 'annotations': []}]
        if variant == 'refused':
            content = [{'type': 'refusal', 'refusal': 'synthetic refusal'}]
        return {'id': 'resp_synthetic', 'object': 'response', 'created_at': 0,
                'status': 'incomplete' if variant == 'incomplete' else 'completed',
                'model': 'gpt-6-luna', 'output': [{'id': 'msg_synthetic', 'type': 'message',
                    'role': 'assistant', 'status': 'completed', 'content': content}],
                'parallel_tool_calls': False, 'tools': [], 'tool_choice': 'auto'}

    def composed(self, variant='success'):
        self.configure()
        self.requests = []
        def respond(request):
            self.requests.append(request)
            return httpx2.Response(500 if variant == 'unavailable' else 200,
                                   json=self.envelope(variant))
        # No HTTP transport can escape to DNS/socket; actual SDK parsing is used.
        client = OpenAI(api_key='synthetic-placeholder', base_url='https://example.invalid/v1',
                        max_retries=0, http_client=httpx2.Client(
                            transport=httpx2.MockTransport(respond), trust_env=False))
        self.addCleanup(client.close)
        with patch('backend.app.runtime.OpenAI', return_value=client) as factory:
            app = create_app()
        factory.assert_called_once_with(api_key='synthetic-placeholder',
            base_url='https://api.openai.com/v1', timeout=90.0, max_retries=0)
        self.assertEqual(self.requests, [])  # constructing an app never analyzes
        return app, client

    def upload(self, client, fmt='PNG'):
        state = client.post('/inspections', json={
            'property_details': {'address': 'Synthetic'}, 'renter_name': 'Example'}).json()
        iid = state['id']
        state = client.post(f'/inspections/{iid}/rooms', json={'name': 'Room'}).json()
        rid = state['rooms'][0]['id']
        state = client.post(f'/inspections/{iid}/rooms/{rid}/photos', json={
            'original_filename': 'synthetic.png', 'declared_media_type': 'image/png'}).json()
        pid = state['photos'][0]['id']
        raw = image_bytes(fmt=fmt)
        self.assertEqual(client.put(f'/inspections/{iid}/photos/{pid}/content', content=raw).status_code, 204)
        return iid, pid, raw

    def test_default_and_explicit_fake_never_construct_client(self):
        for mode in (None, 'fake'):
            if mode:
                os.environ['ROOMPROOF_ANALYZER'] = mode
            with patch('backend.app.runtime.OpenAI') as factory, TestClient(create_app()) as http:
                self.assertIsInstance(http.app.state.inspection_service.analyzer, FakePhotoAnalyzer)
                iid, pid, _ = self.upload(http)
                result = http.post(f'/inspections/{iid}/photos/{pid}/analyses').json()
                self.assertEqual(result['analyses'][0]['analyzer_id'], 'fake')
                self.assertFalse(result['findings'][0]['eligible_for_report'])
                factory.assert_not_called()

    def test_invalid_mode_and_missing_configuration_fail_before_client(self):
        for changes in ({'ROOMPROOF_ANALYZER': 'synthetic-invalid'},
                        {'OPENAI_API_KEY': ''}, {'OPENAI_API_KEY': '  '},
                        {'ROOMPROOF_OPENAI_MODEL': ''}, {'ROOMPROOF_OPENAI_MODEL': '  '}):
            self.configure(); os.environ.update(changes)
            with patch('backend.app.runtime.OpenAI') as factory:
                with self.assertRaises(RuntimeError) as raised:
                    create_app()
                self.assertNotIn('synthetic-placeholder', str(raised.exception))
                self.assertNotIn('synthetic-invalid', str(raised.exception))
                factory.assert_not_called()

    def test_constructor_failure_is_sanitized(self):
        self.configure()
        with patch('backend.app.runtime.OpenAI', side_effect=ValueError('synthetic-placeholder')):
            with self.assertRaisesRegex(RuntimeError, '^Unable to initialize OpenAI analyzer$'):
                create_app()

    def test_shared_source_sdk_pixels_provenance_and_review(self):
        for fmt, action in (('JPEG', 'confirm'), ('PNG', 'edit_and_confirm'), ('PNG', 'reject')):
            with self.subTest(fmt=fmt, action=action):
                app, sdk = self.composed()
                adapter = app.state.inspection_service.analyzer
                self.assertIsInstance(adapter, OpenAIPhotoAnalyzer)
                self.assertIs(adapter.image_source, app.state.image_source)
                self.assertEqual(adapter.config.max_prepared_image_bytes, 20971520)
                self.assertEqual(adapter.config.model, 'gpt-6-luna')
                self.assertEqual(adapter.config.timeout_seconds, 90)
                self.assertNotIn('synthetic-placeholder', repr(adapter))
                with TestClient(app) as http:
                    iid, pid, raw = self.upload(http, fmt)
                    self.assertEqual(adapter.image_source.read(UUID(pid)), raw)
                    response = http.post(f'/inspections/{iid}/photos/{pid}/analyses')
                    self.assertEqual(response.status_code, 200)
                    state = response.json(); analysis = state['analyses'][0]
                    self.assertEqual(analysis['status'], 'succeeded')
                    self.assertEqual(analysis['analyzer_id'], 'openai-photo')
                    self.assertEqual(analysis['provenance'], {
                        'requested_model': 'gpt-6-luna', 'provider_model': 'gpt-6-luna',
                        'prompt_version': 'roomproof-observations-v1',
                        'schema_version': 'roomproof-observations-v1', 'preparation_version': 'rgb-png-v1'})
                    self.assertNotIn('sha256', response.text)
                    self.assertNotIn('synthetic-placeholder', response.text)
                    finding = state['findings'][0]
                    self.assertEqual(finding['state'], 'pending_review')
                    self.assertFalse(finding['eligible_for_report'])
                    self.assertEqual(finding['original_proposal']['evidence_photo_ids'], [pid])
                    review = {'action': action}
                    if action != 'reject':
                        review['reportable'] = True
                    if action == 'edit_and_confirm':
                        review.update(category='scuff', surface='wall', location='lower left',
                                      description='Human observation', evidence_photo_ids=[pid])
                    reviewed = http.post(f"/inspections/{iid}/findings/{finding['id']}/review", json=review)
                    self.assertEqual(reviewed.status_code, 200)
                    final = reviewed.json()['findings'][0]
                    self.assertEqual(final['original_proposal'], finding['original_proposal'])
                    self.assertEqual(final['eligible_for_report'], action != 'reject')
                    self.assertEqual(final['state'], 'rejected' if action == 'reject' else 'confirmed')
                self.assertTrue(sdk.is_closed())
                self.assertEqual(len(self.requests), 1)
                body = json.loads(self.requests[0].content)
                self.assertEqual(body['model'], 'gpt-6-luna')
                self.assertFalse(body['store'])
                self.assertNotIn('max_output_tokens', body)
                self.assertNotIn('synthetic.png', str(body))
                image = body['input'][0]['content'][0]
                self.assertEqual(image['detail'], 'high')
                self.assertEqual(base64.b64decode(image['image_url'].split(',')[1]), prepare_image(raw).encoded_bytes)
                self.assertEqual(set(self.requests[0].extensions['timeout'].values()), {90.0})

    def test_failures_are_safe_and_never_retry(self):
        for variant in ('unavailable', 'malformed', 'refused', 'incomplete'):
            with self.subTest(variant=variant):
                app, _ = self.composed(variant)
                with TestClient(app) as http:
                    iid, pid, _ = self.upload(http)
                    response = http.post(f'/inspections/{iid}/photos/{pid}/analyses')
                    self.assertEqual(response.status_code, 200)
                    state = response.json()
                    self.assertEqual(state['analyses'][0]['status'], 'failed')
                    self.assertEqual(state['analyses'][0]['failure_code'],
                                     'unavailable' if variant == 'unavailable' else 'invalid_response')
                    self.assertEqual(state['findings'], [])
                    self.assertNotIn('synthetic refusal', response.text)
                    self.assertNotIn('broken', response.text)
                self.assertEqual(len(self.requests), 1)

    def test_explicit_injection_bypasses_environment_and_retains_client_ownership(self):
        app, sdk = self.composed()
        adapter = app.state.inspection_service.analyzer
        os.environ['ROOMPROOF_ANALYZER'] = 'invalid'
        with patch('backend.app.runtime.OpenAI') as factory, TestClient(create_app(analyzer=adapter)):
            factory.assert_not_called()
        self.assertFalse(sdk.is_closed())
