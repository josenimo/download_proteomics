"""Download and load proteomics datasets declared in ``datasets.yaml``.

Thin wrapper over :mod:`scverse_misc.datasets`, which does the actual work in three steps:

1. **Describe** -- ``datasets.yaml`` is parsed by :func:`scverse_misc.datasets.parse_registry`
   into typed ``DatasetEntry``/``FileEntry`` objects.
2. **Fetch** -- :func:`scverse_misc.datasets.fetch` downloads via pooch (hash verification,
   caching, retries) trying ``base_url + s3_key`` first and each of the file's
   ``fallback_urls`` (i.e. Zenodo) afterwards.
3. **Load** -- ``fetch`` dispatches on the entry's ``type``; the built-in ``anndata`` loader
   reads the single ``.h5ad`` with :func:`anndata.read_h5ad`.

Adding a dataset is therefore a ``datasets.yaml``-only change; nothing here needs editing.
"""

from __future__ import annotations

import os
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from anndata import AnnData
    from scverse_misc.datasets import DatasetEntry

__all__ = ["load", "available_datasets", "describe", "cache_dir"]

#: Override the download cache directory (see :func:`cache_dir`).
DATA_DIR_ENV_VAR = "DOWNLOAD_PROTEOMICS_DATA_DIR"

#: Override the registry's ``base_url``, e.g. to repoint the bucket without a release.
BASE_URL_ENV_VAR = "DOWNLOAD_PROTEOMICS_BASE_URL"


@cache
def _shipped_registry() -> tuple[str | None, dict[str, DatasetEntry]]:
    """Parse the ``datasets.yaml`` registry shipped inside the ``download_proteomics`` package."""
    import importlib.resources

    from scverse_misc.datasets import parse_registry

    registry = importlib.resources.files("download_proteomics").joinpath("datasets.yaml")
    with importlib.resources.as_file(registry) as registry_path:
        base_url, datasets = parse_registry(registry_path)
    return base_url, datasets


def _base_url() -> str | None:
    """Resolve the download base URL, letting ``$DOWNLOAD_PROTEOMICS_BASE_URL`` win."""
    base_url, _ = _shipped_registry()
    return os.environ.get(BASE_URL_ENV_VAR) or base_url


def cache_dir(path: str | os.PathLike[str] | None = None) -> Path:
    """Resolve the directory downloads are cached in.

    Precedence: the explicit ``path`` argument, then ``$DOWNLOAD_PROTEOMICS_DATA_DIR``, then the
    OS cache location (:func:`pooch.os_cache` for ``"download_proteomics"``).

    Note that :func:`load` caches each file one level deeper, under ``<cache_dir>/anndata/``,
    because ``fetch`` namespaces the cache by dataset type.
    """
    import pooch

    if path is not None:
        return Path(path)
    if env := os.environ.get(DATA_DIR_ENV_VAR):
        return Path(env)
    return Path(pooch.os_cache("download_proteomics"))


def available_datasets() -> list[str]:
    """Return the names of all datasets in the registry, sorted.

    Every name is valid input to :func:`load` and :func:`describe`.
    """
    _, datasets = _shipped_registry()
    return sorted(datasets)


def _entry(name: str) -> DatasetEntry:
    """Look up ``name`` in the registry, raising a ``KeyError`` that lists the valid names."""
    _, datasets = _shipped_registry()
    try:
        return datasets[name]
    except KeyError:
        raise KeyError(f"Unknown dataset {name!r}. Available: {available_datasets()}") from None


def _describe_one(entry: DatasetEntry) -> dict[str, Any]:
    base_url = _base_url()
    return {
        "name": entry.name,
        "type": entry.type,
        "files": [
            {
                "name": f.name,
                "url": f.resolve_url(base_url),
                "sha256": f.sha256,
                "fallback_urls": list(f.fallback_urls or []),
            }
            for f in entry.files
        ],
        # everything in the YAML other than `type` and `files`
        **dict(entry.metadata),
    }


def describe(name: str | None = None) -> dict[str, Any] | list[dict[str, Any]]:
    """Describe one dataset, or every dataset when ``name`` is ``None``.

    Returns the dataset's name and type, its resolved download URLs and hashes, and all the
    free-form metadata from the registry (description, license, reference, ...).

    Args:
        name: Dataset to describe. If ``None``, describe all of them.

    Returns:
        A dict for a single dataset, or a list of dicts ordered like :func:`available_datasets`.

    Raises:
        KeyError: If ``name`` is not in the registry. The message lists the valid names.
    """
    if name is not None:
        return _describe_one(_entry(name))
    _, datasets = _shipped_registry()
    return [_describe_one(datasets[n]) for n in sorted(datasets)]


def load(name: str, path: str | os.PathLike[str] | None = None, **kwargs: Any) -> AnnData:
    """Download (if needed) and load a dataset as an :class:`~anndata.AnnData` object.

    The download is hash-verified and cached, so repeated calls reuse the local copy instead of
    downloading again. The S3 bucket is tried first; if it is unreachable, the file's Zenodo
    mirror is used (a ``UserWarning`` is emitted when that happens).

    Args:
        name: Dataset name, one of :func:`available_datasets`.
        path: Directory to cache the download in. Defaults to :func:`cache_dir`.
        **kwargs: Passed through to :func:`anndata.read_h5ad`, e.g. ``backed="r"``.

    Returns:
        The loaded dataset.

    Raises:
        KeyError: If ``name`` is not in the registry. The message lists the valid names.
        ExceptionGroup: If the S3 URL *and* every fallback URL failed to download.

    Examples:
        >>> import download_proteomics as dp
        >>> adata = dp.load("example_dataset")  # doctest: +SKIP
    """
    from scverse_misc.datasets import fetch

    adata: AnnData = fetch(_entry(name), cache_dir(path), base_url=_base_url(), **kwargs)
    return adata
