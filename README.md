# xorq DataFusion Python Bindings

> [!CAUTION]
> This repo is for the internal xorq DataFusion engine and is not meant for public use

## ML (experimental)

`xorq_datafusion.ml` fits and predicts a scikit-learn pipeline,
`make_pipeline(StandardScaler(), KMeans(init=C0, n_init=1))`, inside
DataFusion. Python only inspects the scikit-learn objects and exchanges JSON
specs; every computation on row data is a native DataFusion plan.

```python
import xorq_datafusion.ml as ml

fitted = ml.fit(make_pipeline(StandardScaler(), KMeans(4, init=C0, n_init=1)), df)
model = ml.compile(fitted)
labelled = model.predict(df)  # an ordinary DataFrame with an Int64 "label"
```

Install with the extra, `pip install "xorq-datafusion[ml]"`; the development
setup in [CONTRIBUTING.md](CONTRIBUTING.md) already includes it. Run the
end-to-end demo (blobs -> Parquet -> fit -> predict -> SQL on the labels ->
comparison with scikit-learn):

```bash
uv run python examples/ml_demo.py
```

Limitations: a KMeans cluster that receives no rows keeps its previous center
(scikit-learn relocates it); missing and non-finite values are refused; data
is Float64; only `fit` is interruptible with Ctrl-C. Predict folds the scaler
into the centroids only for shifts, scales and centers of magnitude
2^-500..2^500 (else it keeps the steps apart); folded or not, a row within
floating-point rounding of a decision boundary may get a different label than
scikit-learn gives it, as scikit-learn's own `predict` may differ from the
direct distance formula there.

Walk the layers (each entry is `file` — `symbol`):

1. `python/xorq_datafusion/ml/api.py` — `fit`, `compile`, `Model`: the public API.
2. `python/xorq_datafusion/ml/frontend.py` — `to_fit_spec`, `to_compile_spec`, `apply_fit_result`: scikit-learn objects to specs and back.
3. `src/ml/bindings.rs` — `fit`, `predict`, `explain_fit`, `explain_predict`: the `_internal.ml` functions.
4. `src/ml/spec.rs` — `FitRequest`, `FitResult`, `CompileRequest`: the spec v0 serde types and their validation.
5. `src/ml/fit.rs` — `fit`, `scaler_fit_plan`, `transform_plan`: the fit driver, chaining steps on the DataFrame's own plan.
6. `src/ml/exec/welford.rs` — `welford_udaf`: the single-pass mean/variance UDAF behind StandardScaler.
7. `src/ml/kmeans.rs` — `kmeans_fit_plan`, `body_plan`: one Lloyd iteration as a relational plan.
8. `src/ml/nodes/iterate.rs` — `Iterate`, `LoopState`: the loop as logical nodes.
9. `src/ml/exec/iterate.rs` — `IterateExec`, `LoopStateExec`: the loop executed, re-planning the body each iteration.
10. `src/ml/properties.rs` — `StepProperties`, `PredictStep`: what rewrite rules match on.
11. `src/ml/nodes/predict.rs` — `Predict`: label rows with fitted steps.
12. `src/ml/rules/mod.rs` — `AffineFusion`, `LowerPredict`: fold the scaler into the centroids, then lower to expressions.
13. `src/ml/exec/nearest_centroid.rs` — `nearest_centroid_udf`: the native labelling UDF.
14. `src/ml/planner.rs` — `MlQueryPlanner`, `MlExtensionPlanner`: physical planning for the ML nodes.
15. `src/ml/session.rs` — `with_ml`: installs the planner, rules and functions on every session.
16. `src/utils.rs` — `wait_for_future_interruptible`: Ctrl-C for ML entry points.
