//! Physical planning for ML logical nodes: `ExtensionPlanner` and `QueryPlanner`.

use std::sync::Arc;

use async_trait::async_trait;
use datafusion::catalog::Session;
use datafusion::error::Result;
use datafusion::execution::context::QueryPlanner;
use datafusion::logical_expr::{LogicalPlan, UserDefinedLogicalNode};
use datafusion::physical_plan::ExecutionPlan;
use datafusion::physical_planner::{DefaultPhysicalPlanner, ExtensionPlanner, PhysicalPlanner};
use datafusion_expr::physical_planning_context::PhysicalPlanningContext;

/// Query planner installed by [`crate::ml::session::with_ml`]: DataFusion's
/// default physical planner plus [`MlExtensionPlanner`]. For a plan with no ML
/// nodes it plans exactly as the default planner does.
#[derive(Debug, Default)]
pub(crate) struct MlQueryPlanner;

#[async_trait]
impl QueryPlanner for MlQueryPlanner {
    async fn create_physical_plan(
        &self,
        logical_plan: &LogicalPlan,
        session: &dyn Session,
    ) -> Result<Arc<dyn ExecutionPlan>> {
        DefaultPhysicalPlanner::with_extension_planners(vec![Arc::new(MlExtensionPlanner)])
            .create_physical_plan(logical_plan, session)
            .await
    }
}

/// Plans ML logical nodes; returns `None` for any other node, so the default
/// planner (and any other extension planner) keeps handling it.
#[derive(Debug, Default)]
pub(crate) struct MlExtensionPlanner;

#[async_trait]
impl ExtensionPlanner for MlExtensionPlanner {
    async fn plan_extension(
        &self,
        _planner: &dyn PhysicalPlanner,
        _node: &dyn UserDefinedLogicalNode,
        _logical_inputs: &[&LogicalPlan],
        _physical_inputs: &[Arc<dyn ExecutionPlan>],
        _session: &dyn Session,
        _planning_ctx: &PhysicalPlanningContext,
    ) -> Result<Option<Arc<dyn ExecutionPlan>>> {
        Ok(None)
    }
}
