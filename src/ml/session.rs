//! `with_ml`: installs the ML query planner and optimizer rules on a session.

use std::any::Any;
use std::sync::Arc;

use datafusion::execution::session_state::{SessionState, SessionStateBuilder};

use super::planner::MlQueryPlanner;
use super::rules;

/// Install the ML query planner and append the ML optimizer rules after
/// DataFusion's defaults. Inert for plans without ML nodes: the planner
/// delegates to the default physical planner and the rules match nothing.
pub(crate) fn with_ml(builder: SessionStateBuilder) -> SessionStateBuilder {
    rules::all()
        .into_iter()
        .fold(builder, |b, rule| b.with_optimizer_rule(rule))
        .with_query_planner(Arc::new(MlQueryPlanner))
}

/// Whether `state` plans with the ML query planner (so ML nodes can execute).
pub(crate) fn has_ml(state: &SessionState) -> bool {
    let planner: &dyn Any = state.query_planner().as_ref();
    planner.is::<MlQueryPlanner>()
}
