"""
Slack request signature verification.

Implements HMAC-SHA256 signature verification for Slack webhooks.
https://api.slack.com/authentication/verifying-requests-from-slack
"""

import hashlib
import hmac
import logging
import time

logger = logging.getLogger(__name__)


def verify_slack_signature(
    body: str,
    timestamp: str,
    signature: str,
    signing_secret: str,
) -> bool:
    """
    Verify Slack request signature using HMAC-SHA256.

    Args:
        body: Raw request body as string
        timestamp: X-Slack-Request-Timestamp header value
        signature: X-Slack-Signature header value
        signing_secret: Slack app signing secret

    Returns:
        True if signature is valid, False otherwise
    """
    # Check timestamp to prevent replay attacks (5 minute window)
    try:
        ts = int(timestamp)
        if abs(time.time() - ts) > 300:
            logger.warning(f"Slack timestamp too old: {ts}")
            return False
    except (ValueError, TypeError):
        logger.warning(f"Invalid Slack timestamp: {timestamp}")
        return False

    # Compute expected signature
    sig_basestring = f"v0:{timestamp}:{body}"
    expected_signature = (
        "v0="
        + hmac.new(
            signing_secret.encode("utf-8"),
            sig_basestring.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
    )

    # Constant-time comparison to prevent timing attacks
    is_valid = hmac.compare_digest(expected_signature, signature)

    if not is_valid:
        logger.warning("Slack signature verification failed")

    return is_valid


def extract_slack_headers(headers: dict) -> tuple[str, str]:
    """
    Extract Slack-specific headers from request.

    Args:
        headers: Request headers dict (case-insensitive keys)

    Returns:
        Tuple of (timestamp, signature)
    """
    # Normalize header keys to lowercase
    normalized = {k.lower(): v for k, v in headers.items()}

    timestamp = normalized.get("x-slack-request-timestamp", "")
    signature = normalized.get("x-slack-signature", "")

    return timestamp, signature


def is_slack_retry(headers: dict) -> bool:
    """
    Check if request is a Slack retry.

    Slack retries requests if it doesn't receive a 200 response within 3 seconds.
    For async processing, we should skip retries.

    Args:
        headers: Request headers dict

    Returns:
        True if this is a retry request
    """
    normalized = {k.lower(): v for k, v in headers.items()}
    return "x-slack-retry-num" in normalized
