from io import BytesIO

from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen.canvas import Canvas


def render_certificate(approval) -> bytes:
    buffer = BytesIO()
    pdf = Canvas(buffer, pagesize=landscape(A4))
    mid = landscape(A4)[0] / 2
    lines = [
        (14, 495, "TRAINING REGISTER"),
        (32, 420, "Certificate of Attendance"),
        (22, 335, approval.trainee_name),
        (17, 286, approval.batch_name),
        (13, 258, f"Trainee ID: {approval.trainee_code}"),
        (13, 232, f"Verified attendance: {approval.attended} of {approval.total} sessions"),
        (12, 155, f"Approved by {approval.reviewer_name} on {approval.approved_at.date()}"),
        (11, 100, f"Register reference {approval.certificate_reference}"),
    ]
    if approval.snapshot_origin == "reconstructed":
        lines.append((10, 75, "Legacy identity details reconstructed from available records."))
    for size, y, line in lines:
        pdf.setFont("Helvetica", size)
        pdf.drawCentredString(mid, y, line)
    pdf.save()
    return buffer.getvalue()
