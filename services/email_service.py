from utils.email_utils import send_email_with_inline_qr
from config import EVENT_NAME

def send_issue_or_reissue(
    *,
    recipients: list[str],
    username: str,
    qr_bytes: bytes,
    s3_url: str,
    preview_url: str,
    is_reissue: bool,
):
    subject = f"{'[Re-issue] ' if is_reissue else ''}Your {EVENT_NAME} Event entry QR Code."
    body_intro = f"""
        <p>Hi {username},</p>
        
        <p>Thank you for being an integral part of NSS North Texas. 
        This Onam, we hope your check-in process for the <b>{EVENT_NAME} Onam Celebration</b> is 
        smooth and efficient. 
        To help with this, we are excited to pilot our new 
        <b>digital QR code check-in system</b>.</p>

        <h3>How to Use It</h3>
        <ol>
            <li><b>Bring Your QR Code</b> – Show the QR code on your phone when you arrive at the event.</li>
            <li><b>Quick Scan at Entry</b> – Our volunteers will scan it to confirm your entry in seconds.</li>
            <li><b>Enjoy the Event</b> – That’s it—no paperwork, no delays.</li>
        </ol>

        <p>Your valuable feedback and suggestions are welcome.</p>

        <p><b>We can’t wait to celebrate Onam with you! 🎉🌸</b></p>

        {"<p style='color:#b91c1c; font-weight:600;'>This is a re-issue. Please use this NEW QR.</p>" if is_reissue else ""}

        <p style="margin-top:20px;">
            Warm Regards,<br/>
            <b>NSS North Texas Team</b>
        </p>
        """

    results = []
    for rcpt in recipients:
        send_email_with_inline_qr(
            recipient=rcpt,
            subject=subject,
            body_intro_html=body_intro,
            qr_bytes=qr_bytes,
            s3_url=s3_url,
            preview_url=preview_url,
            is_reissue=is_reissue,
        )
        results.append(rcpt)
    return results
