import logging
from datetime import timedelta

from snuba_sdk import Column, Condition

import sentry.models
from sentry.search.events.builder.profile_functions_metrics import (
    ProfileFunctionsMetricsQueryBuilder,
    TimeseriesProfileFunctionsMetricsQueryBuilder,
    TopProfileFunctionsMetricsQueryBuilder,
)
from sentry.search.events.types import EventsResponse, QueryBuilderConfig, SnubaParams
from sentry.snuba import discover
from sentry.snuba.dataset import Dataset
from sentry.snuba.metrics.extraction import MetricSpecType
from sentry.snuba.query_sources import QuerySource
from sentry.utils.snuba import SnubaTSResult

logger = logging.getLogger(__name__)


def query(
    selected_columns: list[str],
    query: str,
    referrer: str,
    snuba_params: SnubaParams | None = None,
    equations: list[str] | None = None,
    orderby: list[str] | None = None,
    offset: int | None = None,
    limit: int = 50,
    auto_fields: bool = False,
    auto_aggregations: bool = False,
    include_equation_fields: bool = False,
    allow_metric_aggregates: bool = False,
    use_aggregate_conditions: bool = False,
    conditions: list[Condition] | None = None,
    functions_acl: list[str] | None = None,
    transform_alias_to_input_format: bool = False,
    sample: float | None = None,
    has_metrics: bool = False,
    use_metrics_layer: bool = False,
    skip_tag_resolution: bool = False,
    extra_columns: list[Column] | None = None,
    on_demand_metrics_enabled: bool = False,
    on_demand_metrics_type: MetricSpecType | None = None,
    fallback_to_transactions: bool = False,
    query_source: QuerySource | None = None,
):
    builder = ProfileFunctionsMetricsQueryBuilder(
        dataset=Dataset.PerformanceMetrics,
        params={},
        snuba_params=snuba_params,
        query=query,
        selected_columns=selected_columns,
        equations=equations,
        orderby=orderby,
        limit=limit,
        offset=offset,
        sample_rate=sample,
        config=QueryBuilderConfig(
            auto_fields=auto_fields,
            auto_aggregations=auto_aggregations,
            use_aggregate_conditions=use_aggregate_conditions,
            functions_acl=functions_acl,
            equation_config={"auto_add": include_equation_fields},
            has_metrics=has_metrics,
            use_metrics_layer=use_metrics_layer,
            transform_alias_to_input_format=transform_alias_to_input_format,
            skip_tag_resolution=skip_tag_resolution,
        ),
    )

    result = builder.process_results(builder.run_query(referrer, query_source=query_source))
    return result


def timeseries_query(
    selected_columns: list[str],
    query: str,
    snuba_params: SnubaParams,
    rollup: int,
    referrer: str,
    zerofill_results: bool = True,
    allow_metric_aggregates=True,
    comparison_delta: timedelta | None = None,
    functions_acl: list[str] | None = None,
    has_metrics: bool = True,
    use_metrics_layer: bool = False,
    on_demand_metrics_enabled: bool = False,
    on_demand_metrics_type: MetricSpecType | None = None,
    groupby: Column | None = None,
    query_source: QuerySource | None = None,
) -> SnubaTSResult:
    """
    High-level API for doing arbitrary user timeseries queries against events.
    this API should match that of sentry.snuba.discover.timeseries_query
    """

    metrics_query = TimeseriesProfileFunctionsMetricsQueryBuilder(
        {},
        rollup,
        snuba_params=snuba_params,
        dataset=Dataset.PerformanceMetrics,
        query=query,
        selected_columns=selected_columns,
        groupby=groupby,
        config=QueryBuilderConfig(
            functions_acl=functions_acl,
            allow_metric_aggregates=allow_metric_aggregates,
            use_metrics_layer=use_metrics_layer,
        ),
    )
    result = metrics_query.run_query(referrer, query_source=query_source)

    result = metrics_query.process_results(result)
    result["data"] = (
        discover.zerofill(
            result["data"],
            snuba_params.start_date,
            snuba_params.end_date,
            rollup,
            ["time"],
        )
        if zerofill_results
        else result["data"]
    )

    result["meta"]["isMetricsData"] = True

    return SnubaTSResult(
        {
            "data": result["data"],
            "isMetricsData": True,
            "meta": result["meta"],
        },
        snuba_params.start_date,
        snuba_params.end_date,
        rollup,
    )


def top_events_timeseries(
    timeseries_columns: list[str],
    selected_columns: list[str],
    user_query: str,
    snuba_params: SnubaParams,
    orderby: list[str],
    rollup: int,
    limit: int,
    referrer: str,
    organization: sentry.models.Organization,
    equations: list[str] | None = None,
    top_events: EventsResponse | None = None,
    allow_empty: bool = True,
    zerofill_results: bool = True,
    include_other: bool = False,
    functions_acl: list[str] | None = None,
    on_demand_metrics_enabled: bool = False,
    on_demand_metrics_type: MetricSpecType | None = None,
):
    """
    High-level API for doing arbitrary user timeseries queries for a limited number of top events

    Returns a dictionary of SnubaTSResult objects that have been zerofilled in
    case of gaps. Each value of the dictionary should match the result of a timeseries query

    timeseries_columns (Sequence[str]) List of public aliases to fetch for the timeseries query,
                    usually matches the y-axis of the graph
    selected_columns (Sequence[str]) List of public aliases to fetch for the events query,
                    this is to determine what the top events are
    user_query (str) Filter query string to create conditions from. needs to be user_query
                    to not conflict with the function query
    params (Dict[str, str]) Filtering parameters with start, end, project_id, environment,
    orderby (Sequence[str]) The fields to order results by.
    rollup (int) The bucket width in seconds
    limit (int) The number of events to get timeseries for
    organization (Organization) Used to map group ids to short ids
    referrer (str|None) A referrer string to help locate the origin of this query.
    top_events (dict|None) A dictionary with a 'data' key containing a list of dictionaries that
                    represent the top events matching the query. Useful when you have found
                    the top events earlier and want to save a query.
    """

    if top_events is None:
        top_events = query(
            selected_columns,
            query=user_query,
            snuba_params=snuba_params,
            equations=equations,
            orderby=orderby,
            limit=limit,
            referrer=referrer,
            auto_aggregations=True,
            use_aggregate_conditions=True,
            include_equation_fields=True,
            skip_tag_resolution=True,
        )

    top_events_builder = TopProfileFunctionsMetricsQueryBuilder(
        Dataset.PerformanceMetrics,
        {},
        rollup,
        top_events["data"],
        snuba_params=snuba_params,
        other=False,
        query=user_query,
        selected_columns=selected_columns,
        timeseries_columns=timeseries_columns,
        config=QueryBuilderConfig(
            functions_acl=functions_acl,
            skip_tag_resolution=True,
        ),
    )
    if len(top_events["data"]) == limit and include_other:
        other_events_builder = TopProfileFunctionsMetricsQueryBuilder(
            Dataset.PerformanceMetrics,
            {},
            rollup,
            top_events["data"],
            snuba_params=snuba_params,
            other=True,
            query=user_query,
            selected_columns=selected_columns,
            timeseries_columns=timeseries_columns,
        )

        # TODO: use bulk_snuba_queries
        other_result = other_events_builder.run_query(referrer)
        result = top_events_builder.run_query(referrer)
    else:
        result = top_events_builder.run_query(referrer)
        other_result = {"data": []}
    if (
        not allow_empty
        and not len(result.get("data", []))
        and not len(other_result.get("data", []))
    ):
        return SnubaTSResult(
            {
                "data": (
                    discover.zerofill(
                        [], snuba_params.start_date, snuba_params.end_date, rollup, ["time"]
                    )
                    if zerofill_results
                    else []
                ),
            },
            snuba_params.start_date,
            snuba_params.end_date,
            rollup,
        )

    result = top_events_builder.process_results(result)

    translated_groupby = top_events_builder.translated_groupby

    results = (
        {discover.OTHER_KEY: {"order": limit, "data": other_result["data"]}}
        if len(other_result.get("data", []))
        else {}
    )
    # Using the top events add the order to the results
    for index, item in enumerate(top_events["data"]):
        result_key = discover.create_result_key(item, translated_groupby, {})
        results[result_key] = {"order": index, "data": []}
    for row in result["data"]:
        result_key = discover.create_result_key(row, translated_groupby, {})
        if result_key in results:
            results[result_key]["data"].append(row)
        else:
            logger.warning(
                "profile_functions_metrics.top-events.timeseries.key-mismatch",
                extra={"result_key": result_key, "top_event_keys": list(results.keys())},
            )
    snuba_ts_result: dict[str, SnubaTSResult] = {}
    for key, item in results.items():
        snuba_ts_result[key] = SnubaTSResult(
            {
                "data": (
                    discover.zerofill(
                        item["data"],
                        snuba_params.start_date,
                        snuba_params.end_date,
                        rollup,
                        ["time"],
                    )
                    if zerofill_results
                    else item["data"]
                ),
                "order": item["order"],
            },
            snuba_params.start_date,
            snuba_params.end_date,
            rollup,
        )

    return snuba_ts_result