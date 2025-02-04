import os
from typing import Optional

import dlt
import duckdb
import pytest
from dagster import (
    AssetExecutionContext,
    AssetKey,
    AutoMaterializePolicy,
    AutoMaterializeRule,
    Definitions,
)
from dagster._core.definitions.auto_materialize_rule import MaterializeOnCronRule
from dagster._core.definitions.materialize import materialize
from dagster_open_platform.resources.dlt_resource import (
    DltDagsterResource,
    DltDagsterTranslator,
    dlt_assets,
)
from dlt.extract.resource import DltResource

from .dlt_pipelines.duckdb_with_transformer import pipeline

EXAMPLE_PIPELINE_DUCKDB = "example_pipeline.duckdb"

DLT_SOURCE = pipeline()
DLT_PIPELINE = dlt.pipeline(
    pipeline_name="example_pipeline",
    dataset_name="example",
    destination="duckdb",
)


@pytest.fixture
def _teardown():
    yield
    if os.path.exists(EXAMPLE_PIPELINE_DUCKDB):
        os.remove(EXAMPLE_PIPELINE_DUCKDB)


def test_example_pipeline_asset_keys():
    @dlt_assets(dlt_source=DLT_SOURCE, dlt_pipeline=DLT_PIPELINE)
    def example_pipeline_assets(
        context: AssetExecutionContext, dlt_pipeline_resource: DltDagsterResource
    ):
        yield from dlt_pipeline_resource.run(context=context)

    assert {
        AssetKey("dlt_pipeline_repos"),
        AssetKey("dlt_pipeline_repo_issues"),
    } == example_pipeline_assets.keys


def test_example_pipeline(_teardown):
    @dlt_assets(dlt_source=DLT_SOURCE, dlt_pipeline=DLT_PIPELINE)
    def example_pipeline_assets(
        context: AssetExecutionContext, dlt_pipeline_resource: DltDagsterResource
    ):
        yield from dlt_pipeline_resource.run(context=context)

    res = materialize(
        [example_pipeline_assets],
        resources={"dlt_pipeline_resource": DltDagsterResource()},
    )
    assert res.success

    with duckdb.connect(database=EXAMPLE_PIPELINE_DUCKDB, read_only=True) as conn:
        row = conn.execute("select count(*) from example.repos").fetchone()
        assert row and row[0] == 3

        row = conn.execute("select count(*) from example.repo_issues").fetchone()
        assert row and row[0] == 7


def test_multi_asset_names_do_not_conflict(_teardown):
    class CustomDagsterDltTranslator(DltDagsterTranslator):
        @classmethod
        def get_asset_key(cls, resource: DltResource) -> AssetKey:
            return AssetKey("custom_" + resource.name)

    @dlt_assets(dlt_source=DLT_SOURCE, dlt_pipeline=DLT_PIPELINE, name="multi_asset_name1")
    def assets1():
        pass

    @dlt_assets(
        dlt_source=DLT_SOURCE,
        dlt_pipeline=DLT_PIPELINE,
        name="multi_asset_name2",
        dlt_dagster_translator=CustomDagsterDltTranslator(),
    )
    def assets2():
        pass

    assert Definitions(assets=[assets1, assets2])


def test_get_materialize_policy(_teardown):
    class CustomDagsterDltTranslator(DltDagsterTranslator):
        @classmethod
        def get_auto_materialize_policy(
            cls, resource: DltResource
        ) -> Optional[AutoMaterializePolicy]:
            return AutoMaterializePolicy.eager().with_rules(
                AutoMaterializeRule.materialize_on_cron("0 1 * * *")
            )

    @dlt_assets(
        dlt_source=DLT_SOURCE,
        dlt_pipeline=DLT_PIPELINE,
        dlt_dagster_translator=CustomDagsterDltTranslator(),
    )
    def assets():
        pass

    for item in assets.auto_materialize_policies_by_key.values():
        assert any(
            isinstance(rule, MaterializeOnCronRule) and rule.cron_schedule == "0 1 * * *"
            for rule in item.rules
        )
