"""Narrow read-only compatibility for H5AD null scalar encoding.

The frozen MERFISH inputs were written with AnnData's standard
``IOSpec('null', '0.1.0')`` for ``uns/log1p/base = None``.  AnnData 0.10.9 can
write this spec but lacks the matching HDF5 Dataset reader.  Registering that
single reader restores the serialized value as Python ``None``.  It does not
alter the input file, expression matrix, annotations, or scientific settings.
"""

from __future__ import annotations


def register_h5ad_null_reader() -> None:
    import h5py
    from anndata._io.specs import IOSpec, _REGISTRY

    key = (h5py.Dataset, IOSpec("null", "0.1.0"), frozenset())
    existing = _REGISTRY.read.get(key)
    if existing is not None:
        return

    def read_null_scalar(_elem, *, _reader):
        return None

    _REGISTRY.register_read(
        h5py.Dataset, IOSpec("null", "0.1.0")
    )(read_null_scalar)

