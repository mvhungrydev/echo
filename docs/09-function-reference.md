# 09 - Function Reference

Per-function/constant reference for all source modules in ECHO. Updated as each Phase is completed.

---

## `src/layers/shared_utils/retry_config.py`

Module-level constants. No functions or classes — import the constants directly.

### `GENERAL_CONFIG`

| | |
|---|---|
| **Type** | `botocore.config.Config` |
| **Used by** | Lambda #1 (ingest) S3/SQS clients, Lambda #3 (insights) DynamoDB client |

```python
from retry_config import GENERAL_CONFIG

# Config values
GENERAL_CONFIG.retries          # {"max_attempts": 3, "mode": "adaptive"}
GENERAL_CONFIG.connect_timeout  # 3 (seconds)
GENERAL_CONFIG.read_timeout     # 5 (seconds)
```

---

### `BEDROCK_CONFIG`

| | |
|---|---|
| **Type** | `botocore.config.Config` |
| **Used by** | Lambda #2 (triage) Bedrock client |

```python
from retry_config import BEDROCK_CONFIG

# Config values
BEDROCK_CONFIG.retries          # {"max_attempts": 3, "mode": "adaptive"}
BEDROCK_CONFIG.connect_timeout  # 3 (seconds)
BEDROCK_CONFIG.read_timeout     # 10 (seconds)  ← longer than GENERAL_CONFIG
```

---

## `src/lambda_ingest/mime_parser.py`

### `parse_email(raw_bytes: bytes) -> dict`

Parses a raw `.eml` byte string into a flat dict. Handles multipart/alternative, base64, quoted-printable, RFC 2047 encoded headers, and display-name stripping automatically via `email.policy.default`.

| | |
|---|---|
| **Parameter** | `raw_bytes: bytes` — raw `.eml` content (e.g. from `s3.get_object()["Body"].read()`) |
| **Returns** | `dict` with exactly 3 keys, all `str`, never `None` |

**Return shape:**

```python
{
    "from_address": str,  # bare email address, display name stripped
    "subject":      str,  # RFC 2047 decoded
    "body":         str,  # plain text preferred; "" if no body part
}
```

**Sample — plain text email:**

```python
from mime_parser import parse_email

raw = b"""From: Jane Doe <jane@example.com>\r\nSubject: Hello\r\n\r\nHello world\r\n"""
result = parse_email(raw)
# {
#     "from_address": "jane@example.com",
#     "subject":      "Hello",
#     "body":         "Hello world\n",
# }
```

**Sample — attachment-only email (no body part):**

```python
result = parse_email(raw_attachment_only_bytes)
# {
#     "from_address": "sender@example.com",
#     "subject":      "See attached",
#     "body":         "",
# }
```

**Edge cases:**

| Scenario | Behaviour |
|---|---|
| Multipart/alternative (plain + HTML) | Returns the plain part; HTML is ignored |
| `Content-Transfer-Encoding: base64` | Decoded transparently by `.get_content()` |
| `Content-Transfer-Encoding: quoted-printable` | Decoded transparently by `.get_content()` |
| RFC 2047 encoded subject (e.g. non-ASCII) | Decoded by `policy.default` header handling |
| `From` header absent | `from_address == ""` |
| `Subject` header absent | `subject == ""` |
| No body part (attachment-only) | `body == ""`, no exception |