from utils.email_utils import send_email_with_qr_url

send_email_with_qr_url(
    recipient="sumapnair@gmail.com",
    subject="Test from eventsnssnt",
    body_html="<p>Hello from NSS NT mailer!</p>"
)
