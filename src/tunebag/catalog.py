"""Shim: Catalog store lives in ``tunebag.projection`` as ``CatalogState``."""

from __future__ import annotations

from tunebag.projection import CatalogState as Catalog

__all__ = ["Catalog"]
