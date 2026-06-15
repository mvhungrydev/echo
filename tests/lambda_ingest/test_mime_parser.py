import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "..", "src", "lambda_ingest")
)

from email.message import EmailMessage
from mime_parser import parse_email

# %%


def build_eml(**kwargs) -> bytes:
    body = kwargs.pop("body", "Email body content not provided.")
    html_body = kwargs.pop("html_body", None)
    cte = kwargs.pop("cte", None)
    attachment_only = kwargs.pop("attachment_only", False)

    msg = EmailMessage()
    for header_name, value in kwargs.items():
        msg[header_name] = value

    if attachment_only:
        msg.set_content(b"binary data", maintype="application", subtype="octet-stream")
    else:
        msg.set_content(body, cte=cte)
        if html_body is not None:
            msg.add_alternative(html_body, subtype="html")

    return msg.as_bytes()


# %%

# %%


def test_simple_plain_text_email():
    # 1: simple plain text email -> body is the plain text
    pass


def test_multipart_alternative_returns_plain_body():
    # 2: plain+html -> body is the plain part
    pass


def test_base64_body_decoded():
    # 3: Content-Transfer-Encoding: base64 -> decoded to original text
    pass


def test_quoted_printable_body_decoded():
    # 4: Content-Transfer-Encoding: quoted-printable -> decoded to original text
    pass


def test_rfc2047_encoded_subject_decoded():
    # 5: RFC 2047 encoded-word subject -> decoded readable string
    pass


def test_from_header_strips_display_name():
    # 6: From: "Jane Doe" <jane@example.com> -> from_address == "jane@example.com"
    pass


def test_attachment_only_email_returns_empty_body():
    # 7: boundary - no body part -> body == "", no exception
    pass
