"""
Experimental: fit and predict scikit-learn pipelines inside DataFusion.

The base ``xorq_datafusion`` package never imports this module, so installing
or importing it does not load scikit-learn. Install with the ``ml`` extra::

    pip install "xorq-datafusion[ml]"

Status: experimental. The public names below have their final
signatures. ``fit`` fits the whole pipeline natively; ``compile`` turns a
fitted pipeline (from ``fit`` or from scikit-learn) into a ``Model`` whose
``predict`` adds a ``label`` column to any DataFrame, computed natively.

Limitation: a KMeans cluster that receives no rows keeps its previous
center, where scikit-learn relocates it; inputs must not produce empty
clusters.

Supported: ``make_pipeline(StandardScaler(), KMeans(init=C0, n_init=1))``;
every computation on row data runs natively in DataFusion.
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
