"""Reproduces the panic:

    Cannot start a runtime from within a runtime. This happens because a
    function (like `block_on`) attempted to block the current thread while the
    thread is being used to drive asynchronous tasks.

Root cause
----------
`SessionContext` methods that execute a plan (`sql`, `collect`, `table`, ...)
call `wait_for_future`, which does `runtime.block_on(fut)` on the single,
process-wide tokio runtime (see `src/utils.rs::get_runtime`).

A Python `TableProvider` registered via `register_table_provider` has its
`scan` / `schema` invoked *inside* that outer `block_on` (see
`src/provider.rs::scan`, called during the parent context's planning /
execution).

If that Python `scan` reaches back into another `SessionContext` and triggers
*another* `block_on` on the same runtime, tokio panics: you cannot start a
runtime from within a runtime.

Note both contexts share ONE global runtime, so a second context is not even
required for the hazard -- it just makes the trigger obvious.
"""

import pyarrow as pa

from xorq_datafusion import SessionContext


class ReentrantTableProvider:
    """A table provider whose scan re-enters DataFusion on another context.

    `scan` runs inside the outer context's `block_on`; calling `.collect()` on
    `inner_ctx` issues a nested `block_on` on the same global tokio runtime.
    """

    def __init__(self, inner_ctx, inner_table):
        self.inner_ctx = inner_ctx
        self.inner_table = inner_table
        self._schema = pa.schema([("id", pa.int64())])

    def schema(self):
        return self._schema

    def scan(self, filters=None):
        # nested execution on the shared runtime -> block_on within block_on.
        # Before the fix this panicked with
        # "Cannot start a runtime from within a runtime".
        df = self.inner_ctx.sql(f"select * from {self.inner_table}")
        batches = df.collect()
        return pa.RecordBatchReader.from_batches(self._schema, batches)


def test_register_table_provider_nested_runtime():
    inner = SessionContext()
    inner.sql("select 1 as id").collect()  # warm-up, no nesting
    # register a table the provider will re-query
    inner_df = inner.sql("select 1 as id union all select 2 as id")
    inner.register_dataframe("inner_t", inner_df)

    outer = SessionContext()
    outer.register_table_provider("reentrant", ReentrantTableProvider(inner, "inner_t"))

    # Executing the outer query drives scan(), which re-enters the runtime.
    # With the block_in_place fix this no longer panics and returns the rows
    # produced by the inner context.
    result = outer.sql("select * from reentrant").to_pandas()

    assert sorted(result["id"].tolist()) == [1, 2]
