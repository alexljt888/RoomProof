"""Synthetic, network-free coverage for scoped transient photo content."""
from io import BytesIO
import os
import socket
import unittest
from unittest.mock import patch
from uuid import UUID

from fastapi.testclient import TestClient
from PIL import Image

from backend.app.domain import AnalysisOutcome
from backend.app.images import InMemoryImageSource, prepare_image
from backend.app.inference import AnalysisOutput, AnalyzerExecution
from backend.app.domain import AnalysisProvenance
from backend.app.main import create_app


def picture(fmt='PNG'):
    with Image.new('RGB', (8, 6), 'white') as im, BytesIO() as out:
        im.save(out, format=fmt)
        return out.getvalue()


class PhotoContentTests(unittest.TestCase):
    def setUp(self):
        for owner, name in ((socket, 'getaddrinfo'), (socket.socket, 'connect'), (socket.socket, 'connect_ex')):
            guard = patch.object(owner, name, side_effect=AssertionError('network forbidden'))
            guard.start(); self.addCleanup(guard.stop)
        env = patch.dict(os.environ, {}, clear=True); env.start(); self.addCleanup(env.stop)
        self.app = create_app()
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.iid, self.pid = self.register(self.client)
        self.url = f'/inspections/{self.iid}/photos/{self.pid}/content'

    def register(self, client):
        state = client.post('/inspections', json={'property_details': {'address': 'Synthetic'}, 'renter_name': 'Example'}).json()
        iid = state['id']
        state = client.post(f'/inspections/{iid}/rooms', json={'name':'Room'}).json()
        rid = state['rooms'][0]['id']
        state = client.post(f'/inspections/{iid}/rooms/{rid}/photos', json={'original_filename':'example.png','declared_media_type':'image/png'}).json()
        return iid, state['photos'][0]['id']

    def test_upload_read_prepared_no_store(self):
        for fmt in ('JPEG','PNG'):
            iid,pid = self.register(self.client)
            url=f'/inspections/{iid}/photos/{pid}/content'
            raw=picture(fmt)
            self.assertEqual(self.client.put(url,content=raw).status_code,204)
            result=self.client.get(url)
            self.assertEqual(result.status_code,200)
            self.assertEqual(result.headers['cache-control'],'no-store')
            self.assertEqual(result.headers['content-type'],'image/png')
            self.assertEqual(result.content,prepare_image(raw).encoded_bytes)
            self.assertEqual(self.app.state.image_source.read(UUID(pid)),raw)

    def test_scope_and_missing_content(self):
        other,_=self.register(self.client)
        url=f'/inspections/{other}/photos/{self.pid}/content'
        self.assertEqual(self.client.put(url,content=picture()).status_code,404)
        self.assertEqual(self.client.get(url).status_code,404)
        self.assertEqual(self.client.get(self.url).status_code,404)

    def test_invalid_unsupported_and_retry(self):
        for raw in (b'', b'not an image', picture('GIF')):
            self.assertEqual(self.client.put(self.url,content=raw).status_code,422)
        self.assertEqual(self.client.put(self.url,content=picture()).status_code,204)
        self.assertEqual(self.client.put(self.url,content=picture()).status_code,409)
        self.assertEqual(self.client.put(self.url,content=b'invalid replacement').status_code,409)

    def test_stream_limit_no_binding(self):
        with patch('backend.app.photo_content.MAX_INPUT_BYTES', 10):
            self.assertEqual(self.client.put(self.url,content=picture()).status_code,413)
        self.assertEqual(self.client.get(self.url).status_code,404)
        self.assertEqual(self.client.put(self.url,content=picture()).status_code,204)

    def test_aggregate_limit_atomic_and_duplicate(self):
        raw=picture()
        source=InMemoryImageSource(max_total_bytes=len(raw))
        with TestClient(create_app(image_source=source)) as client:
            iid,pid=self.register(client)
            url=f'/inspections/{iid}/photos/{pid}/content'
            self.assertEqual(client.put(url,content=raw).status_code,204)
            self.assertEqual(client.put(url,content=raw).status_code,409)
            iid2,pid2=self.register(client)
            url2=f'/inspections/{iid2}/photos/{pid2}/content'
            self.assertEqual(client.put(url2,content=raw).status_code,413)
            self.assertEqual(client.get(url2).status_code,404)
            self.assertEqual(client.get(url).status_code,200)

    def test_injected_analyzer_consumes_shared_source(self):
        source=InMemoryImageSource()
        seen=[]
        class Reader:
            image_source=source
            configured_provenance=AnalysisProvenance('offline-reader','1')
            def analyze(self, photo):
                seen.append(self.image_source.read(photo.id))
                return AnalyzerExecution(AnalysisOutput(AnalysisOutcome.NO_VISIBLE_FINDINGS),self.configured_provenance)
        with TestClient(create_app(analyzer=Reader())) as client:
            iid,pid=self.register(client)
            self.assertEqual(client.put(f'/inspections/{iid}/photos/{pid}/content',content=picture()).status_code,204)
            state=client.post(f'/inspections/{iid}/photos/{pid}/analyses').json()
            self.assertEqual(state['analyses'][0]['status'],'succeeded')
            self.assertEqual(seen,[picture()])
        with self.assertRaises(ValueError):
            create_app(analyzer=Reader(),image_source=InMemoryImageSource())

    def test_default_fake_remains_key_free(self):
        self.client.put(self.url,content=picture())
        state=self.client.post(f'/inspections/{self.iid}/photos/{self.pid}/analyses').json()
        self.assertEqual(state['analyses'][0]['analyzer_id'],'fake')
        self.assertEqual(state['findings'][0]['state'],'pending_review')
        self.assertFalse(state['findings'][0]['eligible_for_report'])

    def test_registration_returns_its_own_photo_last_in_detached_snapshot(self):
        # Frontend must identify this request's Photo, even with a stale snapshot
        # that predates another client's registration. No timestamp sorting.
        initial = self.client.get(f'/inspections/{self.iid}').json()
        rid = initial['rooms'][0]['id']
        url = f'/inspections/{self.iid}/rooms/{rid}/photos'
        first = self.client.post(url, json={'original_filename':'other.png','declared_media_type':'image/png'}).json()
        second = self.client.post(url, json={'original_filename':'selected.png','declared_media_type':'image/png'}).json()
        self.assertEqual(second['photos'][:-1], first['photos'])
        self.assertEqual(second['photos'][-1]['original_filename'], 'selected.png')
        self.assertNotEqual(first['photos'][-1]['id'], second['photos'][-1]['id'])
        self.assertEqual(len(initial['photos']), 1)
