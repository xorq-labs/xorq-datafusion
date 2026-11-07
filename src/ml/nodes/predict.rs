//! `Predict`: label each input row with a fitted pipeline.

use std::fmt;
use std::sync::Arc;

use datafusion::arrow::datatypes::{DataType, Field};
use datafusion::common::{plan_err, DFSchema, DFSchemaRef, Result};
use datafusion::logical_expr::{Expr, LogicalPlan, UserDefinedLogicalNodeCore};

use crate::ml::properties::{PredictStep, StepProperties};

/// Adds an Int64 `output` column: the label the steps give each row's
/// `features`. Lowered to plain expressions by `LowerPredict`.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub(crate) struct Predict {
    pub(crate) input: LogicalPlan,
    pub(crate) features: Vec<String>,
    pub(crate) steps: Vec<PredictStep>,
    pub(crate) output: String,
    schema: DFSchemaRef,
}

impl Predict {
    pub(crate) fn try_new(
        input: LogicalPlan,
        features: Vec<String>,
        steps: Vec<PredictStep>,
        output: String,
    ) -> Result<Self> {
        for name in &features {
            if input.schema().field_with_unqualified_name(name).is_err() {
                return plan_err!("Predict feature {name:?} is not a column of the input");
            }
        }
        if input.schema().field_with_unqualified_name(&output).is_ok() {
            return plan_err!("Predict output column {output:?} already exists in the input");
        }
        match steps.split_last() {
            Some((last, rest))
                if last.nearest_centroid().is_some()
                    && rest.iter().all(|s| s.nearest_centroid().is_none()) => {}
            _ => return plan_err!("Predict steps must end with exactly one predictor"),
        }
        let output_field = Field::new(&output, DataType::Int64, true);
        let mut schema = input.schema().as_ref().clone();
        schema.merge(&DFSchema::from_unqualified_fields(
            vec![output_field].into(),
            Default::default(),
        )?);
        Ok(Self {
            input,
            features,
            steps,
            output,
            schema: Arc::new(schema),
        })
    }
}

// The schema derives from the input; the order ignores it (DFSchema has no
// PartialOrd).
impl PartialOrd for Predict {
    fn partial_cmp(&self, other: &Self) -> Option<std::cmp::Ordering> {
        (&self.input, &self.features, &self.steps, &self.output).partial_cmp(&(
            &other.input,
            &other.features,
            &other.steps,
            &other.output,
        ))
    }
}

impl UserDefinedLogicalNodeCore for Predict {
    fn name(&self) -> &str {
        "Predict"
    }

    fn inputs(&self) -> Vec<&LogicalPlan> {
        vec![&self.input]
    }

    fn schema(&self) -> &DFSchemaRef {
        &self.schema
    }

    fn expressions(&self) -> Vec<Expr> {
        vec![]
    }

    fn fmt_for_explain(&self, f: &mut fmt::Formatter) -> fmt::Result {
        let steps: Vec<String> = self.steps.iter().map(ToString::to_string).collect();
        write!(
            f,
            "Predict: features=[{}], steps=[{}], output={}",
            self.features.join(", "),
            steps.join(", "),
            self.output
        )
    }

    fn with_exprs_and_inputs(
        &self,
        _exprs: Vec<Expr>,
        mut inputs: Vec<LogicalPlan>,
    ) -> Result<Self> {
        if inputs.len() != 1 {
            return plan_err!("Predict takes 1 input, got {}", inputs.len());
        }
        Self::try_new(
            inputs.swap_remove(0),
            self.features.clone(),
            self.steps.clone(),
            self.output.clone(),
        )
    }
}
