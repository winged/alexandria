import pytest
from django.urls import reverse
from rest_framework.status import (
    HTTP_200_OK,
    HTTP_201_CREATED,
    HTTP_400_BAD_REQUEST,
    HTTP_403_FORBIDDEN,
)

from alexandria.core.models import File


@pytest.mark.parametrize("allow_anon", [True, False])
@pytest.mark.parametrize("method", ["post", "patch"])
def test_anonymous_writing(db, document, client, settings, user, allow_anon, method):
    settings.ALLOW_ANONYMOUS_WRITE = allow_anon
    if not allow_anon:
        settings.REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"] = [
            "rest_framework.permissions.IsAuthenticatedOrReadOnly",
        ]

    data = {"data": {"type": "documents", "attributes": {"title": "winstonsmith"}}}

    url = reverse("document-list")

    if method == "patch":
        data["data"]["id"] = str(document.pk)
        url = reverse("document-detail", args=[document.pk])

    resp = getattr(client, method)(url, data=data)
    assert (
        resp.status_code == HTTP_201_CREATED or HTTP_200_OK
        if allow_anon
        else HTTP_403_FORBIDDEN
    )


@pytest.mark.parametrize(
    "f_type,original,status_code",
    [
        (File.ORIGINAL, False, HTTP_201_CREATED),
        (File.THUMBNAIL, True, HTTP_201_CREATED),
        (File.THUMBNAIL, False, HTTP_400_BAD_REQUEST),
        (File.ORIGINAL, True, HTTP_400_BAD_REQUEST),
        (None, False, HTTP_400_BAD_REQUEST),
    ],
)
def test_file_validation(
    admin_client, document_factory, file_factory, f_type, original, status_code
):
    doc = document_factory()

    data = {
        "data": {
            "type": "files",
            "attributes": {"name": "file.pdf"},
            "relationships": {
                "document": {"data": {"id": str(doc.pk), "type": "documents"}},
            },
        }
    }
    if f_type:
        data["data"]["attributes"]["type"] = f_type
    if original:
        file = file_factory(document=doc, name="file2.pdf")
        data["data"]["relationships"]["original"] = {
            "data": {"id": str(file.pk), "type": "files"},
        }

    url = reverse("file-list")

    resp = admin_client.post(url, data=data)
    assert resp.status_code == status_code


@pytest.mark.parametrize(
    "enabled,method,correct_bucket,supported_mime,is_thumb,status_code",
    [
        (True, "head", True, True, False, HTTP_200_OK),
        (True, "post", True, True, False, HTTP_201_CREATED),
        (True, "post", True, False, False, HTTP_200_OK),
        (True, "post", True, True, False, HTTP_400_BAD_REQUEST),
        (True, "post", False, True, False, HTTP_200_OK),
        (True, "post", True, True, True, HTTP_200_OK),
        (False, "post", True, True, False, HTTP_403_FORBIDDEN),
    ],
)
def test_hook_view(
    preview_cache_dir,
    admin_client,
    minio_mock,
    document_factory,
    settings,
    enabled,
    method,
    correct_bucket,
    supported_mime,
    is_thumb,
    status_code,
):
    url = reverse("hook")
    data = {
        "EventName": "s3:ObjectCreated:Put",
        "Key": "alexandria-media/218b2504-1736-476e-9975-dc5215ef4f01_test.png",
        "Records": [
            {
                "eventVersion": "2.0",
                "eventSource": "minio:s3",
                "awsRegion": "",
                "eventTime": "2020-07-17T06:38:23.221Z",
                "eventName": "s3:ObjectCreated:Put",
                "userIdentity": {"principalId": "minio"},
                "requestParameters": {
                    "accessKey": "minio",
                    "region": "",
                    "sourceIPAddress": "172.20.0.1",
                },
                "responseElements": {
                    "x-amz-request-id": "162276DB8350E531",
                    "x-minio-deployment-id": "5db7c8da-79cb-4d3a-8d40-189b51ca7aa6",
                    "x-minio-origin-endpoint": "http://172.20.0.2:9000",
                },
                "s3": {
                    "s3SchemaVersion": "1.0",
                    "configurationId": "Config",
                    "bucket": {
                        "name": "alexandria-media",
                        "ownerIdentity": {"principalId": "minio"},
                        "arn": "arn:aws:s3:::alexandria-media",
                    },
                    "object": {
                        "key": "218b2504-1736-476e-9975-dc5215ef4f01_test.png",
                        "size": 299758,
                        "eTag": "af1421c17294eed533ec99eb82b468fb",
                        "contentType": "application/pdf",
                        "userMetadata": {"content-type": "application/pdf"},
                        "versionId": "1",
                        "sequencer": "162276DB83A9F895",
                    },
                },
                "source": {
                    "host": "172.20.0.1",
                    "port": "",
                    "userAgent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) QtWebEngine/5.15.0 Chrome/80.0.3987.163 Safari/537.36",
                },
            }
        ],
    }

    if not enabled:
        settings.ENABLE_THUMBNAIL_GENERATION = False

    if status_code == HTTP_201_CREATED:
        doc = document_factory()
        File.objects.create(
            document=doc, name="test.png", pk="218b2504-1736-476e-9975-dc5215ef4f01"
        )
        assert File.objects.count() == 1

    if not supported_mime:
        doc = document_factory()
        File.objects.create(
            document=doc,
            name="test.unsupported",
            pk="218b2504-1736-476e-9975-dc5215ef4f01",
        )
        assert File.objects.count() == 1
        data["Records"][0]["s3"]["object"][
            "name"
        ] = "218b2504-1736-476e-9975-dc5215ef4f01_test.unsupported"

    if is_thumb:
        doc = document_factory()
        File.objects.create(
            document=doc,
            name="test.png",
            pk="218b2504-1736-476e-9975-dc5215ef4f01",
            type=File.THUMBNAIL,
        )
        assert File.objects.count() == 1

    if not correct_bucket:
        data["Records"][0]["s3"]["bucket"]["name"] = "wrong-bucket"

    resp = getattr(admin_client, method)(url, data=data if method == "post" else None)
    assert resp.status_code == status_code

    if status_code == HTTP_201_CREATED:
        assert File.objects.count() == 2
        assert File.objects.filter(type=File.THUMBNAIL).count() == 1
        orig = File.objects.get(type=File.ORIGINAL)
        thumb = File.objects.get(type=File.THUMBNAIL)
        assert thumb.original == orig

    if is_thumb:
        assert File.objects.count() == 1

    assert len(list(settings.THUMBNAIL_CACHE_DIR.iterdir())) == 0
