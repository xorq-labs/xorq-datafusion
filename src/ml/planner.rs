//! Physical planning for ML logical nodes: `ExtensionPlanner` and `QueryPlanner`.

use std::sync::Arc;

use async_trait::async_trait;
use datafusion::catalog::Session;
use datafusion::common::plan_err;
use datafusion::error::Result;
use datafusion::execution::context::QueryPlanner;
use datafusion::execution::session_state::SessionState;
use datafusion::logical_expr::UserDefinedLogicalNodeCore;
use datafusion::logical_expr::{LogicalPlan, UserDefinedLogicalNode};
use datafusion::physical_plan::ExecutionPlan;
use datafusion::physical_planner::{DefaultPhysicalPlanner, ExtensionPlanner, PhysicalPlanner};
use datafusion_expr::physical_planning_context::PhysicalPlanningContext;

use super::exec::iterate::{IterateExec, LoopStateExec};
use super::nodes::iterate::{Iterate, LoopState};

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
        node: &dyn UserDefinedLogicalNode,
        _logical_inputs: &[&LogicalPlan],
        physical_inputs: &[Arc<dyn ExecutionPlan>],
        session: &dyn Session,
        _planning_ctx: &PhysicalPlanningContext,
    ) -> Result<Option<Arc<dyn ExecutionPlan>>> {
        let any = node.as_any();
        if let Some(state) = any.downcast_ref::<LoopState>() {
            return Ok(Some(Arc::new(LoopStateExec::new(
                state.handle.clone(),
                Arc::new(state.schema.as_arrow().clone()),
            ))));
        }
        if let Some(iterate) = any.downcast_ref::<Iterate>() {
            let Some(state) = session.as_any().downcast_ref::<SessionState>() else {
                return plan_err!("Iterate needs a SessionState to re-plan its body");
            };
            // physical_inputs[1] (the body planned once) is unused: the body
            // is re-planned on every iteration from its logical plan.
            let Some(init) = physical_inputs.first() else {
                return plan_err!("Iterate has no planned init input");
            };
            return Ok(Some(Arc::new(IterateExec::new(
                Arc::clone(init),
                iterate.body.clone(),
                iterate.key.clone(),
                iterate.max_iter,
                iterate.converged.clone(),
                iterate.handle.clone(),
                state.clone(),
                Arc::new(
                    UserDefinedLogicalNodeCore::schema(iterate)
                        .as_arrow()
                        .clone(),
                ),
            ))));
        }
        Ok(None)
    }
}
