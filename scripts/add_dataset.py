#!/usr/bin/env python
"""Emit a paste-ready ``datasets.yaml`` entry for a local ``.h5ad``.

Computes the SHA-256 (which is what makes a cached download trustworthy) and reads the
dataset shape out of the file, so the registry entry does not have to be written by hand.

Usage:
    uv run python scripts/add_dataset.py path/to/file.h5ad [--name NAME] [--zenodo-record ID]
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

CHUNK = 1 << 20  # 1 MiB


def sha256(path: Path) -> str:
    """Hash ``path`` in chunks, so datasets larger than memory work."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


def shape(path: Path) -> tuple[int, int] | None:
    """Read ``(n_obs, n_vars)`` without loading the matrix, or ``None`` if anndata can't."""
    try:
        import anndata

        adata = anndata.read_h5ad(path, backed="r")
        return adata.n_obs, adata.n_vars
    except Exception as e:  # noqa: BLE001 - purely informational, never fatal
        print(f"# note: could not read shape from {path.name}: {e!r}")
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("file", type=Path, help="local .h5ad file, already uploaded (or about to be)")
    parser.add_argument("--name", help="registry key; defaults to the file stem")
    parser.add_argument("--s3-key", help="key relative to the registry base_url; defaults to the file name")
    parser.add_argument("--zenodo-record", help="Zenodo record id, to build the fallback URL")
    args = parser.parse_args()

    path: Path = args.file
    if not path.is_file():
        parser.error(f"{path} is not a file")
    if path.suffix != ".h5ad":
        parser.error(f"expected a .h5ad file, got {path.suffix or 'no suffix'!r}")

    name = args.name or path.stem
    s3_key = args.s3_key or path.name
    dims = shape(path)
    zenodo = args.zenodo_record or "REPLACE"

    size_mb = path.stat().st_size / 1e6
    print(f"\n# --- paste into src/download_proteomics/datasets.yaml under `datasets:` ({size_mb:.1f} MB) ---")
    print(f"    {name}:")
    print("        type: anndata")
    print(f"        doc_header: {name.replace('_', ' ').capitalize()} dataset.")
    print("        description: >-")
    print("            TODO: one-paragraph description of the experiment.")
    if dims is not None:
        print(f"        n_obs: {dims[0]}")
        print(f"        n_vars: {dims[1]}")
    print("        license: TODO")
    print("        files:")
    print(f"            - name: {path.name}")
    print(f"              s3_key: {s3_key}")
    print(f"              sha256: {sha256(path)}")
    print("              fallback_urls:")
    print(f"                  - https://zenodo.org/records/{zenodo}/files/{path.name}")


if __name__ == "__main__":
    main()
