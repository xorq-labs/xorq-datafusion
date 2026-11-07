//! `Iterate` and `LoopState`: a loop as a logical plan.
//!
//! `Iterate` runs `init` once into a loop value, then repeatedly runs `body`,
//! which reads the current loop value through a `LoopState` leaf, and merges
//! the body's output into the loop value by `key` (upsert), until the body
//! reports convergence or `max_iter` iterations have run. It outputs the final
//! loop value plus an `n_iter` column.

use std::cmp::Ordering;
use std::fmt;
use std::hash::{Hash, Hasher};
use std::sync::{Arc, RwLock};

use datafusion::arrow::array::RecordBatch;
use datafusion::arrow::datatypes::{DataType, Field};
use datafusion::common::{plan_err, DFSchema, DFSchemaRef, Result};
use datafusion::logical_expr::{Expr, LogicalPlan, UserDefinedLogicalNodeCore};

/// Output column holding the number of iterations run.
pub(crate) const N_ITER: &str = "__ml_n_iter";

/// The current value of a loop. Today it is always a table of rows; the type
/// keeps that out of the nodes' interface.
#[derive(Debug, Default)]
pub(crate) struct LoopValue {
    pub(crate) batches: Vec<RecordBatch>,
}

/// Shared handle to a loop value: written by the loop, read by `LoopState`.
/// Identity (not contents) defines equality, hashing and order.
#[derive(Debug, Clone, Default)]
pub(crate) struct LoopHandle(pub(crate) Arc<RwLock<LoopValue>>);

impl LoopHandle {
    fn id(&self) -> usize {
        Arc::as_ptr(&self.0) as *const () as usize
    }
}

impl PartialEq for LoopHandle {
    fn eq(&self, other: &Self) -> bool {
        Arc::ptr_eq(&self.0, &other.0)
    }
}

impl Eq for LoopHandle {}

impl Hash for LoopHandle {
    fn hash<H: Hasher>(&self, state: &mut H) {
        self.id().hash(state)
    }
}

impl PartialOrd for LoopHandle {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.id().cmp(&other.id()))
    }
}

/// How the body reports convergence: a boolean column of its output that is
/// true (on any row) once the loop should stop. The column is not part of
/// the loop value.
#[derive(Debug, Clone, PartialEq, Eq, Hash, PartialOrd)]
pub(crate) enum ConvergenceSpec {
    Column(String),
}

/// How the body's output merges into the loop value.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd)]
pub(crate) enum Upsert {
    /// Rows whose key appears in the output are replaced; others are kept.
    ByKey,
}

/// Leaf reading the current loop value.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub(crate) struct LoopState {
    pub(crate) handle: LoopHandle,
    pub(crate) schema: DFSchemaRef,
}

// The schema is not ordered (DFSchema has no PartialOrd); the handle decides.
impl PartialOrd for LoopState {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        self.handle.partial_cmp(&other.handle)
    }
}

impl UserDefinedLogicalNodeCore for LoopState {
    fn name(&self) -> &str {
        "LoopState"
    }

    fn inputs(&self) -> Vec<&LogicalPlan> {
        vec![]
    }

    fn schema(&self) -> &DFSchemaRef {
        &self.schema
    }

    fn expressions(&self) -> Vec<Expr> {
        vec![]
    }

    fn fmt_for_explain(&self, f: &mut fmt::Formatter) -> fmt::Result {
        let columns: Vec<&str> = self
            .schema
            .fields()
            .iter()
            .map(|f| f.name().as_str())
            .collect();
        write!(f, "LoopState: [{}]", columns.join(", "))
    }

    fn with_exprs_and_inputs(&self, _exprs: Vec<Expr>, _inputs: Vec<LogicalPlan>) -> Result<Self> {
        Ok(self.clone())
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub(crate) struct Iterate {
    pub(crate) init: LogicalPlan,
    pub(crate) body: LogicalPlan,
    pub(crate) key: Vec<String>,
    pub(crate) max_iter: usize,
    pub(crate) converged: ConvergenceSpec,
    pub(crate) semantics: Upsert,
    pub(crate) handle: LoopHandle,
    schema: DFSchemaRef,
}

impl Iterate {
    /// Checks that the body's output is the loop value (the init's schema)
    /// plus the convergence column, and that the key columns exist.
    pub(crate) fn try_new(
        init: LogicalPlan,
        body: LogicalPlan,
        key: Vec<String>,
        max_iter: usize,
        converged: ConvergenceSpec,
        handle: LoopHandle,
    ) -> Result<Self> {
        let ConvergenceSpec::Column(flag) = &converged;
        let state_fields = init.schema().fields();
        let body_fields: Vec<_> = body
            .schema()
            .fields()
            .iter()
            .filter(|f| f.name() != flag)
            .collect();
        let same = state_fields.len() == body_fields.len()
            && state_fields
                .iter()
                .zip(&body_fields)
                .all(|(a, b)| a.name() == b.name() && a.data_type() == b.data_type());
        if !same {
            return plan_err!(
                "Iterate body must output the loop value columns plus {flag:?}; \
                 init has {:?}, body has {:?}",
                init.schema().fields(),
                body.schema().fields()
            );
        }
        if body.schema().field_with_unqualified_name(flag).is_err() {
            return plan_err!("Iterate body has no convergence column {flag:?}");
        }
        for k in &key {
            if init.schema().field_with_unqualified_name(k).is_err() {
                return plan_err!("Iterate key column {k:?} is not in the loop value");
            }
        }
        if max_iter == 0 {
            return plan_err!("Iterate max_iter must be at least 1");
        }
        let mut fields: Vec<Field> = state_fields.iter().map(|f| f.as_ref().clone()).collect();
        fields.push(Field::new(N_ITER, DataType::UInt64, false));
        let schema = Arc::new(DFSchema::from_unqualified_fields(
            fields.into(),
            Default::default(),
        )?);
        Ok(Self {
            init,
            body,
            key,
            max_iter,
            converged,
            semantics: Upsert::ByKey,
            handle,
            schema,
        })
    }
}

// The schema derives from `init`, so it is left out of the order.
impl PartialOrd for Iterate {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        (
            &self.init,
            &self.body,
            &self.key,
            self.max_iter,
            &self.converged,
            self.semantics,
            &self.handle,
        )
            .partial_cmp(&(
                &other.init,
                &other.body,
                &other.key,
                other.max_iter,
                &other.converged,
                other.semantics,
                &other.handle,
            ))
    }
}

impl UserDefinedLogicalNodeCore for Iterate {
    fn name(&self) -> &str {
        "Iterate"
    }

    fn inputs(&self) -> Vec<&LogicalPlan> {
        vec![&self.init, &self.body]
    }

    fn schema(&self) -> &DFSchemaRef {
        &self.schema
    }

    fn expressions(&self) -> Vec<Expr> {
        vec![]
    }

    fn fmt_for_explain(&self, f: &mut fmt::Formatter) -> fmt::Result {
        let ConvergenceSpec::Column(flag) = &self.converged;
        write!(
            f,
            "Iterate: key=[{}], max_iter={}, converged={flag}, semantics={:?}",
            self.key.join(", "),
            self.max_iter,
            self.semantics
        )
    }

    fn with_exprs_and_inputs(&self, _exprs: Vec<Expr>, inputs: Vec<LogicalPlan>) -> Result<Self> {
        let [init, body]: [LogicalPlan; 2] = match inputs.try_into() {
            Ok(inputs) => inputs,
            Err(inputs) => return plan_err!("Iterate takes 2 inputs, got {}", inputs.len()),
        };
        Self::try_new(
            init,
            body,
            self.key.clone(),
            self.max_iter,
            self.converged.clone(),
            self.handle.clone(),
        )
    }

    fn necessary_children_exprs(&self, _output_columns: &[usize]) -> Option<Vec<Vec<usize>>> {
        // Every column of both inputs is needed: the loop value round-trips
        // through the body, so neither side may be pruned.
        Some(vec![
            (0..self.init.schema().fields().len()).collect(),
            (0..self.body.schema().fields().len()).collect(),
        ])
    }
}
