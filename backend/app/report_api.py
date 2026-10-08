"""Inspection-scoped preview and export from one authoritative snapshot."""
from uuid import UUID
from fastapi import APIRouter, Request, Response, HTTPException
from .api import Service
from .reports import InspectionReport, project_report
from .report_pdf import render_pdf, ReportUnavailable

router = APIRouter()


@router.get('/inspections/{inspection_id}/report', response_model=InspectionReport)
def report(inspection_id: UUID, service: Service, response: Response, request: Request):
    response.headers['Cache-Control'] = 'no-store'
    return project_report(service.get_inspection(inspection_id), request.app.state.image_source)


@router.get('/inspections/{inspection_id}/report.pdf', response_class=Response,
            responses={200: {'content': {'application/pdf': {}}}, 409: {'description': 'Review or evidence incomplete'},
                       422: {'description': 'Unsupported report text'}, 404: {'description': 'Inspection not found'}})
def pdf(inspection_id: UUID, service: Service, request: Request):
    snapshot = project_report(service.get_inspection(inspection_id), request.app.state.image_source)
    try:
        content = render_pdf(snapshot, request.app.state.image_source)
    except ReportUnavailable as exc:
        messages = {'export_incomplete': 'Complete successful analysis for every photo and review all suggestions before exporting.',
                    'evidence_unavailable': 'Approved evidence is unavailable. Final export is blocked.',
                    'unsupported_text': 'This PDF font does not support some report characters. Export is blocked to avoid losing text.'}
        raise HTTPException(422 if exc.code == 'unsupported_text' else 409,
                            detail={'code': exc.code, 'message': messages[exc.code]}) from None
    return Response(content, media_type='application/pdf', headers={
        'Content-Disposition': 'attachment; filename="roomproof-inspection.pdf"',
        'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})
