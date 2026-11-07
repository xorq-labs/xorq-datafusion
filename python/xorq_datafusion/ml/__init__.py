"""
Experimental: fit and predict scikit-learn pipelines inside DataFusion.

The base ``xorq_datafusion`` package never imports this module, so installing
or importing it does not load scikit-learn. Install with the ``ml`` extra::

    pip install "xorq-datafusion[ml]"

Supported today: ``make_pipeline(StandardScaler(), KMeans(init=C0, n_init=1))``,
fit and predict, with every computation on row data running natively in
DataFusion.
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
