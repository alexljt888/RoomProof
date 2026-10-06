"""Offline HTTP workflow tests: TestClient runs the app in process."""
from datetime import datetime
import unittest
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from backend.app.domain import AnalysisOutcome, AnalysisProvenance, FailureCode
from backend.app.inference import AnalyzerExecution, AnalysisOutput, FakePhotoAnalyzer
from backend.app.main import create_app


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app())
        self.addCleanup(self.client.close)

    def create(self, client=None):
        client = client or self.client
        response = client.post('/inspections', json={
            'property_details': {'address': 'Example address', 'unit': 'A'},
            'renter_name': 'Example renter',
        })
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def setup_photo(self, client=None):
        client = client or self.client
        iid = self.create(client)['id']
        response = client.post(f'/inspections/{iid}/rooms', json={'name': 'Living room'})
        self.assertEqual(response.status_code, 201, response.text)
        rid = response.json()['rooms'][0]['id']
        response = client.post(f'/inspections/{iid}/rooms/{rid}/photos', json={
            'original_filename': 'example.jpg', 'declared_media_type': 'image/jpeg'})
        self.assertEqual(response.status_code, 201, response.text)
        return iid, rid, response.json()['photos'][0]['id']

    def analyze(self, iid, pid, client=None):
        response = (client or self.client).post(f'/inspections/{iid}/photos/{pid}/analyses')
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def review(self, iid, fid, body):
        return self.client.post(f'/inspections/{iid}/findings/{fid}/review', json=body)

    def test_full_http_workflow_replaces_evidence_preserves_proposal(self):
        iid, rid, photo_a = self.setup_photo()
        analyzed = self.analyze(iid, photo_a)
        finding = analyzed['findings'][0]
        original = finding['original_proposal']
        self.assertEqual(finding['state'], 'pending_review')
        self.assertEqual(original['certainty'], 'clear')
        self.assertEqual(original['evidence_photo_ids'], [photo_a])
        self.assertIsNone(finding['review'])
        self.assertFalse(finding['eligible_for_report'])
        response = self.client.post(f'/inspections/{iid}/rooms/{rid}/photos', json={
            'original_filename': 'clearer.jpg', 'declared_media_type': 'image/jpeg'})
        self.assertEqual(response.status_code, 201)
        photo_b = response.json()['photos'][-1]['id']
        response = self.review(iid, finding['id'], {
            'action': 'edit_and_confirm', 'category': 'scuff', 'surface': 'wall',
            'location': 'lower center', 'description': 'Small scuff', 'reportable': True,
            'evidence_photo_ids': [photo_b],
        })
        self.assertEqual(response.status_code, 200, response.text)
        state = self.client.get(f'/inspections/{iid}').json()
        reviewed = state['findings'][0]
        self.assertEqual(reviewed['original_proposal'], original)
        self.assertEqual(reviewed['state'], 'confirmed')
        self.assertTrue(reviewed['eligible_for_report'])
        self.assertEqual(reviewed['review']['action'], 'edit_and_confirm')
        self.assertEqual(reviewed['review']['approved'], {
            'category': 'scuff', 'surface': 'wall', 'location': 'lower center',
            'description': 'Small scuff', 'reportable': True, 'evidence_photo_ids': [photo_b],
        })
        self.assertEqual(reviewed['source_analysis_id'], state['analyses'][0]['id'])
        self.assertEqual(state['analyses'][0]['photo_id'], photo_a)

    def test_create_list_get_and_app_isolation(self):
        self.assertEqual(self.client.get('/inspections').json(), [])
        created = self.create()
        UUID(created['id'])
        self.assertIsNotNone(datetime.fromisoformat(created['created_at']).tzinfo)
        self.assertEqual(self.client.get(f"/inspections/{created['id']}").json(), created)
        summaries = self.client.get('/inspections').json()
        self.assertEqual([s['id'] for s in summaries], [created['id']])
        self.assertNotIn('findings', summaries[0])
        with TestClient(create_app()) as other:
            self.assertEqual(other.get('/inspections').json(), [])
            self.assertEqual(other.get(f"/inspections/{created['id']}").status_code, 404)

    def test_confirm_reportability_and_second_review_conflict(self):
        for reportable in (True, False):
            with self.subTest(reportable=reportable):
                iid, _, pid = self.setup_photo()
                original = self.analyze(iid, pid)['findings'][0]
                response = self.review(iid, original['id'], {'action': 'confirm', 'reportable': reportable})
                self.assertEqual(response.status_code, 200)
                finding = response.json()['findings'][0]
                self.assertEqual(finding['state'], 'confirmed')
                self.assertEqual(finding['eligible_for_report'], reportable)
                approved = finding['review']['approved']
                self.assertEqual(approved['evidence_photo_ids'], [pid])
                self.assertEqual(approved['description'], original['original_proposal']['description'])
                second = self.review(iid, original['id'], {'action': 'reject'})
                self.assert_error(second, 409, 'transition_conflict')

    def test_reject_and_duplicate_analysis(self):
        iid, _, pid = self.setup_photo()
        fid = self.analyze(iid, pid)['findings'][0]['id']
        response = self.review(iid, fid, {'action': 'reject', 'reason': 'Not reportable'})
        self.assertEqual(response.status_code, 200)
        finding = response.json()['findings'][0]
        self.assertEqual(finding['state'], 'rejected')
        self.assertIsNone(finding['review']['approved'])
        self.assertEqual(finding['review']['reason'], 'Not reportable')
        self.assertFalse(finding['eligible_for_report'])
        self.assert_error(self.client.post(f'/inspections/{iid}/photos/{pid}/analyses'),
                          409, 'transition_conflict')

    def test_zero_uncertain_and_failure_are_application_state(self):
        for scenario in (AnalysisOutput(AnalysisOutcome.NO_VISIBLE_FINDINGS),
                         AnalysisOutput(AnalysisOutcome.UNCERTAIN, limitations=('Low visibility',)),
                         FailureCode.UNREADABLE_IMAGE):
            with self.subTest(scenario=scenario), TestClient(create_app(analyzer=FakePhotoAnalyzer(scenario))) as client:
                iid, _, pid = self.setup_photo(client)
                state = self.analyze(iid, pid, client)
                self.assertEqual(state['findings'], [])
                analysis = state['analyses'][0]
                if isinstance(scenario, FailureCode):
                    self.assertEqual(analysis['status'], 'failed')
                    self.assertEqual(analysis['failure_code'], 'unreadable_image')
                    self.assertIsNone(analysis['outcome'])
                    self.assertEqual(len(self.analyze(iid, pid, client)['analyses']), 2)
                else:
                    self.assertEqual(analysis['status'], 'succeeded')
                    self.assertEqual(analysis['outcome'], scenario.outcome.value)
                    self.assertEqual(analysis['limitations'], list(scenario.limitations))
                    self.assertIsNone(analysis['failure_code'])
                self.assertIsNotNone(analysis['completed_at'])

    def test_foreign_room_photo_finding_and_unknown_ids(self):
        iid, rid, pid = self.setup_photo()
        fid = self.analyze(iid, pid)['findings'][0]['id']
        other = self.create()['id']
        responses = (
            self.client.post(f'/inspections/{other}/rooms/{rid}/photos', json={
                'original_filename': 'example.jpg', 'declared_media_type': 'image/jpeg'}),
            self.client.post(f'/inspections/{other}/photos/{pid}/analyses'),
            self.review(other, fid, {'action': 'confirm', 'reportable': True}),
            self.client.get(f'/inspections/{uuid4()}'),
            self.client.post(f'/inspections/{iid}/photos/{uuid4()}/analyses'),
        )
        for response in responses:
            self.assert_error(response, 404, 'not_found')

    def test_invalid_evidence_and_domain_input(self):
        iid, rid, pid = self.setup_photo()
        fid = self.analyze(iid, pid)['findings'][0]['id']
        room = self.client.post(f'/inspections/{iid}/rooms', json={'name': 'Other room'}).json()['rooms'][-1]['id']
        photo = self.client.post(f'/inspections/{iid}/rooms/{room}/photos', json={
            'original_filename': 'other.jpg', 'declared_media_type': 'image/jpeg'}).json()['photos'][-1]['id']
        base = {'action': 'edit_and_confirm', 'category': 'scuff', 'surface': 'wall',
                'location': 'center', 'description': 'Mark', 'reportable': True}
        for evidence, status, code in (([], 422, 'invalid_domain_input'),
                                      ([pid, pid], 422, 'invalid_domain_input'),
                                      ([photo], 422, 'invalid_domain_input'),
                                      ([str(uuid4())], 404, 'not_found')):
            self.assert_error(self.review(iid, fid, dict(base, evidence_photo_ids=evidence)), status, code)
        self.assertEqual(self.client.get(f'/inspections/{iid}').json()['findings'][0]['state'], 'pending_review')
        self.assert_error(self.client.post(f'/inspections/{iid}/rooms', json={'name': ' '}),
                          422, 'invalid_domain_input')
        response = self.client.post(f'/inspections/{iid}/rooms/{rid}/photos', json={
            'original_filename': 'https://example.test/private.jpg', 'declared_media_type': 'image/jpeg'})
        self.assert_error(response, 422, 'invalid_domain_input')
        self.assertNotIn('example.test', response.text)

    def test_edit_omitted_or_null_evidence_retains_original(self):
        for extra in ({}, {'evidence_photo_ids': None}):
            iid, _, pid = self.setup_photo()
            fid = self.analyze(iid, pid)['findings'][0]['id']
            response = self.review(iid, fid, dict(action='edit_and_confirm', category='scuff',
                surface='wall', location='center', description='Small mark', reportable=False, **extra))
            self.assertEqual(response.status_code, 200)
            finding = response.json()['findings'][0]
            self.assertEqual(finding['review']['approved']['evidence_photo_ids'], [pid])
            self.assertFalse(finding['eligible_for_report'])

    def test_malformed_and_direct_state_injection_rejected(self):
        iid, _, pid = self.setup_photo()
        fid = self.analyze(iid, pid)['findings'][0]['id']
        for body in ({'action': 'confirm'}, {'action': 'confirm', 'reportable': 'true'},
                     {'state': 'confirmed'}, {'action': 'reject', 'approved': {}},
                     {'action': 'confirm', 'reportable': True, 'review': {}},
                     {'action': 'edit_and_confirm', 'reportable': True}):
            response = self.review(iid, fid, body)
            self.assertEqual(response.status_code, 422, response.text)
            self.assertIn('detail', response.json())
        self.assertEqual(self.client.post('/inspections', json={}).status_code, 422)
        self.assertEqual(self.client.get('/inspections/not-a-uuid').status_code, 422)
        self.assertEqual(self.client.post('/inspections', json={
            'id': str(uuid4()), 'renter_name': 'Renter', 'property_details': {'address': 'Example'}}).status_code, 422)

    def test_raw_provider_diagnostics_not_exposed(self):
        class Broken:
            analyzer_id = 'broken-test'
            analyzer_version = '1'
            configured_provenance = AnalysisProvenance(analyzer_id, analyzer_version)
            def analyze(self, photo):
                raise RuntimeError('synthetic sensitive diagnostic')
        with TestClient(create_app(analyzer=Broken())) as client:
            iid, _, pid = self.setup_photo(client)
            state = self.analyze(iid, pid, client)
            self.assertEqual(state['analyses'][0]['failure_code'], 'unavailable')
            self.assertNotIn('sensitive diagnostic', str(state))

    def test_response_is_explicit_and_nonrecursive(self):
        iid, _, pid = self.setup_photo()
        state = self.analyze(iid, pid)
        def check(value):
            if isinstance(value, dict):
                self.assertTrue(all(not key.startswith('_') for key in value))
                for child in value.values():
                    check(child)
            elif isinstance(value, list):
                for child in value:
                    check(child)
        check(state)
        self.assertEqual(set(state), {'id', 'created_at', 'property_details', 'renter_name',
                                     'rooms', 'photos', 'analyses', 'findings'})
        self.assertNotIn('source_analysis', state['findings'][0])
        self.assertNotIn('Photo(', str(state))
        self.assertNotIn('Inspection(', str(state))

    def assert_error(self, response, status, code):
        self.assertEqual(response.status_code, status, response.text)
        self.assertEqual(set(response.json()), {'error'})
        self.assertEqual(set(response.json()['error']), {'code', 'message'})
        self.assertEqual(response.json()['error']['code'], code)


    def test_pending_analysis_response_and_conflict(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        started, release = Event(), Event()
        class Blocking:
            analyzer_id = 'blocking-fake'
            analyzer_version = '1'
            configured_provenance = AnalysisProvenance(analyzer_id, analyzer_version)
            def analyze(self, photo):
                started.set()
                if not release.wait(timeout=5):
                    raise RuntimeError('test timed out')
                return AnalyzerExecution(AnalysisOutput(AnalysisOutcome.NO_VISIBLE_FINDINGS), self.configured_provenance)
        with TestClient(create_app(analyzer=Blocking())) as client:
            iid, _, pid = self.setup_photo(client)
            with ThreadPoolExecutor(max_workers=1) as pool:
                call = pool.submit(client.post, f'/inspections/{iid}/photos/{pid}/analyses')
                try:
                    self.assertTrue(started.wait(timeout=3))
                    state = client.get(f'/inspections/{iid}').json()
                    analysis = state['analyses'][0]
                    self.assertEqual(analysis['status'], 'pending')
                    self.assertIsNone(analysis['provenance'])
                    self.assertIsNone(analysis['outcome'])
                    self.assertIsNone(analysis['completed_at'])
                    self.assertIsNone(analysis['failure_code'])
                    self.assertEqual(analysis['limitations'], [])
                    self.assert_error(client.post(f'/inspections/{iid}/photos/{pid}/analyses'),
                                      409, 'transition_conflict')
                finally:
                    release.set()
                self.assertEqual(call.result(timeout=3).status_code, 200)

    def test_foreign_inspection_replacement_evidence_is_not_found(self):
        iid, _, pid = self.setup_photo()
        fid = self.analyze(iid, pid)['findings'][0]['id']
        _, _, foreign = self.setup_photo()
        self.assert_error(self.review(iid, fid, {
            'action': 'edit_and_confirm', 'category': 'scuff', 'surface': 'wall',
            'location': 'center', 'description': 'Mark', 'reportable': True,
            'evidence_photo_ids': [foreign],
        }), 404, 'not_found')

    def test_openapi_has_seven_workflow_operations_and_review_discriminator(self):
        schema = self.client.get('/openapi.json').json()
        operations = [(path, method) for path, methods in schema['paths'].items()
                      for method in methods if method in ('get', 'post') and not path.endswith('/content')]
        self.assertEqual(len(operations), 7)
        review = schema['paths']['/inspections/{inspection_id}/findings/{finding_id}/review']['post']
        body = review['requestBody']['content']['application/json']['schema']
        self.assertEqual(body['discriminator']['propertyName'], 'action')

        # Each domain-validating operation advertises both real response shapes.
        for path in ('/inspections', '/inspections/{inspection_id}/rooms',
                     '/inspections/{inspection_id}/rooms/{room_id}/photos',
                     '/inspections/{inspection_id}/findings/{finding_id}/review'):
            response_schema = schema['paths'][path]['post']['responses']['422']['content']['application/json']['schema']
            alternatives = response_schema.get('anyOf', response_schema.get('oneOf', []))
            names = {entry['$ref'].rsplit('/', 1)[-1] for entry in alternatives}
            self.assertEqual(names, {'HTTPValidationError', 'ErrorResponse'})
            for name in names:
                self.assertIn(name, schema['components']['schemas'])
        self.assertIn('detail', schema['components']['schemas']['HTTPValidationError']['properties'])
        self.assertIn('error', schema['components']['schemas']['ErrorResponse']['properties'])

    def test_unknown_review_action_rejected_before_service(self):
        from unittest.mock import patch
        iid, _, pid = self.setup_photo()
        fid = self.analyze(iid, pid)['findings'][0]['id']
        before = self.client.get(f'/inspections/{iid}').json()
        service = self.client.app.state.inspection_service
        with patch.object(service, 'confirm_finding') as confirm, \
             patch.object(service, 'edit_and_confirm_finding') as edit, \
             patch.object(service, 'reject_finding') as reject:
            response = self.review(iid, fid, {'action': 'unknown'})
            self.assertEqual(response.status_code, 422)
            self.assertIn('detail', response.json())
            self.assertNotIn('error', response.json())
            confirm.assert_not_called()
            edit.assert_not_called()
            reject.assert_not_called()
        self.assertEqual(self.client.get(f'/inspections/{iid}').json(), before)

    def test_malformed_evidence_uuid_rejected_before_service(self):
        from unittest.mock import patch
        iid, _, pid = self.setup_photo()
        fid = self.analyze(iid, pid)['findings'][0]['id']
        before = self.client.get(f'/inspections/{iid}').json()
        with patch.object(self.client.app.state.inspection_service, 'edit_and_confirm_finding') as edit:
            response = self.review(iid, fid, {
                'action': 'edit_and_confirm', 'category': 'scuff', 'surface': 'wall',
                'location': 'center', 'description': 'Mark', 'reportable': True,
                'evidence_photo_ids': ['not-a-uuid'],
            })
            self.assertEqual(response.status_code, 422)
            self.assertIn('detail', response.json())
            self.assertNotIn('error', response.json())
            edit.assert_not_called()
        self.assertEqual(self.client.get(f'/inspections/{iid}').json(), before)

    def test_real_adapter_offline_workflow_and_review(self):
        from uuid import UUID
        from backend.app.images import InMemoryImageSource, prepare_image
        from backend.app.openai_analyzer import OpenAIPhotoAnalyzer, AnalyzerConfig
        from test_openai_analyzer import StubClient, response, image_bytes
        from unittest.mock import patch
        import socket
        safe_fields = {'requested_model', 'provider_model', 'prompt_version',
                       'schema_version', 'preparation_version'}
        for action in ('confirm', 'edit_and_confirm', 'reject'):
            with self.subTest(action=action):
                source, provider = InMemoryImageSource(), StubClient(response())
                adapter = OpenAIPhotoAnalyzer(source, provider, AnalyzerConfig('synthetic-model'))
                app = create_app(analyzer=adapter)
                with patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden')), \
                     TestClient(app) as client:
                    iid, rid, pid = self.setup_photo(client)
                    raw = image_bytes()
                    source.bind(UUID(pid), raw)
                    state = self.analyze(iid, pid, client)
                    self.assertEqual(len(provider.calls), 1)
                    analysis = state['analyses'][0]
                    self.assertEqual(analysis['status'], 'succeeded')
                    self.assertEqual(set(analysis['provenance']), safe_fields)
                    self.assertEqual(analysis['provenance']['requested_model'], 'synthetic-model')
                    stored = app.state.inspection_service.get_inspection(UUID(iid))
                    internal = stored.analyses[UUID(analysis['id'])]
                    prepared = prepare_image(raw)
                    self.assertEqual(internal.result.provenance.original_sha256, prepared.original_sha256)
                    self.assertEqual(internal.result.provenance.prepared_sha256, prepared.prepared_sha256)
                    self.assertNotIn('sha256', str(state))
                    finding = state['findings'][0]
                    original = finding['original_proposal']
                    self.assertEqual(finding['state'], 'pending_review')
                    self.assertFalse(finding['eligible_for_report'])
                    self.assertIsNone(finding['review'])
                    self.assertNotIn('reportable', original)
                    self.assertEqual(original['evidence_photo_ids'], [pid])
                    self.assertEqual(finding['source_analysis_id'], analysis['id'])
                    body = {'action': action}
                    if action == 'confirm':
                        body['reportable'] = False
                    if action == 'edit_and_confirm':
                        registered = client.post(f'/inspections/{iid}/rooms/{rid}/photos', json={
                            'original_filename': 'replacement.png', 'declared_media_type': 'image/png'}).json()
                        replacement = next(p['id'] for p in registered['photos'] if p['id'] != pid)
                        body.update(category='scuff', surface='wall', location='lower',
                                    description='Human correction', reportable=True,
                                    evidence_photo_ids=[replacement])
                    reviewed = client.post(f"/inspections/{iid}/findings/{finding['id']}/review", json=body)
                    self.assertEqual(reviewed.status_code, 200)
                    final = reviewed.json()['findings'][0]
                    self.assertEqual(final['original_proposal'], original)
                    self.assertEqual(final['eligible_for_report'], action == 'edit_and_confirm')
                    self.assertEqual(final['state'], 'rejected' if action == 'reject' else 'confirmed')
                    if action == 'edit_and_confirm':
                        self.assertEqual(final['review']['approved']['evidence_photo_ids'], [replacement])
                    self.assertEqual(len(provider.calls), 1)

    def test_real_adapter_failures_expose_only_safe_provenance(self):
        from uuid import UUID
        from backend.app.images import InMemoryImageSource
        from backend.app.openai_analyzer import OpenAIPhotoAnalyzer, AnalyzerConfig
        from backend.app.inference import AnalyzerContractError
        from test_openai_analyzer import StubClient, image_bytes
        for error, code in ((None, 'unreadable_image'), (RuntimeError('private diagnostic'), 'unavailable'),
                            (AnalyzerContractError('private diagnostic'), 'invalid_response')):
            source, provider = InMemoryImageSource(), StubClient(error=error)
            app = create_app(analyzer=OpenAIPhotoAnalyzer(source, provider, AnalyzerConfig('synthetic')))
            with TestClient(app) as client:
                iid, _, pid = self.setup_photo(client)
                if error is not None:
                    source.bind(UUID(pid), image_bytes())
                state = self.analyze(iid, pid, client)
                self.assertFalse(state['findings'])
                analysis = state['analyses'][0]
                self.assertEqual(analysis['failure_code'], code)
                self.assertEqual(analysis['provenance']['requested_model'], 'synthetic')
                self.assertNotIn('sha256', str(state))
                self.assertNotIn('private diagnostic', str(state))
                self.assertEqual(len(provider.calls), 0 if error is None else 1)
