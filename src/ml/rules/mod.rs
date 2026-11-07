//! ML optimizer rules. They match `StepProperties`, never concrete step types.

use std::sync::Arc;

use datafusion::optimizer::OptimizerRule;

/// Every ML optimizer rule, in the order `with_ml` appends them after
/// DataFusion's defaults. Empty until the first ML node lands.
pub(crate) fn all() -> Vec<Arc<dyn OptimizerRule + Send + Sync>> {
    vec![]
}
