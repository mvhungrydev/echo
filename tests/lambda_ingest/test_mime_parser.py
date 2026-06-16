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

from_address = "Jane Doe <jane@example.com>"
subject = "Test Email"
text_body = "This is a test email."


def test_simple_plain_text_email():
    # 1: simple plain text email -> returns correct from_address, subject, body
    test_mail = build_eml(
        From=from_address,
        Subject=subject,
        body=text_body,
    )
    result = parse_email(test_mail)
    assert result["from_address"] == "jane@example.com"
    assert result["subject"] == "Test Email"
    assert result["body"] == "This is a test email.\n"


def test_multipart_alternative_returns_plain_body():
    # 2: multipart/alternative with text and HTML -> returns text body
    html_body = "<html><body><p>This is a test email.</p></body></html>"
    test_mail = build_eml(
        From=from_address,
        Subject=subject,
        body=text_body,
        html_body=html_body,
    )
    result = parse_email(test_mail)
    assert result["body"] == "This is a test email.\n"


def test_base64_body_decoded():
    # 3: base64 encoded body -> decoded text body
    test_mail = build_eml(
        From=from_address,
        Subject=subject,
        body=text_body,
        cte="base64",
    )
    result = parse_email(test_mail)
    assert result["body"] == "This is a test email.\n"


def test_quoted_printable_body_decoded():
    # 4: quoted-printable encoded body -> decoded text body
    test_mail = build_eml(
        From=from_address,
        Subject=subject,
        body=text_body,
        cte="quoted-printable",
    )
    result = parse_email(test_mail)
    assert result["body"] == "This is a test email.\n"


def test_rfc2047_encoded_subject_decoded():
    # 5: RFC 2047 encoded-word subject -> decoded readable string
    encoded_subject = "Héllo Café ☕"
    raw = build_eml(From=from_address, Subject=encoded_subject, body=text_body)
    result = parse_email(raw)
    assert result["subject"] == encoded_subject


def test_from_header_strips_display_name():
    # 6: From: "Jane Doe" <jane@example.com> -> from_address == "jane@example.com"
    test_mail = build_eml(
        From="Jane Doe <jane@example.com>", Subject=subject, body=text_body
    )
    result = parse_email(test_mail)
    assert result["from_address"] == "jane@example.com"


def test_attachment_only_email_returns_empty_body():
    # 7: boundary - no body part -> body == "", no exception
    test_mail = build_eml(
        From=from_address, Subject=subject, body=text_body, attachment_only=True
    )
    result = parse_email(test_mail)
    assert result["body"] == ""
