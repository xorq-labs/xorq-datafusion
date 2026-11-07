"""
Experimental: fit and predict scikit-learn pipelines inside DataFusion.

The base ``xorq_datafusion`` package never imports this module, so installing
or importing it does not load scikit-learn. Install with the ``ml`` extra::

    pip install "xorq-datafusion[ml]"

Status: in progress. The public names below exist with their final
signatures. ``supports`` and ``fit`` work (the whole pipeline is fitted
natively); ``compile`` and ``Model`` methods raise ``NotImplementedError``.

Limitation: a KMeans cluster that receives no rows keeps its previous
center, where scikit-learn relocates it; inputs must not produce empty
clusters. Planned first target:
``make_pipeline(StandardScaler(), KMeans(init=C0, n_init=1))``, fit and
predict, with every computation on row data running natively in DataFusion.
"""

from xorq_datafusion.ml.api import (
    Model,
    Reason,
    Supported,
    Unsupported,
    compile,
    fit,
    supports,
)

__all__ = [
    "Model",
    "Reason",
    "Supported",
    "Unsupported",
    "compile",
    "fit",
    "supports",
]
