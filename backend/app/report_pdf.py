"""Memory-only PDF rendering. No provider access or caller-supplied file paths."""
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape
import reportlab
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, KeepTogether, Table, TableStyle
from .images import ImageSource, ImageError, prepare_image
from .reports import InspectionReport

# Fixed bundled font path, never derived from inspection/user input.
pdfmetrics.registerFont(TTFont('RoomProof', str(Path(reportlab.__file__).parent / 'fonts' / 'Vera.ttf')))
pdfmetrics.registerFont(TTFont('RoomProof-Bold', str(Path(reportlab.__file__).parent / 'fonts' / 'VeraBd.ttf')))
pdfmetrics.registerFontFamily('RoomProof', normal='RoomProof', bold='RoomProof-Bold')


def thumbnail_size(width: int, height: int) -> tuple[float, float]:
    # Points: 2 inches wide x 2.4 inches tall; never enlarge small sources.
    scale = min(1.0, 144 / width, 172.8 / height)
    return width * scale, height * scale


class ReportUnavailable(Exception):
    def __init__(self, code):
        self.code = code


def render_pdf(report: InspectionReport, source: ImageSource) -> bytes:
    if not report.export_ready:
        raise ReportUnavailable('evidence_unavailable' if report.unavailable_evidence
                                else 'export_incomplete')
    styles = getSampleStyleSheet()
    for style in styles.byName.values():
        style.fontName = 'RoomProof'
    styles['BodyText'].fontSize = 10
    styles['BodyText'].leading = 15
    styles.add(ParagraphStyle('Evidence', fontName='RoomProof', fontSize=8, leading=11, spaceAfter=4))
    styles['Heading1'].fontSize = 17
    styles['Heading1'].leading = 22
    styles['Heading1'].spaceBefore = 0
    styles['Heading1'].spaceAfter = 8
    for name in ('Heading2', 'Heading3'):
        styles[name].fontName = 'RoomProof-Bold'
    styles['Heading2'].fontSize = 13
    styles['Heading2'].leading = 17
    styles['Heading2'].spaceBefore = 12
    styles['Heading2'].keepWithNext = True
    styles['Heading3'].fontSize = 10
    styles['Heading3'].leading = 14
    styles['Heading3'].spaceBefore = 9
    def paragraph(text, style='BodyText', label=None):
        # Fail explicitly instead of silently dropping unsupported characters.
        if any(ord(c) not in pdfmetrics.getFont('RoomProof').face.charToGlyph for c in text if not c.isspace()):
            raise ReportUnavailable('unsupported_text')
        content = escape(text).replace('\n', '<br/>')
        if label:
            content = '<b>' + escape(label) + '</b> ' + content
        return Paragraph(content, styles[style])
    story = [Paragraph('<font color="#3949ab"><b>RoomProof</b></font> - Move-In Inspection Report', styles['Heading1']),
             paragraph('Reviewed content approved by the renter. This is not a determination of cause, age or responsibility.'),
             Spacer(1, 8), paragraph(report.address, label='Property:'),
             paragraph(report.unit or 'Not provided', label='Unit:'), paragraph(report.renter, label='Renter:'),
             Spacer(1, 6), paragraph('Inspection summary', 'Heading2'),
             paragraph(f'{report.room_count} rooms documented; {report.finding_count} confirmed reportable findings.'),
             paragraph(f'{report.unanalysed_photos} photos without analysis; {report.failed_analyses} failed analysis attempts. Review completion is not proof of complete inspection coverage.'),
             paragraph('Local snapshot only. RoomProof storage is transient; retain this downloaded copy.'), Spacer(1, 6)]
    if not report.finding_count:
        story.append(paragraph('No confirmed reportable findings. This does not certify that the property is damage-free.'))
    finding_number = 0
    for room in report.rooms:
        story.append(paragraph(room.name, 'Heading2'))
        if not room.findings:
            story.append(paragraph('No confirmed reportable findings in this room.'))
        for finding in room.findings:
            finding_number += 1
            text = [paragraph(f'{finding_number}. {finding.category.replace("_", " ").title()} on {finding.surface}', 'Heading3'),
                          paragraph('Location: ' + finding.location), paragraph(finding.description)]
            evidence = []
            for pid in finding.evidence_photo_ids:
                try:
                    prepared = prepare_image(source.read(pid))
                except ImageError:
                    raise ReportUnavailable('evidence_unavailable') from None
                width, height = thumbnail_size(prepared.width, prepared.height)
                image = Image(BytesIO(prepared.encoded_bytes), width=width, height=height, hAlign='LEFT')
                # Only keep the caption and thumbnail together, not the entire
                # finding: long approved text can split naturally across pages.
                evidence.append([paragraph(f'Approved evidence - finding {finding_number}', 'Evidence'), image])
            # Compact short findings beside their single thumbnail. Long prose
            # and multiple evidence images retain ordinary splittable text flow.
            text_height = sum(p.wrap(328, 700)[1] + p.getSpaceBefore() + p.getSpaceAfter() for p in text)
            if len(evidence) == 1 and text_height <= 180:
                row = Table([[text, evidence[0]]], colWidths=[344, 160], hAlign='LEFT')
                row.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ('LEFTPADDING', (0, 0), (-1, -1), 0),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 12),
                    ('TOPPADDING', (0, 0), (-1, -1), 4),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 10)]))
                story.append(row)
            else:
                story.extend(text)
                for block in evidence:
                    story.append(KeepTogether([Spacer(1, 4), *block, Spacer(1, 8)]))
    output = BytesIO()
    def canvas(*args, **kwargs):
        kwargs["invariant"] = 1
        return Canvas(*args, **kwargs)
    def footer(canvas, doc):
        canvas.setFont('RoomProof', 8)
        canvas.drawString(48, 28, 'RoomProof | Human-reviewed inspection snapshot')
        canvas.drawRightString(564, 28, str(doc.page))
    SimpleDocTemplate(output, pagesize=(612, 792), rightMargin=48, leftMargin=48,
                      topMargin=24, bottomMargin=48, title='RoomProof Move-In Inspection Report',
                      author='RoomProof').build(story, canvasmaker=canvas, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
