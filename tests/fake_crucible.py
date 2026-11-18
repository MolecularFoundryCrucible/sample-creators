"""In-memory stand-in for the Crucible client (nano-crucible 4.0.1 contract).

Every call is checked against the real nano-crucible 4.0.1 method signature,
removed-method / removed-parameter decorators, and model/update guards so legacy
v3 calls fail here with RemovedError / TypeError / DeprecationWarning just like
they do in production.
"""
import inspect
import itertools
import os
import warnings

import requests
from crucible.client import CrucibleClient
from crucible.errors import CrucibleAPIError, RemovedError
from crucible.models import Dataset, Sample
from crucible.resources.datasets import DatasetOperations
from crucible.resources.files import FileOperations
from crucible.resources.printer import PrintOperations
from crucible.resources.projects import ProjectOperations
from crucible.resources.samples import SampleOperations
from crucible.resources.users import UserOperations
from crucible.utils.deprecation import removed_message
from crucible.utils.identifiers import IdentifierNotFoundError, classify_user_reference, is_mfid

_ids = itertools.count(1)
_REQUEST_SIG = inspect.signature(CrucibleClient._request)


def _new_id(prefix):
    return f"{prefix.lower()}{next(_ids):025d}"


def _http_error(status):
    response = requests.Response()
    response.status_code = status
    return CrucibleAPIError(f"{status} error", response=response, status=status)


class _Checked:
    _real = None

    def __getattribute__(self, name):
        attr = object.__getattribute__(self, name)
        real_cls = object.__getattribute__(self, "_real")
        if callable(attr) and not name.startswith("_") and real_cls is not None:
            real_attr = getattr(real_cls, name)
            removed_params = getattr(real_attr, "__removed_parameters__", ())
            deprecated_params = getattr(attr, "_deprecated_parameters", ())
            sig = inspect.signature(real_attr)

            def checked(*args, **kwargs):
                for old_name, new_name in removed_params:
                    if old_name in kwargs:
                        raise RemovedError(removed_message(
                            f"The '{old_name}' keyword of {real_attr.__qualname__}()",
                            f"use '{new_name}' instead.",
                        ))
                for old_name, new_name in deprecated_params:
                    if old_name in kwargs:
                        if new_name in kwargs:
                            raise TypeError(
                                f"Pass either '{new_name}' or deprecated '{old_name}', not both."
                            )
                        warnings.warn(
                            f"The '{old_name}' keyword is deprecated; use '{new_name}' instead.",
                            DeprecationWarning,
                            stacklevel=2,
                        )
                        kwargs[new_name] = kwargs.pop(old_name)
                sig.bind(None, *args, **kwargs)
                return attr(*args, **kwargs)
            return checked
        return attr

    def __getattr__(self, name):
        real_cls = object.__getattribute__(self, "_real")
        if real_cls is not None and hasattr(real_cls, name):
            real_attr = getattr(real_cls, name)
            if hasattr(real_attr, "__removed__"):
                return real_attr.__get__(self, type(self))
        raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}")


class FakeSamples(_Checked):
    _real = SampleOperations

    def __init__(self, store):
        self.s = store

    def create(self, sample=None, scientific_metadata=None, parents=None, children=None, **kwargs):
        if isinstance(sample, dict):
            sample = Sample.model_validate(sample)
        if sample is None or not isinstance(sample, Sample):
            if sample is not None:
                raise TypeError(
                    f"Expected a Sample model, got {type(sample).__name__}. "
                    "Use: samples.create(Sample(sample_name=..., project_id=...))"
                )
            if kwargs:
                raise RemovedError(removed_message(
                    "Passing keyword arguments to samples.create()",
                    "pass a Sample model instead: samples.create(Sample(...)).",
                ))
            raise ValueError("Pass a Sample model: samples.create(Sample(...))")
        if kwargs:
            raise TypeError(f"samples.create() got an unexpected keyword argument {next(iter(kwargs))!r}")
        if sample.owner_orcid is not None:
            raise RemovedError(removed_message(
                "Setting Sample.owner_orcid when creating a sample",
                "set Sample.owner to an ORCID, MFID, username, or email instead.",
            ))

        uid = sample.unique_id or _new_id("S")
        owner_obj = self.s["users"].get(sample.owner) or (
            {"unique_id": sample.owner, "first_name": "", "last_name": ""} if sample.owner else None
        )
        rec = {
            "unique_id": uid,
            "sample_name": sample.sample_name,
            "sample_type": sample.sample_type,
            "project_id": sample.project_id,
            "description": sample.description,
            "timestamp": sample.timestamp,
            "owner_orcid": sample.owner if sample.owner and sample.owner.startswith("0000-") else None,
            "owner": owner_obj,
            "scientific_metadata": dict(scientific_metadata) if scientific_metadata else None,
        }
        self.s["samples"][uid] = rec
        for p in parents or []:
            self.link(p["unique_id"], uid)
        for chd in children or []:
            self.link(uid, chd["unique_id"])
        out = dict(rec)
        out.pop("scientific_metadata", None)
        return out

    def get(self, sample_mfid, include_links=False, include_metadata=False, include_owner=True,
            include_datasets=False):
        if not is_mfid(sample_mfid):
            raise ValueError("sample_mfid must be an exact 26-character MFID.")
        if include_datasets:
            warnings.warn(
                "include_datasets is deprecated by the Crucible API; use include_links=True, "
                "or client.datasets.list(sample_mfid=...) for the linked datasets.",
                DeprecationWarning,
                stacklevel=2,
            )
        if sample_mfid not in self.s["samples"]:
            raise _http_error(404)
        rec = dict(self.s["samples"][sample_mfid])
        if not include_metadata:
            rec.pop("scientific_metadata", None)
        if not include_owner:
            rec.pop("owner", None)
        if include_links:
            rec["links"] = (
                [{"unique_id": p, "resource_type": "sample", "direction": "source", "relationship_type": None}
                 for p, c in self.s["links"] if c == sample_mfid]
                + [{"unique_id": c, "resource_type": "sample", "direction": "target", "relationship_type": None}
                   for p, c in self.s["links"] if p == sample_mfid]
                + [{"unique_id": d, "resource_type": "dataset", "direction": "undirected", "relationship_type": None}
                   for s, d in self.s["sample_datasets"] if s == sample_mfid]
            )
        if include_datasets:
            rec["datasets"] = [
                {k: v for k, v in self.s["datasets"][d].items() if k != "scientific_metadata"}
                for s, d in self.s["sample_datasets"]
                if s == sample_mfid and d in self.s["datasets"]
            ]
        else:
            rec["datasets"] = None
        return rec

    def list(self, dataset_mfid=None, parent_mfid=None, include_metadata=False, include_links=False,
             include_owner=False, limit=100, offset=0, accessible_to_user=None, accessible_to_project=None,
             project_id=None, project_mfid=None, project_scope=None, sort=None, direction=None,
             visibility=None, affiliation=None, include_total=None, creation_time_gte=None,
             creation_time_lte=None, modification_time_gte=None, modification_time_lte=None,
             cursor=None, mfid=None, **kwargs):
        if "unique_id" in kwargs and kwargs["unique_id"] is not None:
            raise RemovedError(removed_message(
                "Filtering by unique_id",
                "pass mfid=... or call .get(mfid) instead.",
            ))
        if offset and not (parent_mfid and dataset_mfid is None):
            raise RemovedError(removed_message(
                "The 'offset' argument of samples.list()",
                "/samples uses keyset pagination; pass the previous result's next_cursor as cursor instead.",
            ))
        out = list(self.s["samples"].values())
        if mfid is not None:
            wanted = {mfid} if isinstance(mfid, str) else set(mfid)
            out = [r for r in out if r["unique_id"] in wanted]
        if dataset_mfid:
            kids = {s for s, d in self.s["sample_datasets"] if d == dataset_mfid}
            out = [r for r in out if r["unique_id"] in kids]
        if parent_mfid:
            kids = {c for p, c in self.s["links"] if p == parent_mfid}
            out = [r for r in out if r["unique_id"] in kids]
        if project_id:
            out = [r for r in out if r["project_id"] == project_id]
        for key in ("sample_name", "sample_type"):
            if kwargs.get(key) is not None:
                out = [r for r in out if r.get(key) == kwargs[key]]
        # Production's nested child listing ignores include_metadata and is shallow.
        # Match that contract: map-derived children need a single-resource detail read.
        shallow = (parent_mfid and not dataset_mfid) or not include_metadata
        result = []
        for r in out:
            item = dict(r)
            if shallow:
                item.pop("scientific_metadata", None)
            if not include_owner:
                item.pop("owner", None)
            result.append(item)
        if offset:
            result = result[offset:]
        return result[:limit] if isinstance(limit, int) else result

    def list_children(self, parent_mfid, limit=100, offset=0, relationship_type=None, cursor=None, **kwargs):
        # crucible-api v4.0.0 GET /samples/{parent_sample_mfid}/children ignores sample_type
        # query parameters and returns shallow child records without scientific_metadata.
        return self.list(parent_mfid=parent_mfid, limit=limit, offset=offset)

    def update(self, sample_mfid, sample_name=None, description=None, timestamp=None, *,
               sample_type=None, parents=None, children=None, **removed):
        if removed:
            replacements = {
                "owner_orcid": "use client.samples.transfer_ownership() instead.",
                "owner_id": "use client.samples.transfer_ownership() instead.",
                "owner_user_id": "use client.samples.transfer_ownership() instead.",
                "project_id": "use client.samples.reassign_project() instead.",
                "public": "use set_public() or set_private() instead.",
                "date_created": "creation_time is assigned by the server; drop it.",
                "creation_date": "creation_time is assigned by the server; drop it.",
            }
            name = next(iter(removed))
            if name not in replacements:
                raise TypeError(f"samples.update() got an unexpected keyword argument {name!r}")
            raise RemovedError(removed_message(f"The '{name}' argument of samples.update()", replacements[name]))
        if sample_mfid not in self.s["samples"]:
            raise _http_error(404)
        rec = self.s["samples"][sample_mfid]
        for key, value in (("sample_name", sample_name), ("sample_type", sample_type),
                           ("description", description), ("timestamp", timestamp)):
            if value is not None:
                rec[key] = value
        for p in parents or []:
            self.link(p["unique_id"], sample_mfid)
        for chd in children or []:
            self.link(sample_mfid, chd["unique_id"])
        return self.get(sample_mfid)

    def search(self, q, project_id=None, limit=20, owner_ref=None):
        term = str(q or "").strip()
        if len(term) < 3:
            raise _http_error(422)
        needle = term.lower()
        out = [
            dict(r) for r in self.s["samples"].values()
            if needle in (r.get("sample_name") or "").lower()
            and (project_id is None or r.get("project_id") == project_id)
        ]
        for item in out:
            item.pop("scientific_metadata", None)
        return out[:limit]

    def link(self, parent_mfid, child_mfid, relationship_type=None):
        self.s["links"].append((parent_mfid, child_mfid))
        return {}

    def link_dataset(self, sample_mfid, dataset_mfid):
        if sample_mfid in self.s["fail_link"]:
            raise _http_error(403)
        if (sample_mfid, dataset_mfid) not in self.s["sample_datasets"]:
            self.s["sample_datasets"].append((sample_mfid, dataset_mfid))
        return {}


class FakeDatasets(_Checked):
    _real = DatasetOperations

    def __init__(self, store):
        self.s = store

    def create(self, dataset, scientific_metadata=None, keywords=None, files=None,
               upload_files=True, files_to_upload=None, ingestor=None, verbose=False,
               wait_for_ingestion_response=False, skip_ingestion=False):
        if files_to_upload is not None:
            raise RemovedError(removed_message(
                "The 'files_to_upload' keyword of datasets.create()", "use 'files' instead."))
        if isinstance(dataset, dict):
            dataset = Dataset.model_validate(dataset)
        if not isinstance(dataset, Dataset):
            raise TypeError(f"Expected a Dataset model, got {type(dataset).__name__}.")
        if dataset.owner_orcid is not None:
            raise RemovedError(removed_message(
                "Setting Dataset.owner_orcid when creating a dataset",
                "set Dataset.owner to an ORCID, MFID, username, or email instead."))
        if (dataset.instrument_name is not None
                and dataset.instrument_id is None
                and dataset.instrument_mfid is None):
            raise RemovedError(removed_message(
                "Identifying a dataset's instrument by instrument_name",
                "names may repeat, so set instrument_mfid or instrument_id instead."))

        uid = dataset.unique_id or _new_id("D")
        owner_obj = self.s["users"].get(dataset.owner) or (
            {"unique_id": dataset.owner, "first_name": "", "last_name": ""} if dataset.owner else None
        )
        stored_meta = dict(scientific_metadata) if scientific_metadata else None
        self.s["datasets"][uid] = {
            "unique_id": uid,
            "dataset_name": dataset.dataset_name,
            "data_type": dataset.data_type,
            "data_format": dataset.data_format,
            "measurement": dataset.measurement,
            "project_id": dataset.project_id,
            "instrument_mfid": dataset.instrument_mfid,
            "instrument_id": dataset.instrument_id,
            "timestamp": dataset.timestamp,
            "owner_orcid": dataset.owner if dataset.owner and dataset.owner.startswith("0000-") else None,
            "owner": owner_obj,
            "keywords": list(keywords or []),
            "scientific_metadata": stored_meta,
        }
        file_results = [
            self.add_file(uid, f, ingestion_class=ingestor, skip_ingestion=skip_ingestion)
            for f in (files or [])
        ]
        created_record = {k: v for k, v in self.s["datasets"][uid].items() if k != "scientific_metadata"}
        scimd_record = {"unique_id": uid, "scientific_metadata": dict(stored_meta)} if stored_meta else None
        return {
            "created_record": created_record,
            "scientific_metadata_record": scimd_record,
            "dataset_mfid": uid,
            "files": file_results,
        }

    def get(self, dataset_mfid, include_metadata=False, include_links=False, include_owner=True):
        if not is_mfid(dataset_mfid):
            raise ValueError("dataset_mfid must be an exact 26-character MFID.")
        if dataset_mfid not in self.s["datasets"]:
            raise _http_error(404)
        rec = dict(self.s["datasets"][dataset_mfid])
        if not include_metadata:
            rec.pop("scientific_metadata", None)
        if not include_owner:
            rec.pop("owner", None)
        if include_links:
            rec["links"] = [
                {"unique_id": s, "resource_type": "sample", "relationship": "associated",
                 "direction": "undirected", "relationship_type": None}
                for s, d in self.s["sample_datasets"] if d == dataset_mfid
            ]
        return rec

    def list(self, sample_mfid=None, include_metadata=False, include_links=False, include_owner=False,
             limit=100, offset=0, accessible_to_user=None, accessible_to_project=None,
             instrument_mfid=None, instrument_id=None, project_id=None, project_mfid=None,
             project_scope=None, sort=None, direction=None, visibility=None, affiliation=None,
             include_total=None, creation_time_gte=None, creation_time_lte=None,
             modification_time_gte=None, modification_time_lte=None, cursor=None, mfid=None, **kwargs):
        if "unique_id" in kwargs and kwargs["unique_id"] is not None:
            raise RemovedError(removed_message(
                "Filtering by unique_id",
                "pass mfid=... or call .get(mfid) instead.",
            ))
        if "instrument_name" in kwargs and kwargs["instrument_name"] is not None:
            raise RemovedError(removed_message(
                "Filtering datasets by instrument_name",
                "pass instrument_mfid or instrument_id instead.",
            ))
        if offset:
            raise RemovedError(removed_message(
                "The 'offset' argument of datasets.list()",
                "/datasets uses keyset pagination; pass the previous result's next_cursor as cursor instead.",
            ))
        if sample_mfid is None:
            ids = list(self.s["datasets"])
        else:
            ids = [d for s, d in self.s["sample_datasets"] if s == sample_mfid and d in self.s["datasets"]]
        if mfid is not None:
            wanted = {mfid} if isinstance(mfid, str) else set(mfid)
            ids = [d for d in ids if d in wanted]
        out = [
            self.get(d, include_metadata=include_metadata, include_links=include_links,
                     include_owner=include_owner)
            for d in ids
        ]
        if project_id is not None:
            out = [r for r in out if r.get("project_id") == project_id]
        if instrument_mfid is not None:
            out = [r for r in out if r.get("instrument_mfid") == instrument_mfid]
        if instrument_id is not None:
            out = [r for r in out if r.get("instrument_id") == instrument_id]
        for key in ("measurement", "data_type", "dataset_name"):
            if kwargs.get(key) is not None:
                out = [r for r in out if r.get(key) == kwargs[key]]
        return out[:limit] if isinstance(limit, int) else out

    def update(self, dataset_mfid, **updates):
        if "public" in updates:
            raise RemovedError(removed_message(
                "The 'public' field of datasets.update()", "use set_public() or set_private() instead."))
        instrument_fields = sorted({"instrument_id", "instrument_name"} & updates.keys())
        if instrument_fields:
            raise RemovedError(removed_message(
                f"The {' and '.join(repr(f) for f in instrument_fields)} field of datasets.update()",
                "use assign_instrument() instead."))
        response_only = {"capabilities", "instrument", "project"} & updates.keys()
        if response_only:
            raise ValueError(f"Dataset fields are response-only: {', '.join(sorted(response_only))}.")
        if dataset_mfid not in self.s["datasets"]:
            raise _http_error(404)
        self.s["datasets"][dataset_mfid].update(updates)
        return self.get(dataset_mfid)

    def link_sample(self, dataset_mfid, sample_mfid):
        if sample_mfid in self.s["fail_link"]:
            raise _http_error(403)
        if (sample_mfid, dataset_mfid) not in self.s["sample_datasets"]:
            self.s["sample_datasets"].append((sample_mfid, dataset_mfid))
        return {}

    def link(self, parent_mfid, child_mfid, relationship_type=None):
        self.s["dataset_links"].append((parent_mfid, child_mfid))
        return {}

    def list_children(self, parent_mfid, limit=100, offset=0, relationship_type=None, cursor=None, **kwargs):
        children = [child for parent, child in self.s["dataset_links"] if parent == parent_mfid]
        # The v3/v4 child-list response is DatasetRead and does not honor the client's
        # include_metadata option. Match that omission; map code must fetch details.
        return [self.get(child) for child in children]

    def get_scientific_metadata(self, resource_mfid):
        if resource_mfid not in self.s["datasets"]:
            raise _http_error(404)
        return {
            "unique_id": resource_mfid,
            "scientific_metadata": dict(self.s["datasets"][resource_mfid].get("scientific_metadata") or {}),
        }

    def update_scientific_metadata(self, resource_mfid, metadata, overwrite=False):
        if not self.s["can_edit"]:
            raise _http_error(403)
        if resource_mfid not in self.s["datasets"]:
            raise _http_error(404)
        if overwrite:
            self.s["datasets"][resource_mfid]["scientific_metadata"] = dict(metadata)
        else:
            current = self.s["datasets"][resource_mfid].get("scientific_metadata") or {}
            self.s["datasets"][resource_mfid]["scientific_metadata"] = {**current, **metadata}
        return self.get_scientific_metadata(resource_mfid)

    def add_file(self, dataset_mfid, file_path, ingestion_class=None, wait_for_ingestion_response=False,
                 multipart=None, chunk_size_mb=None, max_workers=None, skip_ingestion=False,
                 upload_protocol=None, progress=None, replace=False):
        for name, value in (("multipart", multipart), ("chunk_size_mb", chunk_size_mb),
                            ("upload_protocol", upload_protocol)):
            if value is not None:
                raise RemovedError(removed_message(
                    f"The '{name}' argument of datasets.add_file()",
                    "every upload uses signed multipart; drop it."))
        name = os.path.basename(file_path)
        files = self.s["files"].setdefault(dataset_mfid, [])
        if not replace and any(f["filename"] == name for f in files):
            raise Exception("FileExistsWithDifferentContent")
        with open(file_path, "rb") as fh:
            files.append({"mfid": _new_id("F"), "filename": name, "size": len(fh.read()),
                          "skip_ingestion": skip_ingestion})
        return {"associated_file": files[-1], "ingestion_request": None}

    def list_files(self, dataset_mfid):
        return [dict(f) for f in self.s["files"].get(dataset_mfid, [])]

    def get_download_links(self, dataset_mfid, disposition=None):
        return {f["mfid"]: f"https://storage.example/{f['filename']}" for f in self.s["files"].get(dataset_mfid, [])}

    def add_keyword(self, dataset_mfid, keyword):
        if dataset_mfid not in self.s["datasets"]:
            raise _http_error(404)
        kws = self.s["datasets"][dataset_mfid].setdefault("keywords", [])
        if keyword not in kws:
            kws.append(keyword)
        return {"dataset_mfid": dataset_mfid, "keyword": keyword}

    def postprocess(self, dataset_mfid, pipeline, parameters=None, idempotency_key=None):
        if dataset_mfid not in self.s["datasets"]:
            raise _http_error(404)
        entry = {
            "id": next(_ids),
            "dataset_mfid": dataset_mfid,
            "pipeline": pipeline,
            "parameters": parameters,
            "idempotency_key": idempotency_key,
            "status": "requested",
        }
        self.s["postprocessing"].append(entry)
        return dict(entry)


class FakeFiles(_Checked):
    _real = FileOperations

    def __init__(self, store):
        self.s = store

    def list(self, limit=100, sha256_hash=None, offset=0, cursor=None):
        out = []
        for ds_mfid, ds_files in self.s["files"].items():
            for f in ds_files:
                item = {"dataset_mfid": ds_mfid, **f}
                if sha256_hash is not None and item.get("sha256_hash") != sha256_hash:
                    continue
                out.append(item)
        if offset:
            out = out[offset:]
        return out[:limit] if isinstance(limit, int) else out


class FakeUsers(_Checked):
    _real = UserOperations

    def __init__(self, store):
        self.s = store

    def get(self, user_ref=None, email=None, username=None, *, user_unique_id=None):
        provided = [v for v in (user_ref, email, username, user_unique_id) if v is not None]
        if len(provided) != 1:
            raise ValueError("Provide exactly one user reference.")
        if user_unique_id is not None:
            kind, normalized = "unique_id", user_unique_id
        elif username is not None:
            kind, normalized = classify_user_reference(username)
            if kind != "username":
                raise ValueError("username must be a valid 3-to-24-character username.")
        elif email is not None:
            kind, normalized = classify_user_reference(email)
            if kind != "email":
                raise ValueError("email must contain '@'.")
        else:
            kind, normalized = classify_user_reference(user_ref)

        for user in self.s["users"].values():
            if kind in ("unique_id", "reference") and normalized in (user.get("unique_id"), user.get("orcid")):
                return dict(user)
            if kind == "email" and (user.get("email") or "").lower() == normalized:
                return dict(user)
            if kind == "username" and (user.get("username") or "").lower() == normalized:
                return dict(user)

        if kind in ("email", "username"):
            raise IdentifierNotFoundError(f"User not found: {normalized}")
        raise _http_error(404)

    def list_projects(self, user_ref, limit=100, offset=0, role=None, sort=None,
                      direction=None, include_metadata=False, cursor=None):
        projects = [dict(p) for p in self.s["user_projects"].get(user_ref, [])]
        return projects[:limit] if isinstance(limit, int) else projects

    list_projects._deprecated_parameters = (("user_unique_id", "user_ref"),)


class FakeProjects(_Checked):
    _real = ProjectOperations

    def __init__(self, store):
        self.s = store

    def list(self, orcid=None, include_metadata=False, limit=100, offset=0,
             accessible_to_user=None, accessible_to_project=None, sort=None,
             direction=None, member_ref=None, member_role=None, cursor=None,
             mfid=None, owner_ref=None):
        if orcid is not None:
            raise RemovedError(removed_message(
                "The 'orcid' argument of projects.list()",
                "use member_ref=... or client.users.list_projects() instead."))
        if member_ref is not None:
            out = [dict(p) for p in self.s["user_projects"].get(member_ref, [])]
        else:
            out = [dict(p) for p in self.s["projects"].values()]
        if offset:
            out = out[offset:]
        return out[:limit] if isinstance(limit, int) else out


class FakePrint(_Checked):
    _real = PrintOperations

    def __init__(self, store):
        self.s = store

    def barcode(self, printer_id, mfid, name):
        if not is_mfid(mfid):
            raise ValueError("mfid must be an exact 26-character MFID.")
        self.s["prints"].append((printer_id, mfid, name))
        return self.s["print_result"]


def install(client):
    """Swap the client's resources for fakes. Returns (store, restore)."""
    names = ("samples", "datasets", "files", "users", "projects", "print", "_request")
    saved = {name: client.__dict__.get(name) for name in names}
    store = {
        "samples": {}, "links": [], "datasets": {}, "sample_datasets": [], "files": {},
        "prints": [], "fail_link": set(), "can_edit": True, "print_result": {"status": "ok"},
        "dataset_links": [], "ingestion_requests": {}, "file_ingestions": [],
        "users": {}, "projects": {}, "user_projects": {}, "postprocessing": [],
    }
    client.samples = FakeSamples(store)
    client.datasets = FakeDatasets(store)
    client.files = FakeFiles(store)
    client.users = FakeUsers(store)
    client.projects = FakeProjects(store)
    client.print = FakePrint(store)

    def _request(method, path, *args, **kwargs):
        _REQUEST_SIG.bind(None, method, path, *args, **kwargs)
        if method == "post" and path.endswith("/metadata") and not kwargs.get("params"):
            uid = path.split("/")[2]
            records = store["datasets"] if uid in store["datasets"] else store["samples"]
            if records[uid].get("scientific_metadata"):
                raise _http_error(409)
            records[uid]["scientific_metadata"] = kwargs["json"]
            return {"unique_id": uid, "scientific_metadata": dict(kwargs["json"])}
        if method == "post" and path.startswith("/files/") and path.endswith("/ingest"):
            if kwargs.get("json") is not None or "status" not in (kwargs.get("params") or {}):
                raise AssertionError("POST /files/{file_mfid}/ingest requires query params, not json body")
            file_mfid = path.split("/")[2]
            entry = {"id": next(_ids), "file_mfid": file_mfid, **kwargs["params"]}
            store["file_ingestions"].append(entry)
            return dict(entry)
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
