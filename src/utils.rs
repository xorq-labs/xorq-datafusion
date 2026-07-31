use std::future::Future;
use std::pin::Pin;
use std::sync::{Arc, OnceLock, RwLock};
use std::task::{Context, Poll};

use arrow::array::ArrayRef;
use arrow::array::RecordBatch;
use arrow::datatypes::SchemaRef;
use datafusion::execution::SendableRecordBatchStream;
use datafusion::physical_expr::{EquivalenceProperties, LexOrdering, Partitioning};
use datafusion::physical_plan::execution_plan::{Boundedness, EmissionType};
use datafusion::physical_plan::stream::RecordBatchReceiverStream;
use datafusion::physical_plan::{PlanProperties, RecordBatchStream};
use datafusion_common::{Result, ScalarValue};
use datafusion_expr::Volatility;
use datafusion_expr::{ColumnarValue, ScalarFunctionImplementation};
use futures::Stream;
use pyo3::prelude::*;
use tokio::runtime::{Handle, Runtime};
use tokio::sync::mpsc::OwnedPermit;
use tokio::sync::Semaphore;

use crate::errors::DataFusionError;

/// Batches buffered between the batch producer and the async stream consumer.
/// Bounds memory and the read-ahead a pull may run in front of the consumer.
const CHANNEL_CAPACITY: usize = 8;

/// Blocking-pool threads that may sit stranded in *speculative* pulls at once,
/// process-wide.
///
/// A pull that blocks forever cannot be interrupted, so its thread is lost. When
/// the query asked for that batch, that is the caller's own doing; when the
/// producer pulled it speculatively, it is ours -- and one leak per query
/// exhausts tokio's 512-thread pool and wedges the runtime. Speculation therefore
/// draws on this budget for the duration of the pull: a stranded speculative pull
/// keeps its permit forever, so a pathological reader can cost at most this many
/// threads, after which read-ahead simply stops happening.
const SPECULATION_BUDGET: usize = 64;

/// How far the producer may run ahead of what the consumer has actually asked
/// for.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ReadAhead {
    /// Pull only what the consumer has polled for. A `LIMIT 1` query pulls
    /// exactly one batch, so a reader that blocks on its *next* batch is never
    /// entered, and a reader with side effects (a paginated API) is never asked
    /// for pages the query does not use.
    OnDemand,
    /// Allow read-ahead up to the channel capacity, overlapping producer and
    /// consumer, bounded by [`SPECULATION_BUDGET`]. For sources whose pull is
    /// expected to terminate on its own -- e.g. pyarrow's own scanner.
    Buffered,
}

/// Permits for [`SPECULATION_BUDGET`]; leaked deliberately when a speculative
/// pull never returns.
fn speculation_budget() -> &'static Arc<Semaphore> {
    static BUDGET: OnceLock<Arc<Semaphore>> = OnceLock::new();
    BUDGET.get_or_init(|| Arc::new(Semaphore::new(SPECULATION_BUDGET)))
}

/// Permission to perform one pull, held until that pull returns.
enum Credit {
    /// The consumer polled for this batch.
    Demanded,
    /// Read-ahead: holds a [`speculation_budget`] permit so a pull that never
    /// returns is accounted for.
    Speculative(#[allow(dead_code)] tokio::sync::OwnedSemaphorePermit),
}

/// Take a speculation permit if the budget allows.
fn try_speculate(read_ahead: ReadAhead) -> Option<Credit> {
    match read_ahead {
        ReadAhead::OnDemand => None,
        ReadAhead::Buffered => Arc::clone(speculation_budget())
            .try_acquire_owned()
            .ok()
            .map(Credit::Speculative),
    }
}

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
/// * Under [`ReadAhead::Buffered`] it may be called for batches the query never
///   consumes; under [`ReadAhead::OnDemand`] it is not.
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
/// A coordinator *async task* runs the pull loop: it awaits demand from the
/// consumer and a free channel slot (parking as a cheap async task -- no thread --
/// when the consumer is slow or has stopped) and only then pulls on the blocking
/// pool via `spawn_blocking`. That blocking task drains batches only while demand
/// and slots remain, and returns its thread as soon as either runs out, so a
/// stream that is polled once and then abandoned (kept alive but not drained)
/// holds **zero** blocking threads -- it just parks the coordinator. This avoids
/// the blocking-pool exhaustion hang a lifetime producer parked in
/// `blocking_send` causes once enough streams are abandoned. Draining several
/// batches per dispatch (rather than one) keeps the per-batch cost of a
/// many-small-batches scan at roughly one channel send.
///
/// Read-ahead is governed by `read_ahead` (see [`ReadAhead`]): with
/// [`ReadAhead::OnDemand`] the producer pulls only batches the consumer has polled
/// for, so a `LIMIT 1` query enters the reader exactly once and cannot strand a
/// thread in a pull nobody wanted.
///
/// Cancellation: dropping the returned stream closes the channel *and* aborts the
/// coordinator (the builder's `JoinSet`), so no further pull is dispatched. A
/// pull already in flight still runs to completion -- Rust cannot interrupt a
/// blocking call -- so a pull that blocks forever holds its thread until it
/// returns.
///
/// GIL discipline: the pull runs inside `spawn_blocking` (never an async worker)
/// and is dropped there as well, so taking the GIL in either is safe.
pub fn spawn_channel_stream(
    schema: SchemaRef,
    pull: BatchPull,
    read_ahead: ReadAhead,
) -> SendableRecordBatchStream {
    // The builder owns the channel, propagates panics to the consumer, and aborts
    // the coordinator when the stream is dropped.
    let mut builder = RecordBatchReceiverStream::builder(Arc::clone(&schema), CHANNEL_CAPACITY);
    let tx = builder.tx();

    // One permit == permission to pull one batch, added by the consumer for each
    // batch it polls for.
    let demand = Arc::new(Semaphore::new(0));
    let producer_demand = Arc::clone(&demand);

    builder.spawn(async move {
        let mut guard = PullGuard::new(pull);
        loop {
            // Pull on demand, or speculatively while the budget allows. Falling
            // back to waiting for demand is always safe -- read-ahead is an
            // optimisation, never a requirement for progress.
            let credit = match producer_demand.try_acquire() {
                Ok(granted) => {
                    granted.forget();
                    Credit::Demanded
                }
                Err(_) => match try_speculate(read_ahead) {
                    Some(credit) => credit,
                    // Park until the consumer wants a batch. Err => the semaphore
                    // was closed with the stream => stop.
                    None => {
                        let Ok(granted) = producer_demand.acquire().await else {
                            break;
                        };
                        granted.forget();
                        Credit::Demanded
                    }
                },
            };
            // Backpressure without a pinned thread: park here until a slot frees.
            // Err => the receiver was dropped (query cancelled) => stop.
            let Ok(permit) = tx.clone().reserve_owned().await else {
                break;
            };
            // Pull on the blocking pool; the closure is moved in and handed back
            // so its reader survives across rounds.
            let pull = guard.take();
            let round_demand = Arc::clone(&producer_demand);
            let joined = tokio::task::spawn_blocking(move || {
                let mut pull = pull;
                // `credit` (and any the drain takes) is released only when the
                // pull returns, so a pull that never returns keeps it.
                let _credit = credit;
                let ended = drain_batches(&mut pull, permit, &round_demand, read_ahead);
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

    Box::pin(DemandStream {
        inner: builder.build(),
        schema,
        demand,
        requested: false,
    })
}

/// Grants the producer permission to pull the batch the consumer is polling for,
/// so nothing is read speculatively under [`ReadAhead::OnDemand`].
struct DemandStream {
    inner: SendableRecordBatchStream,
    schema: SchemaRef,
    demand: Arc<Semaphore>,
    /// True once a batch has been asked for and not yet delivered: repeated polls
    /// of a pending stream must not stack up credit.
    requested: bool,
}

impl Stream for DemandStream {
    type Item = Result<RecordBatch>;

    fn poll_next(mut self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Option<Self::Item>> {
        let this = &mut *self;
        if !this.requested {
            this.demand.add_permits(1);
            this.requested = true;
        }
        let polled = this.inner.as_mut().poll_next(cx);
        if let Poll::Ready(Some(_)) = &polled {
            this.requested = false;
        }
        polled
    }
}

impl RecordBatchStream for DemandStream {
    fn schema(&self) -> SchemaRef {
        Arc::clone(&self.schema)
    }
}

/// Pull batches into `permit`'s channel while credit and free slots both last.
/// Returns `true` when the stream is finished (input exhausted or terminal error).
///
/// Runs on the blocking pool, so it may hold the GIL and block. It never waits on
/// a full channel: it returns instead, handing the thread back while the
/// coordinator parks. Draining several batches per dispatch is what keeps the
/// per-batch cost of a many-small-batches scan at roughly one channel send.
fn drain_batches(
    pull: &mut BatchPull,
    permit: OwnedPermit<Result<RecordBatch>>,
    demand: &Semaphore,
    read_ahead: ReadAhead,
) -> bool {
    let mut permit = permit;
    // Held for as long as this dispatch runs, so a pull that never returns keeps
    // the speculation permits it drew.
    let mut credits: Vec<Credit> = Vec::new();
    loop {
        match pull() {
            Some(Ok(batch)) => {
                let tx = permit.send(Ok(batch));
                // Take the next slot before the credit for it, so credit is never
                // consumed without a batch to put in it. Channel full (consumer
                // behind) or closed (cancelled): stop holding this thread and let
                // the coordinator decide.
                let Ok(next) = tx.try_reserve_owned() else {
                    return false;
                };
                // Continue on demand the consumer has already granted, else on
                // read-ahead the budget still allows.
                match demand.try_acquire() {
                    Ok(granted) => granted.forget(),
                    Err(_) => match try_speculate(read_ahead) {
                        Some(credit) => credits.push(credit),
                        None => return false,
                    },
                }
                permit = next;
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
