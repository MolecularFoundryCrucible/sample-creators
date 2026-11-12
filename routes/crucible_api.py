"""crucible-api calls that nano-crucible 3.3 has no public method for.

Everything here goes through the client's private `_request`, so it is the one module to
revisit when nano-crucible adds wrappers or changes that method.
"""

from routes.shared import cruc_client

# The API joins and CRC32C-verifies all parts inside the completion request.
COMPLETE_TIMEOUT_S = 120
STATUS_PAGE_LIMIT = 1000


def list_printers():
    """Printers crucible-api has seen a status heartbeat from, with live online state.

    Discovery only: a printer that has never been powered on won't appear.
    """
    return cruc_client._request("get", "/print/printers").get("printers", [])


def add_scientific_metadata(resource_mfid, metadata):
    """Set the scientific metadata of a resource that has none yet.

    datasets.create(scientific_metadata=...) writes it with PATCH, which needs edit rights the
    service account may lack on records it creates for users; POST only needs create rights.
    """
    return cruc_client._request("post", f"/resources/{resource_mfid}/metadata", json=metadata)


def multipart_initiate(dataset_mfid, filename, size, idempotency_key):
    return cruc_client._request(
        "post", f"/datasets/{dataset_mfid}/upload/multipart/initiate",
        retry=False, json={"filename": filename, "size": size},
        headers={"Idempotency-Key": idempotency_key},
    )


def multipart_sign_parts(dataset_mfid, upload_id, parts):
    # Signed URLs are bearer credentials, so the response body must never reach the logs.
    return cruc_client._request(
        "post", f"/datasets/{dataset_mfid}/upload/multipart/{upload_id}/parts",
        retry=False, log_body=False, json={"parts": parts},
    )


def multipart_status_page(dataset_mfid, upload_id, part_number_marker=0):
    return cruc_client._request(
        "get", f"/datasets/{dataset_mfid}/upload/multipart/{upload_id}",
        log_body=False, params={"limit": STATUS_PAGE_LIMIT, "part_number_marker": part_number_marker},
    )


def multipart_complete(dataset_mfid, upload_id, sha256_hash, crc32c):
    return cruc_client._request(
        "post", f"/datasets/{dataset_mfid}/upload/multipart/complete",
        retry=False, timeout=(10, COMPLETE_TIMEOUT_S),
        json={"upload_id": upload_id, "sha256_hash": sha256_hash, "crc32c": crc32c},
    )


def multipart_abort(dataset_mfid, upload_id):
    return cruc_client._request(
        "delete", f"/datasets/{dataset_mfid}/upload/multipart/{upload_id}", retry=False,
    )


def request_ingestion(file_mfid, requested=True, ingestion_class=None):
    """Record an ingestion decision for an uploaded file.

    Every call creates a new ingestion request on the server, so callers must not retry it.
    """
    params = {"status": "requested" if requested else "not_requested"}
    if requested and ingestion_class:
        params["ingestion_class"] = ingestion_class
    return cruc_client._request("post", f"/files/{file_mfid}/ingest", retry=False, params=params)
