//! `with_ml`: installs the ML query planner and optimizer rules on a session.

use std::any::Any;
use std::sync::Arc;

use datafusion::execution::session_state::{SessionState, SessionStateBuilder};

use super::exec::welford::welford_udaf;
use super::planner::MlQueryPlanner;
use super::rules;

/// Install the ML query planner, append the ML optimizer rules after
/// DataFusion's defaults, and register the ML functions (`__ml_*` names, so
/// they cannot collide with user functions). Inert for plans without ML
/// nodes: the planner delegates to the default physical planner and the
/// rules match nothing.
///
/// Call after `with_default_features`, which would otherwise replace the
/// registered functions.
pub(crate) fn with_ml(builder: SessionStateBuilder) -> SessionStateBuilder {
    let mut builder = rules::all()
        .into_iter()
        .fold(builder, |b, rule| b.with_optimizer_rule(rule))
        .with_query_planner(Arc::new(MlQueryPlanner));
    builder
        .aggregate_functions()
        .get_or_insert_with(Vec::new)
        .push(welford_udaf());
    builder
}

/// Whether `state` plans with the ML query planner (so ML nodes can execute).
pub(crate) fn has_ml(state: &SessionState) -> bool {
    let planner: &dyn Any = state.query_planner().as_ref();
    planner.is::<MlQueryPlanner>()
}
