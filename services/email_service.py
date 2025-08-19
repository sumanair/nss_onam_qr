from utils.email_utils import send_email_with_inline_qr
from config import EVENT_NAME
import html, textwrap

def send_issue_or_reissue(
    *,
    recipients: list[str],
    username: str,
    qr_bytes: bytes,
    s3_url: str,
    preview_url: str,
    is_reissue: bool,
):
    subject = f"{'[Re-issue] ' if is_reissue else ''}{EVENT_NAME} – Your Event Entry QR Code"

    safe_name = html.escape(username)

    body_intro = textwrap.dedent(f"""\
        <p>Hi {safe_name},</p>

        <p>Thank you for being an integral part of NSS North Texas.
        This Onam, we hope your check-in process for the <b>{EVENT_NAME} Onam Celebration</b> is
        smooth and efficient. To help with this, we are piloting our new
        <b>digital QR code check-in system</b>.</p>

        {"<div style='margin:12px 0;padding:10px 12px;border-left:4px solid #b91c1c;background:#fee2e2;color:#7f1d1d;font-weight:600;'>This is a <b>re-issue</b>. Please use this <u>NEW</u> QR.</div>" if is_reissue else ""}

        <h3 style="margin:18px 0 8px;">How to Use It</h3>
        <ol style="padding-left:20px;margin:0;">
            <li><b>Bring Your QR Code</b> – Show the QR code when you arrive at the event.</li>
            <li><b>Quick Scan at Entry</b> – Our volunteers will scan it to confirm your entry in seconds.</li>
            <li><b>Enjoy the Event</b> – That’s it—no paperwork, no delays.</li>
        </ol>

        <p style="color:#800000;font-weight:bold;margin-top:12px;">
            ⚠️ Note: We encourage you to bring your QR code(s). If you are unable to present your QR code at check-in,
            you will not be able to use the expedited process. In that case, the traditional check-in method used
            in the past—manual verification of payment information—will apply instead.
        </p>

        <p style="color:#000080;font-weight:bold;margin-top:12px;">
            ⚠️ Note: For every PayPal payment transaction, you will receive a QR code.
            If you made multiple payments (for guests, extended family, etc.), please make sure to have them all handy.
        </p>

        <p>Your valuable feedback and suggestions are welcome.</p>

        <p><b>We can’t wait to celebrate Onam with you! 🎉🌼</b></p>

        <p style="margin-top:16px;">
          Warm regards,<br/>
          <b>NSS North Texas Team</b>
        </p>
    """)

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
