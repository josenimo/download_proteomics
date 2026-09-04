"""Download proteomics AnnData datasets from S3, with Zenodo as a backup mirror.

Datasets are declared in ``datasets.yaml`` and fetched/cached/loaded through
:mod:`scverse_misc.datasets`.

Examples:
    >>> import download_proteomics as dp
    >>> dp.available_datasets()
    ['example_dataset']
    >>> adata = dp.load("example_dataset")  # doctest: +SKIP
"""

from importlib.metadata import PackageNotFoundError, version

from ._datasets import available_datasets, cache_dir, describe, load

try:
    __version__ = version("download-proteomics")
except PackageNotFoundError:  # not installed, e.g. running from a source checkout
    __version__ = "0.0.0.dev0"

__all__ = ["load", "available_datasets", "describe", "cache_dir", "__version__"]
