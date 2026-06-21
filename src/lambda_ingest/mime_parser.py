from email import policy
from email.parser import BytesParser
from email.utils import parseaddr


def parse_email(raw_email: bytes) -> dict:
    # policy.default enables UTF-8 header decoding (RFC 2047) and handles
    # Content-Transfer-Encoding (base64, quoted-printable) automatically
    msg = BytesParser(policy=policy.default).parsebytes(raw_email)
    print(f"[mime_parser] parsed MIME message, content-type: {msg.get_content_type()}")

    if msg["from"]:
        # parseaddr returns (display_name, email) — [1] strips "Jane Doe" from "Jane Doe <jane@example.com>"
        from_address = parseaddr(str(msg["from"]))[1]
    else:
        from_address = ""

    if msg["subject"]:
        subject = str(msg["subject"])
    else:
        subject = ""

    # preferencelist=("plain", "html") — prefer plain text; fall back to HTML if no plain part
    body_part = msg.get_body(preferencelist=("plain", "html"))
    if body_part:
        # get_content() decodes base64/quoted-printable automatically via policy.default
        body = body_part.get_content()
    else:
        body = ""

    print(f"[mime_parser] from={from_address}, subject={subject[:50]}, body_len={len(body)}")
    return {"from_address": from_address, "subject": subject, "body": body}
