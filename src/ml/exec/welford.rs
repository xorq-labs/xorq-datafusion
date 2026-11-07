//! `__ml_welford`: single-pass count, mean and sum of squared deviations
//! (M2) of a `Float64` column, mergeable across partitions.
//!
//! Update uses Welford's recurrence; merge uses Chan et al.'s pairwise
//! formula, so partial and final aggregation agree with a single pass up to
//! rounding. Nulls are skipped (counted out); NaN propagates.

use std::sync::Arc;

use datafusion::arrow::array::{Array, ArrayRef, AsArray, StructArray};
use datafusion::arrow::datatypes::{DataType, Field, FieldRef, Fields, Float64Type, UInt64Type};
use datafusion::common::{internal_err, Result, ScalarValue};
use datafusion::logical_expr::function::{AccumulatorArgs, StateFieldsArgs};
use datafusion::logical_expr::utils::format_state_name;
use datafusion::logical_expr::{
    Accumulator, AggregateUDF, AggregateUDFImpl, Signature, Volatility,
};

pub(crate) const NAME: &str = "__ml_welford";
pub(crate) const COUNT: &str = "count";
pub(crate) const MEAN: &str = "mean";
pub(crate) const M2: &str = "m2";

fn result_fields() -> Fields {
    Fields::from(vec![
        Field::new(COUNT, DataType::UInt64, false),
        Field::new(MEAN, DataType::Float64, false),
        Field::new(M2, DataType::Float64, false),
    ])
}

/// The `__ml_welford` aggregate: `Float64 -> Struct{count, mean, m2}`.
pub(crate) fn welford_udaf() -> Arc<AggregateUDF> {
    Arc::new(AggregateUDF::from(Welford::new()))
}

#[derive(Debug, PartialEq, Eq, Hash)]
struct Welford {
    signature: Signature,
}

impl Welford {
    fn new() -> Self {
        Self {
            signature: Signature::exact(vec![DataType::Float64], Volatility::Immutable),
        }
    }
}

impl AggregateUDFImpl for Welford {
    fn name(&self) -> &str {
        NAME
    }

    fn signature(&self) -> &Signature {
        &self.signature
    }

    fn return_type(&self, _arg_types: &[DataType]) -> Result<DataType> {
        Ok(DataType::Struct(result_fields()))
    }

    fn accumulator(&self, _acc_args: AccumulatorArgs) -> Result<Box<dyn Accumulator>> {
        Ok(Box::<WelfordAccumulator>::default())
    }

    fn state_fields(&self, args: StateFieldsArgs) -> Result<Vec<FieldRef>> {
        Ok(vec![
            Arc::new(Field::new(
                format_state_name(args.name, COUNT),
                DataType::UInt64,
                false,
            )),
            Arc::new(Field::new(
                format_state_name(args.name, MEAN),
                DataType::Float64,
                false,
            )),
            Arc::new(Field::new(
                format_state_name(args.name, M2),
                DataType::Float64,
                false,
            )),
        ])
    }
}

#[derive(Debug, Default, Clone, Copy, PartialEq)]
pub(crate) struct WelfordState {
    pub(crate) count: u64,
    pub(crate) mean: f64,
    pub(crate) m2: f64,
}

impl WelfordState {
    pub(crate) fn push(&mut self, x: f64) {
        self.count += 1;
        let delta = x - self.mean;
        self.mean += delta / self.count as f64;
        self.m2 += delta * (x - self.mean);
    }

    pub(crate) fn merge(&mut self, other: WelfordState) {
        if other.count == 0 {
            return;
        }
        if self.count == 0 {
            *self = other;
            return;
        }
        let count = self.count + other.count;
        let (n_a, n_b, n) = (self.count as f64, other.count as f64, count as f64);
        let delta = other.mean - self.mean;
        // Ratio first, before squaring: `delta * delta` alone can overflow
        // f64 while the merged M2 is finite.
        self.mean += delta * (n_b / n);
        self.m2 += other.m2 + delta * (delta * (n_a / n)) * n_b;
        self.count = count;
    }
}

#[derive(Debug, Default)]
struct WelfordAccumulator {
    state: WelfordState,
}

impl Accumulator for WelfordAccumulator {
    fn update_batch(&mut self, values: &[ArrayRef]) -> Result<()> {
        let [values] = values else {
            return internal_err!("{NAME} takes one argument, got {}", values.len());
        };
        let values = values.as_primitive::<Float64Type>();
        if values.null_count() == 0 {
            values.values().iter().for_each(|x| self.state.push(*x));
        } else {
            values.iter().flatten().for_each(|x| self.state.push(x));
        }
        Ok(())
    }

    fn merge_batch(&mut self, states: &[ArrayRef]) -> Result<()> {
        let [counts, means, m2s] = states else {
            return internal_err!("{NAME} state has 3 columns, got {}", states.len());
        };
        let counts = counts.as_primitive::<UInt64Type>();
        let means = means.as_primitive::<Float64Type>();
        let m2s = m2s.as_primitive::<Float64Type>();
        for i in 0..counts.len() {
            self.state.merge(WelfordState {
                count: counts.value(i),
                mean: means.value(i),
                m2: m2s.value(i),
            });
        }
        Ok(())
    }

    fn state(&mut self) -> Result<Vec<ScalarValue>> {
        Ok(vec![
            ScalarValue::UInt64(Some(self.state.count)),
            ScalarValue::Float64(Some(self.state.mean)),
            ScalarValue::Float64(Some(self.state.m2)),
        ])
    }

    fn evaluate(&mut self) -> Result<ScalarValue> {
        let WelfordState { count, mean, m2 } = self.state;
        let columns: Vec<ArrayRef> = vec![
            ScalarValue::UInt64(Some(count)).to_array()?,
            ScalarValue::Float64(Some(mean)).to_array()?,
            ScalarValue::Float64(Some(m2)).to_array()?,
        ];
        let array = StructArray::try_new(result_fields(), columns, None)?;
        Ok(ScalarValue::Struct(Arc::new(array)))
    }

    fn size(&self) -> usize {
        std::mem::size_of_val(self)
    }
}
