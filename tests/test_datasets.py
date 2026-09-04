"""Tests for the registry + fetch wiring. No network: pooch is monkeypatched throughout.

Technique borrowed from scverse-misc's own ``tests/test_datasets.py``.
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any

import anndata
import pooch
import pytest

import download_proteomics as dp
from download_proteomics import _datasets


@pytest.fixture(autouse=True)
def _clear_registry_cache() -> None:
    """`_shipped_registry` is `@cache`d; drop it so env-var overrides are seen per test."""
    _datasets._shipped_registry.cache_clear()


@pytest.fixture(autouse=True)
def _no_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep a developer's own env vars from leaking into the tests."""
    monkeypatch.delenv(_datasets.DATA_DIR_ENV_VAR, raising=False)
    monkeypatch.delenv(_datasets.BASE_URL_ENV_VAR, raising=False)


# --- step 1: the shipped registry ------------------------------------------------------


def test_shipped_registry_parses_without_warnings() -> None:
    """The YAML ships inside the package and parses cleanly.

    `parse_registry` warns on (and silently drops) file keys it doesn't recognise, so turning
    warnings into errors here is what catches a typo'd or misplaced key in `datasets.yaml`.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        base_url, datasets = _datasets._shipped_registry()
    assert base_url  # a base_url is required, since entries use s3_key
    assert datasets, "registry is empty"


def test_every_entry_is_loadable() -> None:
    """Each entry declares a type we have a loader for, and exactly one .h5ad."""
    from scverse_misc.datasets import available_loaders

    _, datasets = _datasets._shipped_registry()
    for name, entry in datasets.items():
        assert entry.type in available_loaders(), f"{name}: no loader for type {entry.type!r}"
        # `_load_anndata` calls `entry.file(suffix=".h5ad")`, which needs exactly one match
        assert entry.file(suffix=".h5ad"), name


def test_available_datasets_matches_registry() -> None:
    _, datasets = _datasets._shipped_registry()
    assert dp.available_datasets() == sorted(datasets)


def test_urls_resolve_against_base_url() -> None:
    """Every file resolves to a URL, and s3_key-based ones hang off base_url."""
    base_url, datasets = _datasets._shipped_registry()
    for entry in datasets.values():
        for f in entry.files:
            url = f.resolve_url(base_url)
            assert url.startswith("https://")
            if f.s3_key and not f.url:
                assert url == f"{base_url.rstrip('/')}/{f.s3_key}"


def test_base_url_env_var_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_datasets.BASE_URL_ENV_VAR, "https://mirror.invalid/data")
    assert _datasets._base_url() == "https://mirror.invalid/data"


# --- describe / error paths ------------------------------------------------------------


def test_describe_all_and_one() -> None:
    everything = dp.describe()
    assert isinstance(everything, list)
    assert [d["name"] for d in everything] == dp.available_datasets()

    name = dp.available_datasets()[0]
    one = dp.describe(name)
    assert isinstance(one, dict)
    assert one["name"] == name
    assert one["type"] == "anndata"
    assert one["files"][0]["url"].startswith("https://")
    # dataset-level YAML keys land in metadata and get surfaced
    assert "description" in one


@pytest.mark.parametrize("fn", [dp.load, dp.describe])
def test_unknown_dataset_lists_valid_names(fn: Any) -> None:
    with pytest.raises(KeyError, match="Unknown dataset 'nope'.*Available"):
        fn("nope")


# --- cache directory -------------------------------------------------------------------


def test_cache_dir_precedence(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # 3. OS cache by default
    assert _datasets.cache_dir() == Path(pooch.os_cache("download_proteomics"))
    # 2. env var beats the default
    monkeypatch.setenv(_datasets.DATA_DIR_ENV_VAR, str(tmp_path / "from_env"))
    assert _datasets.cache_dir() == tmp_path / "from_env"
    # 1. explicit argument beats the env var
    assert _datasets.cache_dir(tmp_path / "explicit") == tmp_path / "explicit"


# --- step 2 + 3: fetch and load --------------------------------------------------------


@pytest.fixture
def fake_pooch(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace ``pooch.create`` so nothing is downloaded, and record how it was called."""
    calls: dict[str, Any] = {}

    class FakePup:
        def fetch(self, name: str, **kwargs: object) -> str:
            calls["fetched"] = name
            return f"/cache/{name}"

    def fake_create(**kwargs: object) -> FakePup:
        calls.update(kwargs)
        return FakePup()

    monkeypatch.setattr(pooch, "create", fake_create)
    return calls


def test_load_wires_registry_to_pooch_and_anndata(
    monkeypatch: pytest.MonkeyPatch, fake_pooch: dict[str, Any], tmp_path: Path
) -> None:
    """load() -> fetch() -> pooch download -> anndata.read_h5ad, with kwargs passed through."""
    seen: dict[str, Any] = {}

    def fake_read_h5ad(path: str, **kwargs: object) -> str:
        seen["path"] = path
        seen["kwargs"] = kwargs
        return "adata"

    monkeypatch.setattr(anndata, "read_h5ad", fake_read_h5ad)

    base_url, datasets = _datasets._shipped_registry()
    name = dp.available_datasets()[0]
    entry = datasets[name]
    file = entry.file(suffix=".h5ad")

    assert dp.load(name, path=tmp_path, backed="r") == "adata"

    # the URL came from the registry ...
    assert fake_pooch["urls"] == {file.name: file.resolve_url(base_url)}
    assert fake_pooch["fetched"] == file.name
    # ... the cache is namespaced by dataset type ...
    assert fake_pooch["path"] == str(tmp_path / "anndata")
    assert (tmp_path / "anndata").is_dir()
    # ... and **kwargs reached read_h5ad
    assert seen["path"] == f"/cache/{file.name}"
    assert seen["kwargs"] == {"backed": "r"}


def test_load_uses_zenodo_fallback_when_s3_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """When the primary URL fails, fetch() warns and retries against fallback_urls."""
    _, datasets = _datasets._shipped_registry()
    name = dp.available_datasets()[0]
    file = datasets[name].file(suffix=".h5ad")
    if not file.fallback_urls:
        pytest.skip(f"{name} declares no fallback_urls")

    attempted: list[str] = []

    def fake_create(**kwargs: object) -> Any:
        url = next(iter(kwargs["urls"].values()))  # type: ignore[union-attr]
        attempted.append(url)

        class Pup:
            def fetch(self, fname: str, **kw: object) -> str:
                if len(attempted) == 1:  # the S3 attempt
                    raise OSError("bucket unreachable")
                return f"/cache/{fname}"

        return Pup()

    monkeypatch.setattr(pooch, "create", fake_create)
    monkeypatch.setattr(anndata, "read_h5ad", lambda path, **kw: path)

    with pytest.warns(UserWarning, match="retrying with fallback URLs"):
        assert dp.load(name, path=tmp_path) == f"/cache/{file.name}"

    assert len(attempted) == 2
    assert attempted[1] == file.fallback_urls[0]
