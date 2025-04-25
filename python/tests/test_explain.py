def test_register_explain_select(ctx, data_dir):
    parquet_path = data_dir / "data.rownum.parquet"
    ctx.register_parquet("data", str(parquet_path))
    actual = (
        ctx.sql("explain select * from data")
        .to_pandas()
        .set_index("plan_type")["plan"]
        .to_dict()
    )
    assert actual.keys() == {"logical_plan", "physical_plan"}
