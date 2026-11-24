from io import BytesIO

from django.utils import timezone
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen.canvas import Canvas


def render_certificate(approval) -> bytes:
    buffer = BytesIO()
    width, height = landscape(A4)
    pdf = Canvas(buffer, pagesize=(width, height))
    pdf.setTitle(f"Certificate of Attendance | {approval.certificate_reference}")
    mid = width / 2
    ink = HexColor("#18323B")
    accent = HexColor("#24746D")
    pdf.setStrokeColor(accent)
    pdf.setLineWidth(2)
    pdf.rect(38, 38, width - 76, height - 76)
    pdf.line(mid - 52, 389, mid + 52, 389)
    approval_date = timezone.localtime(approval.approved_at).date()
    lines = [
        ("Helvetica-Bold", 14, 495, "TRAINING REGISTER"),
        ("Times-Bold", 38, 425, "Certificate of Attendance"),
        ("Helvetica-Bold", 26, 335, approval.trainee_name),
        ("Helvetica", 18, 286, approval.batch_name),
        ("Helvetica", 13, 258, f"Trainee ID: {approval.trainee_code}"),
        ("Helvetica", 13, 232, f"Verified attendance: {approval.attended} of {approval.total} sessions"),
        ("Helvetica", 12, 155, f"Approved by {approval.reviewer_name} on {approval_date}"),
        ("Helvetica-Bold", 11, 100, f"Register reference {approval.certificate_reference}"),
    ]
    if approval.snapshot_origin == "reconstructed":
        lines.append(("Helvetica", 10, 75, "Legacy identity details reconstructed from available records."))
    pdf.setFillColor(ink)
    max_text_width = width - 134
    for font, size, y, line in lines:
        text_width = pdf.stringWidth(line, font, size)
        if text_width > max_text_width:
            size *= max_text_width / text_width
        pdf.setFont(font, size)
        pdf.drawCentredString(mid, y, line)
    pdf.save()
    return buffer.getvalue()
