use std::future::Future;
use std::sync::{Arc, OnceLock, RwLock};

use arrow::array::ArrayRef;
use arrow::array::RecordBatch;
use arrow::datatypes::SchemaRef;
use datafusion::execution::SendableRecordBatchStream;
use datafusion::physical_expr::{EquivalenceProperties, LexOrdering, Partitioning};
use datafusion::physical_plan::execution_plan::{Boundedness, EmissionType};
use datafusion::physical_plan::stream::RecordBatchReceiverStream;
use datafusion::physical_plan::PlanProperties;
use datafusion_common::{Result, ScalarValue};
use datafusion_expr::Volatility;
use datafusion_expr::{ColumnarValue, ScalarFunctionImplementation};
use pyo3::prelude::*;
use tokio::runtime::{Handle, Runtime};
use tokio::sync::mpsc::OwnedPermit;

use crate::errors::DataFusionError;

/// Batches buffered between the batch producer and the async stream consumer.
/// Bounds memory and the read-ahead a pull may run in front of the consumer.
const CHANNEL_CAPACITY: usize = 8;

/// One batch pulled from a Python-backed source. `None` ends the stream; the
/// closure owns all its state (reader/iterator, projection, ...) and is called
/// on the blocking pool, so it may hold the GIL and block freely.
///
/// Contract for implementers:
/// * The closure is called from `spawn_blocking`, and **not necessarily from the
///   same thread each time** -- consecutive batches of one stream may run on
///   different blocking-pool threads (the GIL still serialises them). A reader
///   backed by thread-affine state (e.g. a `sqlite3` connection created with
///   `check_same_thread=True`) must therefore not be used directly as a pull.
/// * It is only called again after returning `Some(Ok(_))`: `None` and
///   `Some(Err(_))` are both terminal.
/// * It is dropped on the blocking pool too (see [`PullGuard`]), so destroying
///   the Python objects it owns may take the GIL.
pub type BatchPull = Box<dyn FnMut() -> Option<Result<RecordBatch>> + Send>;

/// Owns a [`BatchPull`] between rounds and guarantees the closure is destroyed on
/// the blocking pool.
///
/// Dropping a pull destroys the Python objects it captured (an
/// `ArrowArrayStreamReader`'s FFI release callback, a `Py<PyIterator>`, ...),
/// which acquires the GIL. That must never happen on an async worker: a worker
/// blocked on the GIL cannot be handed back to the scheduler, and with a Python
/// thread holding the GIL while waiting on a Rust lock (the GIL/mutex inversion)
/// it can park every worker and hang the runtime. The coordinator holds the pull
/// across `await` points, so this also covers the task being *aborted* there
/// (which drops its locals on the worker).
struct PullGuard(Option<BatchPull>);

impl PullGuard {
    fn new(pull: BatchPull) -> Self {
        Self(Some(pull))
    }

    /// Hand the pull to a blocking task. The guard is empty until [`Self::put`],
    /// so an abort while the blocking task runs leaves disposal to that task.
    fn take(&mut self) -> BatchPull {
        self.0.take().expect("pull is in flight")
    }

    fn put(&mut self, pull: BatchPull) {
        self.0 = Some(pull);
    }
}

impl Drop for PullGuard {
    fn drop(&mut self) {
        let Some(pull) = self.0.take() else { return };
        match Handle::try_current() {
            // Detached on purpose: disposal must not depend on this task being
            // polled again -- it usually runs from a drop/abort.
            Ok(handle) => {
                handle.spawn_blocking(move || drop(pull));
            }
            // No runtime context (e.g. after shutdown_runtime): there is nowhere
            // to hand it to, so drop it here.
            Err(_) => drop(pull),
        }
    }
}

/// Bridge a synchronous, blocking `pull` (a Python reader) to an async
/// `SendableRecordBatchStream` without ever pinning a blocking-pool thread while
/// idle.
///
/// A coordinator *async task* runs the pull loop: it awaits `reserve_owned()` for
/// a channel slot (parking as a cheap async task -- no thread -- when the
/// consumer is slow or has stopped) and only then pulls on the blocking pool via
/// `spawn_blocking`. That blocking task drains batches only while the channel has
/// free slots and returns its thread as soon as the channel is full, so a stream
/// that is polled once and then abandoned (kept alive but not drained) holds
/// **zero** blocking threads -- it just parks the coordinator in
/// `reserve_owned()`. This avoids the blocking-pool exhaustion hang a lifetime
/// producer parked in `blocking_send` causes once enough streams are abandoned.
/// Draining several batches per dispatch (rather than one) keeps the per-batch
/// cost of a many-small-batches scan at roughly one channel send.
///
/// Cancellation: dropping the returned stream closes the channel *and* aborts the
/// coordinator (the builder's `JoinSet`), so no further pull is dispatched. A
/// pull already in flight still runs to completion -- Rust cannot interrupt a
/// blocking call -- so a pull that blocks forever holds its thread until it
/// returns.
///
/// Read-ahead: up to `CHANNEL_CAPACITY` batches may be produced before the
/// consumer polls, so a pull must tolerate being called for batches the query
/// never consumes (e.g. under a `LIMIT`).
///
/// GIL discipline: the pull runs inside `spawn_blocking` (never an async worker)
/// and is dropped there as well, so taking the GIL in either is safe.
pub fn spawn_channel_stream(schema: SchemaRef, pull: BatchPull) -> SendableRecordBatchStream {
    // The builder owns the channel, propagates panics to the consumer, and aborts
    // the coordinator when the stream is dropped.
    let mut builder = RecordBatchReceiverStream::builder(schema, CHANNEL_CAPACITY);
    let tx = builder.tx();

    builder.spawn(async move {
        let mut guard = PullGuard::new(pull);
        loop {
            // Backpressure without a pinned thread: park here until a slot frees.
            // Err => the receiver was dropped (query cancelled) => stop.
            let Ok(permit) = tx.clone().reserve_owned().await else {
                break;
            };
            // Pull on the blocking pool; the closure is moved in and handed back
            // so its reader survives across rounds.
            let pull = guard.take();
            let joined = tokio::task::spawn_blocking(move || {
                let mut pull = pull;
                let ended = drain_batches(&mut pull, permit);
                (ended, pull)
            })
            .await;
            match joined {
                Ok((ended, returned)) => {
                    guard.put(returned);
                    if ended {
                        break;
                    }
                }
                // The pull panicked (the closure died with its task, so the guard
                // is already empty). Re-raise here so the builder can resume the
                // original payload on the consumer instead of an opaque JoinError.
                Err(join_err) if join_err.is_panic() => {
                    std::panic::resume_unwind(join_err.into_panic())
                }
                Err(join_err) => {
                    return Err(datafusion_common::DataFusionError::External(Box::new(
                        join_err,
                    )))
                }
            }
        }
        Ok(())
    });

    builder.build()
}

/// Pull batches into `permit`'s channel while it has free slots. Returns `true`
/// when the stream is finished (input exhausted or terminal error).
///
/// Runs on the blocking pool, so it may hold the GIL and block. It never waits on
/// a full channel: it returns instead, handing the thread back while the
/// coordinator parks.
fn drain_batches(pull: &mut BatchPull, permit: OwnedPermit<Result<RecordBatch>>) -> bool {
    let mut permit = permit;
    loop {
        match pull() {
            Some(Ok(batch)) => {
                let tx = permit.send(Ok(batch));
                match tx.try_reserve_owned() {
                    Ok(next) => permit = next,
                    // Channel full (consumer behind) or closed (cancelled): stop
                    // holding this thread and let the coordinator decide.
                    Err(_) => return false,
                }
            }
            // An errored stream is terminal: surface the error once and stop,
            // rather than re-running the pull (which would retry a failed lazy
            // init or read past a fatal error).
            Some(Err(e)) => {
                permit.send(Err(e));
                return true;
            }
            // End of stream; the unused permit is released on drop.
            None => return true,
        }
    }
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
