# download-proteomics

Download proteomics [AnnData][] datasets from an S3 bucket — with Zenodo as an automatic
backup mirror — and load them straight into memory.

Downloads are hash-verified and cached, so repeated calls reuse the local copy.

## Install

```bash
uv add download-proteomics
```

For a source checkout:

```bash
uv sync
```

Requires Python ≥ 3.12.

## Usage

```python
import download_proteomics as dp

dp.available_datasets()          # ['example_dataset']
dp.describe("example_dataset")   # urls, hashes, license, description

adata = dp.load("example_dataset")            # downloads on first call, cached after
adata = dp.load("example_dataset", backed="r")  # kwargs go to anndata.read_h5ad
```

### Cache location

By default files land in the OS cache directory (`pooch.os_cache("download_proteomics")`),
namespaced by dataset type — so `~/Library/Caches/download_proteomics/anndata/` on macOS.
Override it per call with `dp.load(name, path=...)`, or globally:

| Environment variable | Effect |
| --- | --- |
| `DOWNLOAD_PROTEOMICS_DATA_DIR` | Cache downloads here instead of the OS cache dir |
| `DOWNLOAD_PROTEOMICS_BASE_URL` | Repoint the S3 base URL without a new release |

`dp.cache_dir()` reports the directory that will be used.

## How it works

This package is a thin wrapper over [`scverse-misc[datasets]`][scverse-misc], the shared
scverse implementation of the three-step dataset pattern. The heavy lifting is not ours:

1. **Describe** — [`src/download_proteomics/datasets.yaml`](src/download_proteomics/datasets.yaml)
   is the single source of truth, parsed by `scverse_misc.datasets.parse_registry`.
2. **Fetch** — `scverse_misc.datasets.fetch` downloads through [pooch][]: SHA-256
   verification, caching, retries. It tries `base_url + s3_key` first, then each of the file's
   `fallback_urls` in turn — which is how Zenodo acts as the backup. A `UserWarning` is emitted
   when a fallback is used; if every mirror fails you get an `ExceptionGroup`.
3. **Load** — `fetch` dispatches on the entry's `type`. `anndata` is a built-in loader that
   reads the single `.h5ad` with `anndata.read_h5ad`.

Because the registry drives everything, **adding a dataset is a YAML-only change** — no Python
edits, and it shows up in `available_datasets()` automatically.

## Adding a dataset

1. Upload the `.h5ad` to the S3 bucket (must be readable over anonymous HTTPS — pooch does a
   plain `GET`, it does not use AWS credentials).
2. Mirror the same file to Zenodo and note the record id.
3. Generate the registry entry:

   ```bash
   uv run python scripts/add_dataset.py path/to/file.h5ad --zenodo-record 1234567
   ```

4. Paste the emitted block into `datasets.yaml` under `datasets:` and fill in the `description`
   and `license` fields.
5. `uv run pytest` — the suite re-parses the shipped registry and will fail on a malformed entry
   (including a file key in the wrong place).

Only `name`, `url`, `s3_key`, `sha256` and `fallback_urls` are valid *file* keys; anything else
is dropped with a warning. Put prose at the *dataset* level, where it lands in the entry's
metadata and is surfaced by `describe()`.

## Development

```bash
uv sync
uv run pytest        # no network access needed; pooch is monkeypatched
```

[AnnData]: https://anndata.readthedocs.io/
[scverse-misc]: https://scverse-misc.readthedocs.io/page/api.html
[pooch]: https://www.fatiando.org/pooch/
