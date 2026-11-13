"""In-memory stand-in for the Crucible client (from manual-synthesis-ui backend/tests at c25ae5c).

Every call is checked against the real nano-crucible method signature, so a
renamed or misnamed argument fails here the same way it would in production.
"""
import inspect
import itertools
import os

import requests
from crucible.resources.datasets import DatasetOperations
from crucible.resources.samples import SampleOperations

_ids = itertools.count(1)


def _new_id(prefix):
    return f"{prefix}{next(_ids):025d}"


def _http_error(status):
    response = requests.Response()
    response.status_code = status
    return requests.exceptions.HTTPError(f"{status} error", response=response)


class _Checked:
    _real = None

    def __getattribute__(self, name):
        attr = object.__getattribute__(self, name)
        real_cls = object.__getattribute__(self, "_real")
        if callable(attr) and not name.startswith("_") and real_cls is not None:
            sig = inspect.signature(getattr(real_cls, name))

            def checked(*args, **kwargs):
                sig.bind(None, *args, **kwargs)
                return attr(*args, **kwargs)
            return checked
        return attr


class FakeSamples(_Checked):
    _real = SampleOperations

    def __init__(self, store):
        self.s = store

    def create(self, sample, scientific_metadata=None, parents=None, children=None):
        uid = _new_id("S")
        rec = {"unique_id": uid, "sample_name": sample.sample_name, "sample_type": sample.sample_type,
               "project_id": sample.project_id, "description": sample.description, "timestamp": sample.timestamp}
        self.s["samples"][uid] = rec
        return dict(rec)

    def get(self, sample_mfid, include_links=False, include_metadata=False, include_owner=True,
            include_datasets=True):
        if sample_mfid not in self.s["samples"]:
            raise _http_error(404)
        return dict(self.s["samples"][sample_mfid])

    def list(self, dataset_mfid=None, parent_mfid=None, limit=100, project_id=None, **kwargs):
        out = list(self.s["samples"].values())
        if dataset_mfid:
            kids = {s for s, d in self.s["sample_datasets"] if d == dataset_mfid}
            out = [r for r in out if r["unique_id"] in kids]
        if parent_mfid:
            kids = {c for p, c in self.s["links"] if p == parent_mfid}
            out = [r for r in out if r["unique_id"] in kids]
        if project_id:
            out = [r for r in out if r["project_id"] == project_id]
        for key in ("sample_name", "sample_type"):
            if key in kwargs:
                out = [r for r in out if r[key] == kwargs[key]]
        return [dict(r) for r in out]

    def link(self, parent_mfid, child_mfid, relationship_type=None):
        self.s["links"].append((parent_mfid, child_mfid))
        return {}

    def link_dataset(self, sample_mfid, dataset_mfid):
        if sample_mfid in self.s["fail_link"]:
            raise _http_error(403)
        self.s["sample_datasets"].append((sample_mfid, dataset_mfid))
        return {}


class FakeDatasets(_Checked):
    _real = DatasetOperations

    def __init__(self, store):
        self.s = store

    def create(self, dataset, scientific_metadata=None, keywords=None, **kwargs):
        uid = _new_id("D")
        self.s["datasets"][uid] = {"unique_id": uid, "dataset_name": dataset.dataset_name,
                                   "measurement": dataset.measurement, "project_id": dataset.project_id,
                                   "keywords": keywords, "scientific_metadata": None}
        return {"created_record": {"unique_id": uid}}

    def get(self, dataset_mfid, include_metadata=False, include_links=False, include_owner=True):
        if dataset_mfid not in self.s["datasets"]:
            raise _http_error(404)
        rec = dict(self.s["datasets"][dataset_mfid])
        if not include_metadata:
            rec.pop("scientific_metadata")
        return rec

    def list(self, sample_mfid=None, include_metadata=False, limit=100, **kwargs):
        if sample_mfid is None:
            out = [self.get(d, include_metadata=include_metadata) for d in self.s["datasets"]]
        else:
            out = []
            for s, d in self.s["sample_datasets"]:
                if s == sample_mfid:
                    out.append(self.get(d, include_metadata=include_metadata))
        for key in ("project_id", "measurement"):
            if key in kwargs:
                out = [r for r in out if r.get(key) == kwargs[key]]
        return out

    def link_sample(self, dataset_mfid, sample_mfid):
        if (sample_mfid, dataset_mfid) not in self.s["sample_datasets"]:
            self.s["sample_datasets"].append((sample_mfid, dataset_mfid))
        return {}

    def link(self, parent_mfid, child_mfid, relationship_type=None):
        self.s["dataset_links"].append((parent_mfid, child_mfid))
        return {}

    def list_children(self, parent_mfid, limit=100, **kwargs):
        children = [child for parent, child in self.s["dataset_links"] if parent == parent_mfid]
        return [self.get(child, include_metadata=kwargs.get("include_metadata", False)) for child in children]

    def update_scientific_metadata(self, resource_mfid, metadata, overwrite=False):
        if not self.s["can_edit"]:
            raise _http_error(403)
        if overwrite:
            self.s["datasets"][resource_mfid]["scientific_metadata"] = metadata
        else:
            current = self.s["datasets"][resource_mfid].get("scientific_metadata") or {}
            self.s["datasets"][resource_mfid]["scientific_metadata"] = {**current, **metadata}
        return {}

    def add_file(self, dataset_mfid, file_path, ingestion_class=None, wait_for_ingestion_response=False,
                 multipart=True, chunk_size_mb=None, max_workers=None, skip_ingestion=False,
                 upload_protocol=None, progress=None, replace=False):
        name = os.path.basename(file_path)
        files = self.s["files"].setdefault(dataset_mfid, [])
        if any(f["filename"] == name for f in files):
            raise Exception("FileExistsWithDifferentContent")
        with open(file_path, "rb") as fh:
            files.append({"mfid": _new_id("F"), "filename": name, "size": len(fh.read()),
                          "skip_ingestion": skip_ingestion})
        return {"associated_file": files[-1], "ingestion_request": None}

    def list_files(self, dataset_mfid):
        return [dict(f) for f in self.s["files"].get(dataset_mfid, [])]

    def get_download_links(self, dataset_mfid, disposition=None):
        return {f["mfid"]: f"https://storage.example/{f['filename']}" for f in self.s["files"].get(dataset_mfid, [])}


class FakePrint:
    def __init__(self, store):
        self.s = store

    def barcode(self, printer_id, mfid, name):
        self.s["prints"].append((printer_id, mfid, name))
        return self.s["print_result"]


def install(client):
    """Swap the client's resources for fakes. Returns (store, restore)."""
    saved = {name: client.__dict__.get(name) for name in ("samples", "datasets", "print", "_request")}
    store = {"samples": {}, "links": [], "datasets": {}, "sample_datasets": [], "files": {}, "prints": [],
             "fail_link": set(), "can_edit": True, "print_result": {"status": "ok"},
             "dataset_links": [], "ingestion_requests": {}}
    client.samples = FakeSamples(store)
    client.datasets = FakeDatasets(store)
    client.print = FakePrint(store)

    def _request(method, path, **kwargs):
        if method == "post" and path.endswith("/metadata") and not kwargs.get("params"):
            uid = path.split("/")[2]
            records = store["datasets"] if uid in store["datasets"] else store["samples"]
            if records[uid].get("scientific_metadata"):
                raise _http_error(409)
            records[uid]["scientific_metadata"] = kwargs["json"]
            return {}
        if method == "get" and path == "/ingestion_requests":
            return {"items": store["ingestion_requests"].get(kwargs.get("params", {}).get("dataset_mfid"), [])}
        if method == "get" and path == "/print/printers":
            return {"printers": [{"printer_id": "b30-113", "online": True}]}
        raise AssertionError(f"unexpected request {method} {path}")
    client._request = _request

    def restore():
        for name, value in saved.items():
            if value is None:
                client.__dict__.pop(name, None)
            else:
                setattr(client, name, value)
    return store, restore
