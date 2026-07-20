use std::future::Future;
use std::sync::{Arc, OnceLock, RwLock};

use arrow::array::ArrayRef;
use arrow::array::RecordBatch;
use arrow::datatypes::SchemaRef;
use datafusion::execution::SendableRecordBatchStream;
use datafusion::physical_expr::{EquivalenceProperties, LexOrdering, Partitioning};
use datafusion::physical_plan::execution_plan::{Boundedness, EmissionType};
use datafusion::physical_plan::stream::RecordBatchStreamAdapter;
use datafusion::physical_plan::PlanProperties;
use datafusion_common::DataFusionError as InnerDataFusionError;
use datafusion_common::{Result, ScalarValue};
use datafusion_expr::Volatility;
use datafusion_expr::{ColumnarValue, ScalarFunctionImplementation};
use futures::stream;
use pyo3::prelude::*;
use tokio::runtime::{Handle, Runtime};

use crate::errors::DataFusionError;

/// Batches buffered between the batch producer and the async stream consumer.
/// Bounds memory and lets the producer read one step ahead of the consumer.
pub const CHANNEL_CAPACITY: usize = 8;

/// One batch pulled from a Python-backed source. `None` ends the stream; the
/// closure owns all its state (reader/iterator, projection, ...) and is called
/// on the blocking pool, so it may hold the GIL and block freely.
pub type BatchPull = Box<dyn FnMut() -> Option<Result<RecordBatch>> + Send>;

/// Bridge a synchronous, blocking `pull` (a Python reader) to an async
/// `SendableRecordBatchStream` without ever pinning a blocking-pool thread while
/// idle.
///
/// A coordinator *async task* runs the pull loop: it awaits `reserve()` for a
/// channel slot (parking as a cheap async task -- no thread -- when the consumer
/// is slow or has stopped) and only then pulls exactly one batch on the blocking
/// pool via `spawn_blocking`. The blocking thread is returned as soon as that one
/// batch is produced, so a stream that is polled once and then abandoned (kept
/// alive but not drained) holds **zero** blocking threads -- it just parks the
/// coordinator in `reserve()`. This avoids the blocking-pool exhaustion hang that
/// a lifetime producer parked in `blocking_send` would cause once enough streams
/// are abandoned. When the consumer (`rx`) is dropped, `reserve()` errors and the
/// coordinator exits.
///
/// GIL discipline: the pull runs inside `spawn_blocking` (never an async worker),
/// so acquiring the GIL there is safe.
pub fn spawn_channel_stream(schema: SchemaRef, pull: BatchPull) -> SendableRecordBatchStream {
    let (tx, rx) = tokio::sync::mpsc::channel::<Result<RecordBatch>>(CHANNEL_CAPACITY);

    tokio::spawn(async move {
        let mut pull = pull;
        loop {
            // Backpressure without a pinned thread: park here until a slot frees.
            // Err => the receiver was dropped (query cancelled) => stop.
            let permit = match tx.reserve().await {
                Ok(permit) => permit,
                Err(_) => break,
            };
            // Pull one batch on the blocking pool; the pull closure is moved in and
            // handed back so its reader survives across batches.
            let joined = tokio::task::spawn_blocking(move || {
                let mut pull = pull;
                let item = pull();
                (item, pull)
            })
            .await;
            match joined {
                Ok((item, returned)) => {
                    pull = returned;
                    match item {
                        Some(batch) => permit.send(batch),
                        None => break,
                    }
                }
                Err(join_err) => {
                    permit.send(Err(InnerDataFusionError::External(Box::new(join_err))));
                    break;
                }
            }
        }
    });

    let stream = stream::unfold(rx, |mut rx| async move {
        rx.recv().await.map(|item| (item, rx))
    });
    Box::pin(RecordBatchStreamAdapter::new(schema, stream))
}

// NOTE: Other pyo3 Python libraries have had issues with using tokio
// behind a forking app-server like `gunicorn`
// If we run into that problem, in the future we can look to `delta-rs`
// which adds a check in that disallows calls from a forked process
// https://github.com/delta-io/delta-rs/blob/87010461cfe01563d91a4b9cd6fa468e2ad5f283/python/src/utils.rs#L10-L31
fn get_runtime() -> &'static RwLock<Option<Runtime>> {
    static RUNTIME: OnceLock<RwLock<Option<Runtime>>> = OnceLock::new();
    RUNTIME.get_or_init(|| RwLock::new(Some(Runtime::new().unwrap())))
}

/// Returns a Handle for spawning tasks without blocking on the runtime lock.
pub fn get_tokio_handle() -> Handle {
    get_runtime()
        .read()
        .unwrap()
        .as_ref()
        .expect("tokio runtime has been shut down")
        .handle()
        .clone()
}

/// Shuts down the process-wide tokio runtime. Safe to call from Python before
/// sys.exit() to avoid a Py_Finalize / blocking-pool drop deadlock.
pub fn shutdown_runtime(timeout_secs: Option<u64>) {
    let old = get_runtime().write().unwrap().take();
    if let Some(rt) = old {
        match timeout_secs {
            Some(s) => rt.shutdown_timeout(std::time::Duration::from_secs(s)),
            None => rt.shutdown_background(),
        }
    }
}

/// Utility to collect rust futures with GIL released
pub fn wait_for_future<F>(py: Python, f: F) -> F::Output
where
    F: Send + Future,
    F::Output: Send,
{
    let handle = get_tokio_handle();
    py.detach(|| match Handle::try_current() {
        // Already running inside the tokio runtime (e.g. a Python
        // TableProvider.scan/schema that re-enters another SessionContext
        // during an outer block_on). Calling block_on again would panic with
        // "Cannot start a runtime from within a runtime", so hand the worker
        // thread back to the scheduler via block_in_place first.
        Ok(handle) => tokio::task::block_in_place(|| handle.block_on(f)),
        Err(_) => handle.block_on(f),
    })
}
pub(crate) fn parse_volatility(value: &str) -> Result<Volatility, DataFusionError> {
    Ok(match value {
        "immutable" => Volatility::Immutable,
        "stable" => Volatility::Stable,
        "volatile" => Volatility::Volatile,
        value => {
            return Err(DataFusionError::Common(format!(
                "Unsupported volatility type: `{value}`, supported \
                 values are: immutable, stable and volatile."
            )))
        }
    })
}

pub fn compute_properties(schema: SchemaRef) -> Arc<PlanProperties> {
    let eq_properties = EquivalenceProperties::new(schema);

    Arc::new(PlanProperties::new(
        eq_properties,
        Partitioning::UnknownPartitioning(1),
        EmissionType::Incremental,
        Boundedness::Bounded,
    ))
}

pub fn compute_properties_with_orderings(
    schema: SchemaRef,
    orderings: &[LexOrdering],
) -> Arc<PlanProperties> {
    let eq_properties = if orderings.is_empty() {
        EquivalenceProperties::new(Arc::clone(&schema))
    } else {
        EquivalenceProperties::new_with_orderings(Arc::clone(&schema), orderings.to_vec())
    };

    Arc::new(PlanProperties::new(
        eq_properties,
        Partitioning::UnknownPartitioning(1),
        EmissionType::Incremental,
        Boundedness::Bounded,
    ))
}

pub fn make_scalar_function<F>(inner: F) -> ScalarFunctionImplementation
where
    F: Fn(&[ArrayRef]) -> Result<ArrayRef> + Sync + Send + 'static,
{
    Arc::new(move |args: &[ColumnarValue]| {
        // first, identify if any of the arguments is an Array. If yes, store its `len`,
        // as any scalar will need to be converted to an array of len `len`.
        let len = args
            .iter()
            .fold(Option::<usize>::None, |acc, arg| match arg {
                ColumnarValue::Scalar(_) => acc,
                ColumnarValue::Array(a) => Some(a.len()),
            });

        let is_scalar = len.is_none();

        let inferred_length = len.unwrap_or(1);
        let args = args
            .iter()
            .map(|arg| arg.clone().into_array(inferred_length))
            .collect::<Result<Vec<_>>>()?;

        let result = (inner)(&args);
        if is_scalar {
            // If all inputs are scalar, keeps output as scalar
            let result = result.and_then(|arr| ScalarValue::try_from_array(&arr, 0));
            result.map(ColumnarValue::Scalar)
        } else {
            result.map(ColumnarValue::Array)
        }
    })
}
