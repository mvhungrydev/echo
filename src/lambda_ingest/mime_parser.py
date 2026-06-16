from email import policy
from email.parser import BytesParser
from email.utils import parseaddr


def parse_email(raw_email: bytes) -> dict:
    msg = BytesParser(policy=policy.default).parsebytes(raw_email)
    if msg["from"]:
        from_address = parseaddr(str(msg["from"]))[1]
    else:
        from_address = ""

    if msg["subject"]:
        subject = str(msg["subject"])
    else:
        subject = ""

    body_part = msg.get_body(preferencelist=("plain", "html"))
    if body_part:
        body = body_part.get_content()
    else:
        body = ""
    return {"from_address": from_address, "subject": subject, "body": body}
