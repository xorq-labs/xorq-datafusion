use std::future::Future;
use std::pin::Pin;
use std::sync::{Arc, OnceLock, RwLock};
use std::task::{Context, Poll};

use arrow::array::ArrayRef;
use arrow::array::RecordBatch;
use arrow::datatypes::SchemaRef;
use datafusion::execution::SendableRecordBatchStream;
use datafusion::physical_expr::{EquivalenceProperties, Partitioning};
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
/// * It runs on a thread that may hold the GIL and block, never on an async
///   worker. A stream normally gets one dedicated thread for its whole life (see
///   [`AFFINE_THREAD_BUDGET`]), so a reader bound to the thread that created it
///   keeps working; past that budget consecutive batches may run on different
///   blocking-pool threads, so thread affinity is best-effort, not guaranteed.
/// * It is only called again after returning `Some(Ok(_))`: `None` and
///   `Some(Err(_))` are both terminal.
/// * Under [`ReadAhead::Buffered`] it may be called for batches the query never
///   consumes; under [`ReadAhead::OnDemand`] it is not.
/// * It is dropped on the blocking pool too (see [`PullGuard`]), so destroying
///   the Python objects it owns may take the GIL. Once [`quiesce_python_pulls`]
///   has closed the gate it is leaked instead, never dropped: cleanup that only
///   runs on drop (a generator's `finally`) does not run.
pub type BatchPull = Box<dyn FnMut() -> Option<Result<RecordBatch>> + Send>;

/// Keeps pull threads and Python callbacks out of Python once the interpreter
/// starts shutting down.
///
/// Pull threads are not Python threads: nothing joins them before
/// `Py_FinalizeEx`. One that is inside a pull when finalization starts (in
/// `time.sleep`, or any call that released the GIL) tries to take the GIL back
/// on a finalizing interpreter. CPython 3.13 answers with `pthread_exit`; the
/// forced unwind runs pyarrow's GIL guard destructor and aborts the process
/// with "PyGILState_Release: thread state ... must be current when releasing".
/// CPython 3.14 hangs the thread instead.
///
/// So every pull and every reader disposal holds a ticket from this gate, and
/// the `atexit` hook ([`quiesce_python_pulls`]) closes it and waits, with the
/// GIL released, for the tickets out to come back. A closed gate refuses new
/// tickets: a stream whose next pull is refused ends with an error, and a reader
/// whose disposal is refused is leaked -- the process is exiting.
struct PythonGate {
    state: std::sync::Mutex<GateState>,
    idle: std::sync::Condvar,
}

struct GateState {
    closed: bool,
    in_flight: usize,
}

static PYTHON_GATE: PythonGate = PythonGate {
    state: std::sync::Mutex::new(GateState {
        closed: false,
        in_flight: 0,
    }),
    idle: std::sync::Condvar::new(),
};

/// Permission to be inside Python from a thread Python does not own; returned
/// on drop.
struct GateTicket;

impl Drop for GateTicket {
    fn drop(&mut self) {
        let gate = &PYTHON_GATE;
        let mut state = gate.state.lock().unwrap_or_else(|e| e.into_inner());
        state.in_flight -= 1;
        if state.in_flight == 0 {
            gate.idle.notify_all();
        }
    }
}

/// A ticket, or `None` once [`quiesce_python_pulls`] has closed the gate.
fn enter_python() -> Option<GateTicket> {
    let mut state = PYTHON_GATE.state.lock().unwrap_or_else(|e| e.into_inner());
    if state.closed {
        return None;
    }
    state.in_flight += 1;
    Some(GateTicket)
}

/// The error for any Python entry refused once the gate is closed; `what`
/// finishes the sentence.
fn closed_error(what: std::fmt::Arguments) -> datafusion_common::DataFusionError {
    datafusion_common::DataFusionError::Execution(format!(
        "xorq_datafusion was closed (by `close()` or at interpreter exit); {what}"
    ))
}

fn runtime_closed() -> datafusion_common::DataFusionError {
    closed_error(format_args!(
        "Python-backed streams stop before their next pull"
    ))
}

/// An error from a Python callback, as DataFusion sees it.
pub(crate) trait IntoDataFusionError {
    fn into_datafusion_error(self) -> datafusion_common::DataFusionError;
}

impl IntoDataFusionError for PyErr {
    fn into_datafusion_error(self) -> datafusion_common::DataFusionError {
        crate::errors::to_external_err(self)
    }
}

impl IntoDataFusionError for datafusion_common::DataFusionError {
    fn into_datafusion_error(self) -> datafusion_common::DataFusionError {
        self
    }
}

fn python_closed(site: &str) -> datafusion_common::DataFusionError {
    closed_error(format_args!("{site} no longer calls into Python"))
}

/// Run `f` with the GIL, from code DataFusion may run on a thread Python does
/// not own: a tokio worker, the blocking pool, or planning inside `block_on`.
///
/// Holds a ticket from the same gate as the read-ahead pulls, so `close()` (and
/// the `atexit` hook) waits for a callback already inside Python, and once the
/// gate is closed refuses to enter Python at all: taking the GIL on a
/// finalizing interpreter crashes the process (see [`PythonGate`]). `site`
/// names the caller in that error, and in the debug-build note below.
pub(crate) fn with_python<T, E: IntoDataFusionError>(
    site: &'static str,
    f: impl for<'py> FnOnce(Python<'py>) -> std::result::Result<T, E>,
) -> Result<T> {
    let Some(_entered) = enter_python() else {
        return Err(python_closed(site));
    };
    note_python_on_worker(site);
    // The ticket outlives the GIL: it is returned only after `attach` released
    // it, so `quiesce_python_pulls` never waits on a thread that holds the GIL.
    Python::attach(f).map_err(IntoDataFusionError::into_datafusion_error)
}

/// Debug builds only, with `XORQ_DATAFUSION_DEBUG_GIL` set: print once per
/// site when it takes the GIL on a tokio worker, which holds that worker for as
/// long as the Python code runs (see xorq-labs/xorq-datafusion#46).
#[cfg(debug_assertions)]
fn note_python_on_worker(site: &'static str) {
    static ENABLED: OnceLock<bool> = OnceLock::new();
    static SEEN: std::sync::Mutex<Vec<&'static str>> = std::sync::Mutex::new(Vec::new());
    if !*ENABLED.get_or_init(|| std::env::var_os("XORQ_DATAFUSION_DEBUG_GIL").is_some()) {
        return;
    }
    // Some inside any task on the runtime, including under block_in_place and
    // in spawn_blocking closures (tokio sets the id for blocking tasks too), so
    // the pool pulls, our only blocking-pool callers, mark themselves.
    if tokio::task::try_id().is_none() || ON_BLOCKING_POOL.get() {
        return;
    }
    let mut seen = SEEN.lock().unwrap_or_else(|e| e.into_inner());
    if !seen.contains(&site) {
        seen.push(site);
        eprintln!("xorq_datafusion: {site} takes the GIL on a tokio worker");
    }
}

#[cfg(not(debug_assertions))]
fn note_python_on_worker(_site: &'static str) {}

#[cfg(debug_assertions)]
thread_local! {
    /// Set while a pool pull runs, so [`note_python_on_worker`] can tell the
    /// blocking pool from an async worker.
    static ON_BLOCKING_POOL: std::cell::Cell<bool> = const { std::cell::Cell::new(false) };
}

/// Marks the current blocking-pool thread for [`note_python_on_worker`] until
/// dropped.
struct BlockingPoolMark {
    #[cfg(debug_assertions)]
    previous: bool,
}

impl BlockingPoolMark {
    fn enter() -> Self {
        Self {
            #[cfg(debug_assertions)]
            previous: ON_BLOCKING_POOL.replace(true),
        }
    }
}

impl Drop for BlockingPoolMark {
    fn drop(&mut self) {
        #[cfg(debug_assertions)]
        ON_BLOCKING_POOL.set(self.previous);
    }
}

/// Destroy a pull, which releases the Python objects it captured -- unless the
/// gate is closed, in which case the pull is leaked rather than touch an
/// interpreter that may already be finalizing.
fn dispose_pull(pull: BatchPull) {
    match enter_python() {
        Some(_entered) => drop(pull),
        None => std::mem::forget(pull),
    }
}

/// A pull that goes through [`dispose_pull`] however it is dropped: normally,
/// by an unwind out of the pull, or inside a closure the runtime discards
/// without running (a `spawn_blocking` refused during shutdown).
struct GatedPull(Option<BatchPull>);

impl GatedPull {
    fn get(&mut self) -> &mut BatchPull {
        self.0.as_mut().expect("pull is present until into_inner")
    }

    fn into_inner(mut self) -> BatchPull {
        self.0.take().expect("pull is present until into_inner")
    }
}

impl Drop for GatedPull {
    fn drop(&mut self) {
        if let Some(pull) = self.0.take() {
            dispose_pull(pull);
        }
    }
}

/// Close the gate and wait up to `timeout` (`Duration::ZERO`: do not wait;
/// `Duration::MAX`: no limit) for every pull already inside Python to return.
/// Returns `false` if some are still running at the deadline (a pull blocked on
/// something that never comes); those can still take the process down at
/// finalization, as before.
///
/// Must be called with the GIL released: the pulls being waited on need it to
/// finish.
pub fn quiesce_python_pulls(timeout: std::time::Duration) -> bool {
    let gate = &PYTHON_GATE;
    let mut state = gate.state.lock().unwrap_or_else(|e| e.into_inner());
    state.closed = true;
    let (state, _) = gate
        .idle
        .wait_timeout_while(state, timeout, |s| s.in_flight > 0)
        .unwrap_or_else(|e| e.into_inner());
    state.in_flight == 0
}

/// Streams that may hold a dedicated pull thread at once, process-wide.
///
/// A dedicated thread keeps a reader on the thread that created it, which readers
/// bound to thread-local state (a `sqlite3` cursor, `threading.local()`) require.
/// The thread parks in `recv()` between batches, so dropping the stream wakes it
/// and it exits -- unlike a producer parked in `blocking_send`, it cannot be
/// stranded by an abandoned stream. It is still an OS thread per *live* stream
/// (~115 kB resident each), hence the cap: past it, streams fall back to the
/// blocking pool and lose affinity rather than the process losing its thread
/// budget. The cap sits well above any plausible scan concurrency
/// (`target_partitions` per query), and the readers that hit it in bulk --
/// pyarrow's own -- do not need affinity.
const AFFINE_THREAD_BUDGET: usize = 128;

/// Permits for [`AFFINE_THREAD_BUDGET`], released when a pull thread exits.
fn affine_thread_budget() -> &'static Arc<Semaphore> {
    static BUDGET: OnceLock<Arc<Semaphore>> = OnceLock::new();
    BUDGET.get_or_init(|| Arc::new(Semaphore::new(AFFINE_THREAD_BUDGET)))
}

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
        // Gated however the closure ends: a runtime that is shutting down drops
        // a refused `spawn_blocking` closure on this (worker) thread unrun; the
        // gate is closed by then, so the pull is leaked, not destroyed here.
        let pull = GatedPull(Some(pull));
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

/// One drain round handed to a stream's pull thread.
struct PullJob {
    permit: OwnedPermit<Result<RecordBatch>>,
    demand: Arc<Semaphore>,
    schema: SchemaRef,
    /// Released only when the round finishes, so a pull that never returns keeps
    /// whatever it drew from the speculation budget.
    credit: Credit,
    /// `Ok(true)` => the stream is finished; `Err` carries a panic payload to
    /// re-raise on the consumer.
    done: tokio::sync::oneshot::Sender<std::thread::Result<bool>>,
}

/// Sent to a stream's pull thread: the reader first, then one message per round.
///
/// The reader travels over the channel rather than into the thread closure so a
/// failed spawn hands it back instead of dropping it on the calling thread (which
/// is usually an async worker, where destroying Python state must not happen).
enum PullMessage {
    Init(BatchPull),
    Job(PullJob),
}

/// Where a stream's pull runs.
enum PullHost {
    /// One thread for the stream's whole life: the reader is created, resumed and
    /// destroyed on the same thread, so thread-affine readers keep working.
    Affine(std::sync::mpsc::Sender<PullMessage>),
    /// A fresh blocking-pool task per round. No affinity, but no thread is held
    /// while the stream is idle.
    Pool(PullGuard),
}

impl PullHost {
    /// Prefer a dedicated thread; fall back to the pool when the budget is spent
    /// or the thread cannot be spawned.
    fn new(pull: BatchPull, read_ahead: ReadAhead) -> Self {
        let Ok(budget) = Arc::clone(affine_thread_budget()).try_acquire_owned() else {
            return Self::Pool(PullGuard::new(pull));
        };
        let (jobs, requests) = std::sync::mpsc::channel::<PullMessage>();
        let spawned = std::thread::Builder::new()
            .name("xorq-pull".to_string())
            .spawn(move || {
                // Released when this thread exits, so the budget counts live pull
                // threads rather than streams that once had one.
                let _budget = budget;
                run_affine_pull(requests, read_ahead);
            });
        // Thread limit reached, or the thread died before taking the reader: the
        // pool still works, just without affinity.
        match spawned {
            Ok(_handle) => match jobs.send(PullMessage::Init(pull)) {
                Ok(()) => Self::Affine(jobs),
                Err(returned) => match returned.0 {
                    PullMessage::Init(pull) => Self::Pool(PullGuard::new(pull)),
                    PullMessage::Job(_) => unreachable!("only Init is sent here"),
                },
            },
            Err(_) => Self::Pool(PullGuard::new(pull)),
        }
    }

    /// Run one drain round. `Ok(true)` => the stream is finished.
    async fn round(
        &mut self,
        permit: OwnedPermit<Result<RecordBatch>>,
        demand: &Arc<Semaphore>,
        schema: &SchemaRef,
        credit: Credit,
        read_ahead: ReadAhead,
    ) -> Result<bool> {
        match self {
            Self::Affine(jobs) => {
                let (done, finished) = tokio::sync::oneshot::channel();
                let job = PullJob {
                    permit,
                    demand: Arc::clone(demand),
                    schema: Arc::clone(schema),
                    credit,
                    done,
                };
                if jobs.send(PullMessage::Job(job)).is_err() {
                    // The pull thread is gone (it only exits after reporting the
                    // end of the stream, or after a panic it already reported).
                    return Ok(true);
                }
                match finished.await {
                    Ok(Ok(ended)) => Ok(ended),
                    Ok(Err(panic)) => std::panic::resume_unwind(panic),
                    // Thread died without reporting: treat as end of stream.
                    Err(_) => Ok(true),
                }
            }
            Self::Pool(guard) => {
                // Gated before it is moved into the closure, so a panic out of the
                // pull, or a closure the runtime drops unrun (a `spawn_blocking`
                // refused during shutdown, dropped on this worker), still disposes
                // it through the gate.
                let pull = GatedPull(Some(guard.take()));
                let demand = Arc::clone(demand);
                let schema = Arc::clone(schema);
                let joined = tokio::task::spawn_blocking(move || {
                    let _mark = BlockingPoolMark::enter();
                    let mut pull = pull;
                    let _credit = credit;
                    let ended = drain_batches(pull.get(), permit, &demand, read_ahead, &schema);
                    // Guarded on the way back too: if this task was aborted, the
                    // runtime drops the output, and the pull must still be
                    // disposed through `dispose_pull`.
                    (ended, PullGuard::new(pull.into_inner()))
                })
                .await;
                match joined {
                    Ok((ended, mut returned)) => {
                        guard.put(returned.take());
                        Ok(ended)
                    }
                    // The pull panicked (the closure died with its task, so the
                    // guard is already empty). Re-raise here so the builder can
                    // resume the original payload on the consumer instead of an
                    // opaque JoinError.
                    Err(join_err) if join_err.is_panic() => {
                        std::panic::resume_unwind(join_err.into_panic())
                    }
                    Err(join_err) => Err(datafusion_common::DataFusionError::External(Box::new(
                        join_err,
                    ))),
                }
            }
        }
    }
}

/// Body of a stream's dedicated pull thread.
///
/// Parks in `recv()` between rounds, so dropping the stream (which drops the job
/// sender) wakes it: the reader is destroyed here, on a thread that may hold the
/// GIL and that created it in the first place.
fn run_affine_pull(requests: std::sync::mpsc::Receiver<PullMessage>, read_ahead: ReadAhead) {
    let Ok(PullMessage::Init(mut pull)) = requests.recv() else {
        return;
    };
    while let Ok(PullMessage::Job(job)) = requests.recv() {
        let PullJob {
            permit,
            demand,
            schema,
            credit,
            done,
        } = job;
        let outcome = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            drain_batches(&mut pull, permit, &demand, read_ahead, &schema)
        }));
        drop(credit);
        let ended = matches!(outcome, Ok(true) | Err(_));
        // The receiver is gone if the query was cancelled; nothing to report to.
        let _ = done.send(outcome);
        if ended {
            break;
        }
    }
    dispose_pull(pull);
}

/// Bridge a synchronous, blocking `pull` (a Python reader) to an async
/// `SendableRecordBatchStream` without ever pinning a blocking-pool thread while
/// idle.
///
/// A coordinator *async task* runs the pull loop: it awaits demand from the
/// consumer and a free channel slot (parking as a cheap async task -- no thread --
/// when the consumer is slow or has stopped) and only then dispatches a drain
/// round to the stream's [`PullHost`]. A round ends as soon as demand or slots run
/// out, so an abandoned stream (kept alive but not drained) never sits in a pull:
/// it holds at most its parked pull thread, which wakes and exits when the stream
/// is dropped. That is what avoids the blocking-pool exhaustion hang a lifetime
/// producer parked in `blocking_send` causes. Draining several batches per round
/// (rather than one) keeps the per-batch cost of a many-small-batches scan at
/// roughly one channel send.
///
/// Batches are checked against `schema` before they are forwarded: a drifted batch
/// fails the query rather than reaching kernels that trust the plan's types and
/// panic.
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
/// GIL discipline: the pull runs on a pull thread or the blocking pool (never an
/// async worker) and is dropped there as well, so taking the GIL in either is
/// safe.
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

    let producer_schema = Arc::clone(&schema);
    builder.spawn(async move {
        let mut host = PullHost::new(pull, read_ahead);
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
            // Never on an async worker: the pull holds the GIL and blocks.
            if host
                .round(
                    permit,
                    &producer_demand,
                    &producer_schema,
                    credit,
                    read_ahead,
                )
                .await?
            {
                break;
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

/// Reject a batch whose columns do not line up with the schema the plan
/// advertises.
///
/// Names and types must match positionally; nullability and metadata are not
/// compared, because pyarrow readers routinely differ there without affecting how
/// the data is read.
fn check_batch_schema(schema: &SchemaRef, batch: &RecordBatch) -> Result<()> {
    let actual = batch.schema_ref();
    if Arc::ptr_eq(schema, actual) {
        return Ok(());
    }
    let matches = schema.fields().len() == actual.fields().len()
        && schema
            .fields()
            .iter()
            .zip(actual.fields())
            .all(|(want, got)| want.name() == got.name() && want.data_type() == got.data_type());
    if matches {
        return Ok(());
    }
    let describe = |s: &arrow::datatypes::Schema| {
        s.fields()
            .iter()
            .map(|f| format!("{}: {}", f.name(), f.data_type()))
            .collect::<Vec<_>>()
            .join(", ")
    };
    Err(datafusion_common::DataFusionError::Execution(format!(
        "reader produced a batch that does not match the table schema: \
         expected [{}], got [{}]",
        describe(schema),
        describe(actual)
    )))
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
    schema: &SchemaRef,
) -> bool {
    let mut permit = permit;
    // Held for as long as this dispatch runs, so a pull that never returns keeps
    // the speculation permits it drew.
    let mut credits: Vec<Credit> = Vec::new();
    loop {
        // Every pull may enter Python, so it goes through the gate: once the
        // interpreter starts shutting down, end the stream instead.
        let Some(entered) = enter_python() else {
            permit.send(Err(runtime_closed()));
            return true;
        };
        let pulled = pull();
        drop(entered);
        match pulled {
            Some(Ok(batch)) => {
                // A batch that does not match the advertised schema is terminal:
                // downstream kernels trust the plan's schema and panic on a
                // mismatch (arrow's `as_primitive` on a string column), which
                // takes the process down instead of failing the query.
                if let Err(e) = check_batch_schema(schema, &batch) {
                    permit.send(Err(e));
                    return true;
                }
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
    try_get_tokio_handle().expect("tokio runtime has been shut down")
}

/// Like [`get_tokio_handle`], but returns `None` after [`shutdown_runtime`]
/// instead of panicking.
pub fn try_get_tokio_handle() -> Option<Handle> {
    get_runtime()
        .read()
        .unwrap()
        .as_ref()
        .map(|rt| rt.handle().clone())
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
            // try_from_array indexes without a bounds check, so an empty
            // result from the callback would panic.
            let result = result.and_then(|arr| {
                if arr.is_empty() {
                    return datafusion_common::exec_err!(
                        "scalar function returned an empty array for scalar arguments"
                    );
                }
                ScalarValue::try_from_array(&arr, 0)
            });
            result.map(ColumnarValue::Scalar)
        } else {
            result.map(ColumnarValue::Array)
        }
    })
}
