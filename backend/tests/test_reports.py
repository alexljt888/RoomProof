"""Synthetic report/export tests; no provider requests or filesystem images."""
from io import BytesIO
import os
import socket
import unittest
from unittest.mock import patch
from uuid import UUID, uuid4
from fastapi.testclient import TestClient
from pypdf import PdfReader
from backend.app.main import create_app
from backend.app.reports import project_report
from backend.app.domain import Analysis, FailureCode, AnalysisOutcome
from backend.app.inference import FakePhotoAnalyzer, AnalysisOutput
from test_photo_content import picture


class ReportTests(unittest.TestCase):
    def setUp(self):
        env=patch.dict(os.environ, {}, clear=True);env.start();self.addCleanup(env.stop)
        for owner,name in ((socket,'getaddrinfo'),(socket.socket,'connect'),(socket.socket,'connect_ex')):
            guard=patch.object(owner,name,side_effect=AssertionError('network forbidden'))
            guard.start();self.addCleanup(guard.stop)
        self.app=create_app();self.client=TestClient(self.app)
        self.addCleanup(self.client.close)
        self.service=self.app.state.inspection_service
        self.iid=self.client.post('/inspections',json={'property_details':{'address':'Synthetic <Home>','unit':'101'},'renter_name':'Example Renter'}).json()['id']

    def finding(self, room='Room', upload=True, iid=None):
        iid=iid or self.iid
        state=self.client.post(f'/inspections/{iid}/rooms',json={'name':room}).json()
        rid=state['rooms'][-1]['id']
        state=self.client.post(f'/inspections/{iid}/rooms/{rid}/photos',json={'original_filename':'example.png','declared_media_type':'image/png'}).json()
        pid=state['photos'][-1]['id']
        if upload:self.assertEqual(self.client.put(f'/inspections/{iid}/photos/{pid}/content',content=picture()).status_code,204)
        state=self.client.post(f'/inspections/{iid}/photos/{pid}/analyses').json()
        return state['findings'][-1]['id'],pid

    def review(self, fid, **data):
        return self.client.post(f'/inspections/{self.iid}/findings/{fid}/review',json=data)

    def preview(self):return self.client.get(f'/inspections/{self.iid}/report')
    def pdf(self):return self.client.get(f'/inspections/{self.iid}/report.pdf')

    def test_filter_approved_content_grouping_and_pending_block(self):
        keep,pid=self.finding('Bedroom')
        self.review(keep,action='edit_and_confirm',category='hole',surface='wall',location='Left',description='Human approved <indentation> & evidence',evidence_photo_ids=[pid],reportable=True)
        reject,_=self.finding('Kitchen');self.review(reject,action='reject')
        note,_=self.finding('Office');self.review(note,action='confirm',reportable=False)
        pending,_=self.finding('Hall')
        report=self.preview().json()
        self.assertEqual(report['finding_count'],1);self.assertEqual(report['room_count'],4)
        selected=report['rooms'][0]['findings'][0]
        self.assertEqual(selected['category'],'hole');self.assertEqual(selected['description'],'Human approved <indentation> & evidence')
        self.assertEqual(selected['evidence_photo_ids'],[pid])
        self.assertTrue(all(not r['findings'] for r in report['rooms'][1:]))
        self.assertFalse(report['review_complete']);self.assertEqual(self.pdf().status_code,409)
        self.review(pending,action='reject')
        before=self.client.get(f'/inspections/{self.iid}').json()
        with patch.object(self.service.analyzer.__class__,'analyze',side_effect=AssertionError('provider forbidden')):
            self.preview();response=self.pdf();again=self.pdf()
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.headers['content-type'],'application/pdf')
        self.assertEqual(response.headers['content-disposition'],'attachment; filename="roomproof-inspection.pdf"')
        self.assertEqual(response.headers['cache-control'],'no-store')
        self.assertTrue(response.content.startswith(b'%PDF-'))
        self.assertEqual(response.content,again.content)
        reader=PdfReader(BytesIO(response.content));text='\n'.join(p.extract_text() for p in reader.pages)
        self.assertIn('Human approved <indentation> & evidence',text)
        self.assertNotIn('Synthetic example scratch',text)
        self.assertIn('Synthetic <Home>',text)
        self.assertEqual(sum(len(p.images) for p in reader.pages),1)
        self.assertEqual(before,self.client.get(f'/inspections/{self.iid}').json())
        self.assertNotIn('sha256',self.preview().text)

    def test_zero_findings_pdf(self):
        response=self.pdf();self.assertEqual(response.status_code,200)
        text=PdfReader(BytesIO(response.content)).pages[0].extract_text()
        self.assertIn('No confirmed reportable findings',text)
        self.assertTrue(self.preview().json()['review_complete'])

    def test_missing_and_invalid_evidence_block_export(self):
        fid,pid=self.finding(upload=False);self.review(fid,action='confirm',reportable=True)
        self.assertEqual(self.preview().status_code,200)
        self.assertFalse(self.preview().json()['export_ready'])
        self.assertEqual(self.preview().json()['unavailable_evidence'],1)
        self.assertEqual(self.pdf().json()['detail']['code'],'evidence_unavailable')
        self.app.state.image_source.bind(UUID(pid),b'invalid image')
        self.assertEqual(self.pdf().status_code,409)

    def test_approved_replacement_evidence_is_used(self):
        fid,original=self.finding(upload=False)
        state=self.client.get(f'/inspections/{self.iid}').json();rid=state['rooms'][0]['id']
        pid=self.client.post(f'/inspections/{self.iid}/rooms/{rid}/photos',json={'original_filename':'replacement.png','declared_media_type':'image/png'}).json()['photos'][-1]['id']
        self.client.put(f'/inspections/{self.iid}/photos/{pid}/content',content=picture())
        self.review(fid,action='edit_and_confirm',category='chip',surface='trim',description='Approved replacement',location='Top',evidence_photo_ids=[pid],reportable=True)
        self.assertEqual(self.preview().json()['rooms'][0]['findings'][0]['evidence_photo_ids'],[pid])
        analysed=self.client.post(f'/inspections/{self.iid}/photos/{pid}/analyses').json()
        self.review(analysed['findings'][-1]['id'],action='reject')
        self.assertEqual(self.pdf().status_code,200)

    def test_cross_inspection_evidence_rejected_and_not_projected(self):
        other=self.client.post('/inspections',json={'property_details':{'address':'Other private property'},'renter_name':'Other'}).json()['id']
        _,foreign=self.finding(iid=other)
        fid,_=self.finding()
        response=self.review(fid,action='edit_and_confirm',category='hole',surface='wall',location='Top',description='Approved',reportable=True,evidence_photo_ids=[foreign])
        self.assertEqual(response.status_code,404)
        self.assertNotIn(foreign,self.preview().text)
        self.assertNotIn('Other private property',self.preview().text)
        self.assertEqual(self.client.get(f'/inspections/{uuid4()}/report').status_code,404)
        self.assertEqual(self.client.get(f'/inspections/{uuid4()}/report.pdf').status_code,404)

    def test_in_progress_analysis_blocks_export(self):
        fid,pid=self.finding();self.review(fid,action='reject')
        def reserve(state):
            analysis=Analysis(state.photos[UUID(pid)],'fake','1')
            state.analyses[analysis.id]=analysis
        self.service.repository.update(UUID(self.iid),reserve)
        self.assertEqual(self.preview().json()['pending_analyses'],1)
        self.assertEqual(self.pdf().status_code,409)

    def test_unicode_not_silently_lost(self):
        fid,pid=self.finding()
        self.review(fid,action='edit_and_confirm',category='hole',surface='wall',location='Top',description='墙',reportable=True,evidence_photo_ids=[pid])
        self.assertEqual(self.pdf().status_code,422)
        self.assertEqual(self.pdf().json()['detail']['code'],'unsupported_text')

    def test_long_text_paginates(self):
        fid,pid=self.finding()
        self.review(fid,action='edit_and_confirm',category='hole',surface='wall',location='Top',description='Long approved observation. '*450,reportable=True,evidence_photo_ids=[pid])
        response=self.pdf();self.assertEqual(response.status_code,200)
        self.assertGreater(len(PdfReader(BytesIO(response.content)).pages),1)

    def unanalysed_photo(self):
        state=self.client.post(f'/inspections/{self.iid}/rooms',json={'name':'Room'}).json()
        rid=state['rooms'][-1]['id']
        state=self.client.post(f'/inspections/{self.iid}/rooms/{rid}/photos',json={'original_filename':'example.png','declared_media_type':'image/png'}).json()
        pid=state['photos'][-1]['id']
        self.client.put(f'/inspections/{self.iid}/photos/{pid}/content',content=picture())
        return pid

    def test_unanalysed_photo_blocks_direct_export_until_analysis_and_review(self):
        pid=self.unanalysed_photo()
        before=self.client.get(f'/inspections/{self.iid}').json()
        preview=self.preview()
        self.assertEqual(preview.status_code,200)
        self.assertTrue(preview.json()['review_complete'])
        self.assertFalse(preview.json()['export_ready'])
        self.assertEqual(preview.json()['photos_needing_analysis'],1)
        response=self.pdf()
        self.assertEqual(response.status_code,409)
        self.assertEqual(response.json()['detail']['code'],'export_incomplete')
        self.assertEqual(before,self.client.get(f'/inspections/{self.iid}').json())
        state=self.client.post(f'/inspections/{self.iid}/photos/{pid}/analyses').json()
        self.assertEqual(self.preview().json()['photos_needing_analysis'],0)
        self.assertFalse(self.preview().json()['export_ready'])
        self.assertEqual(self.pdf().status_code,409)
        self.review(state['findings'][-1]['id'],action='confirm',reportable=False)
        self.assertTrue(self.preview().json()['export_ready'])
        self.assertEqual(self.preview().json()['finding_count'],0)
        self.assertEqual(self.pdf().status_code,200)

    def test_failure_blocks_until_successful_retry_and_history_does_not_block(self):
        pid=self.unanalysed_photo()
        self.service.analyzer=FakePhotoAnalyzer(FailureCode.UNAVAILABLE)
        self.client.post(f'/inspections/{self.iid}/photos/{pid}/analyses')
        self.assertEqual(self.preview().json()['failed_analyses'],1)
        self.assertEqual(self.preview().json()['photos_needing_analysis'],1)
        self.assertFalse(self.preview().json()['export_ready'])
        self.assertEqual(self.pdf().status_code,409)
        self.service.analyzer=FakePhotoAnalyzer(AnalysisOutput(AnalysisOutcome.NO_VISIBLE_FINDINGS))
        self.client.post(f'/inspections/{self.iid}/photos/{pid}/analyses')
        report=self.preview().json()
        self.assertEqual(report['failed_analyses'],1)
        self.assertEqual(report['photos_needing_analysis'],0)
        self.assertTrue(report['export_ready'])
        self.assertEqual(self.pdf().status_code,200)

    def test_pdf_thumbnail_bounds_preserve_aspect_ratio_and_never_upscale(self):
        from backend.app.report_pdf import thumbnail_size
        for width,height in ((1200,1800),(1800,1200),(800,800),(8,6)):
            w,h=thumbnail_size(width,height)
            self.assertLessEqual(w,144)
            self.assertLessEqual(h,172.8)
            self.assertLessEqual(w,width)
            self.assertLessEqual(h,height)
            self.assertAlmostEqual(w/h,width/height)
        self.assertEqual(thumbnail_size(8,6),(8,6))

    def test_compact_header_labels_and_thirty_mixed_findings_paginate(self):
        from PIL import Image
        from backend.app.reports import RoomReport,ReportFinding
        from backend.app.report_pdf import render_pdf
        source=self.app.state.image_source
        photos=[]
        for size in ((900,1500),(1500,900)):
            pid=uuid4()
            with Image.new('RGB',size,'#ddddee') as image, BytesIO() as out:
                image.save(out,format='PNG');source.bind(pid,out.getvalue())
            photos.append(pid)
        report=project_report(self.service.get_inspection(UUID(self.iid)),source)
        report.rooms=[RoomReport(id=uuid4(),name=f'Room {r+1}',findings=[
            ReportFinding(id=uuid4(),category='hole',surface='wall',location='Near center',
                description=f'Approved observation {r*10+i+1}.',evidence_photo_ids=[photos[i%2]])
            for i in range(10)]) for r in range(3)]
        report.room_count=3;report.finding_count=30
        data=render_pdf(report,source)
        self.assertEqual(data,render_pdf(report,source))
        reader=PdfReader(BytesIO(data))
        self.assertGreater(len(reader.pages),1)
        self.assertLess(len(reader.pages),15)
        text='\n'.join(page.extract_text() for page in reader.pages)
        for n in range(1,31):
            self.assertIn(f'Approved observation {n}.',text)
            self.assertIn(f'Approved evidence - finding {n}',text)
        runs=[]
        reader.pages[0].extract_text(visitor_text=lambda text,cm,tm,font,size:runs.append((text,font.get('/BaseFont','') if font else '')))
        for label in ('Property:', 'Unit:', 'Renter:'):
            self.assertTrue(any(label in text and 'Bold' in font for text,font in runs))
        self.assertTrue(any('Synthetic <Home>' in text and 'Bold' not in font for text,font in runs))
        self.assertIn('RoomProof - Move-In Inspection Report',reader.pages[0].extract_text())
