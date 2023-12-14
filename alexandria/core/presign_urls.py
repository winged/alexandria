import hashlib
from typing import Optional, Tuple

from django.conf import settings
from django.utils import timezone
from django.utils.http import urlsafe_base64_encode
from rest_framework_json_api.relations import reverse


def make_signature_components(
    pk: str, hostname: str, expires: Optional[int] = None, scheme: str = "http"
) -> Tuple[str, int, str]:
    """Make the components used to sign and verify the download_url.

    If `expires` is provided the components are called for the verification step.

    Otherwise expiry is calculated and returned
    """
    if not expires:
        expires = int(
            (
                timezone.now()
                + timezone.timedelta(seconds=settings.ALEXANDRIA_DOWNLOAD_URL_LIFETIME)
            ).timestamp()
        )
    download_path = reverse("file-download", args=[pk])
    host = f"{scheme}://{hostname}"
    url = f"{host.strip('/')}{download_path}"
    token = f"{url}{expires}{settings.SECRET_KEY}"
    hash = hashlib.shake_256(token.encode())
    # Django's base64 encoder strips padding and ascii-decodes the output
    signature = urlsafe_base64_encode(hash.digest(32))
    return url, expires, signature


def verify_signed_components(pk, hostname, expires, scheme, token_sig):
    """Verify a presigned download URL.

    It tests against the expiry: raises a TimeoutError
    It tests against signature integrity: raises an AssertionError

    returns True otherwise.
    """
    now = timezone.now()
    host, expires, signature = make_signature_components(pk, hostname, expires, scheme)

    if int(now.timestamp()) > expires:
        raise TimeoutError()
    try:
        assert token_sig == signature
    except AssertionError:
        raise

    return True
