import math
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

import sentry_sdk
from django.http import Http404
from rest_framework.exceptions import ParseError
from rest_framework.request import Request
from rest_framework.response import Response
from snuba_sdk import Column, Condition, Function, Op

from sentry import features, tagstore
from sentry.api.api_publish_status import ApiPublishStatus
from sentry.api.base import region_silo_endpoint
from sentry.api.bases import NoProjects, OrganizationEventsV2EndpointBase
from sentry.api.paginator import GenericOffsetPaginator
from sentry.api.utils import handle_query_errors
from sentry.search.events.builder.discover import DiscoverQueryBuilder
from sentry.search.events.fields import DateArg
from sentry.search.events.types import SnubaParams
from sentry.snuba import discover
from sentry.snuba.dataset import Dataset
from sentry.utils.cursors import Cursor, CursorResult

ALLOWED_AGGREGATE_COLUMNS = {
    "transaction.duration",
    "measurements.lcp",
    "measurements.cls",
    "measurements.fcp",
    "measurements.fid",
    "measurements.inp",
    "spans.browser",
    "spans.http",
    "spans.db",
    "spans.resource",
}

TAG_ALIASES = {"release": "sentry:release", "dist": "sentry:dist", "user": "sentry:user"}
DEFAULT_TAG_KEY_LIMIT = 5


class OrganizationEventsFacetsPerformanceEndpointBase(OrganizationEventsV2EndpointBase):
    publish_status = {
        "GET": ApiPublishStatus.PRIVATE,
    }

    def has_feature(self, organization, request):
        return features.has("organizations:performance-view", organization, actor=request.user)

    # NOTE: This used to be called setup, but since Django 2.2 it's a View method.
    #       We don't fit its semantics, but I couldn't think of a better name, and
    #       it's only used in child classes.
    def _setup(self, request: Request, organization):
        if not self.has_feature(organization, request):
            raise Http404

        snuba_params = self.get_snuba_params(request, organization)

        filter_query = request.GET.get("query")
        aggregate_column = request.GET.get("aggregateColumn")

        if not aggregate_column:
            raise ParseError(detail="'aggregateColumn' must be provided.")

        if aggregate_column not in ALLOWED_AGGREGATE_COLUMNS:
            raise ParseError(detail=f"'{aggregate_column}' is not a supported tags column.")

        if len(snuba_params.project_ids) > 1:
            raise ParseError(detail="You cannot view facet performance for multiple projects.")

        return snuba_params, aggregate_column, filter_query


@region_silo_endpoint
class OrganizationEventsFacetsPerformanceEndpoint(OrganizationEventsFacetsPerformanceEndpointBase):
    def get(self, request: Request, organization) -> Response:
        try:
            snuba_params, aggregate_column, filter_query = self._setup(request, organization)
        except NoProjects:
            return Response([])

        all_tag_keys = None
        tag_key = None

        all_tag_keys = request.GET.get("allTagKeys")
        tag_key = request.GET.get("tagKey")

        if tag_key in TAG_ALIASES:
            tag_key = TAG_ALIASES.get(tag_key)

        def data_fn(offset, limit):
            with sentry_sdk.start_span(op="discover.endpoint", description="discover_query"):
                referrer = "api.organization-events-facets-performance.top-tags"
                tag_data = query_tag_data(
                    filter_query=filter_query,
                    aggregate_column=aggregate_column,
                    referrer=referrer,
                    snuba_params=snuba_params,
                )

                if not tag_data:
                    return {"data": []}

                results = query_facet_performance(
                    tag_data=tag_data,
                    filter_query=filter_query,
                    aggregate_column=aggregate_column,
                    referrer=referrer,
                    orderby=self.get_orderby(request),
                    limit=limit,
                    offset=offset,
                    snuba_params=snuba_params,
                    all_tag_keys=all_tag_keys,
                    tag_key=tag_key,
                )

                if not results:
                    return {"data": []}

                for row in results["data"]:
                    row["tags_value"] = tagstore.backend.get_tag_value_label(
                        row["tags_key"], row["tags_value"]
                    )
                    row["tags_key"] = tagstore.backend.get_standardized_key(row["tags_key"])

                return results

        with handle_query_errors():
            return self.paginate(
                request=request,
                paginator=GenericOffsetPaginator(data_fn=data_fn),
                on_results=lambda results: self.handle_results_with_meta(
                    request, organization, snuba_params.project_ids, results
                ),
                default_per_page=5,
                max_per_page=20,
            )


@region_silo_endpoint
class OrganizationEventsFacetsPerformanceHistogramEndpoint(
    OrganizationEventsFacetsPerformanceEndpointBase
):
    publish_status = {
        "GET": ApiPublishStatus.PRIVATE,
    }

    def get(self, request: Request, organization) -> Response:
        try:
            snuba_params, aggregate_column, filter_query = self._setup(request, organization)
        except NoProjects:
            return Response([])

        tag_key = request.GET.get("tagKey")
        num_buckets_per_key = request.GET.get("numBucketsPerKey")
        per_page = request.GET.get("per_page", DEFAULT_TAG_KEY_LIMIT)

        if not num_buckets_per_key:
            raise ParseError(
                detail="'numBucketsPerKey' must be provided for the performance histogram."
            )
        try:
            per_page = int(per_page)
            num_buckets_per_key = int(num_buckets_per_key)
        except ValueError:
            raise ParseError(detail="Bucket and tag key per_pages must be numeric.")

        if per_page * num_buckets_per_key > 500:
            raise ParseError(
                detail="The number of total buckets ('per_page' * 'numBucketsPerKey') cannot exceed 500"
            )

        if not tag_key:
            raise ParseError(detail="'tagKey' must be provided when using histograms.")

        if tag_key in TAG_ALIASES:
            tag_key = TAG_ALIASES.get(tag_key)

        def data_fn(offset, limit, raw_limit):
            with sentry_sdk.start_span(op="discover.endpoint", description="discover_query"):
                referrer = "api.organization-events-facets-performance-histogram"
                top_tags = query_top_tags(
                    tag_key=tag_key,
                    limit=limit,
                    filter_query=filter_query,
                    aggregate_column=aggregate_column,
                    snuba_params=snuba_params,
                    orderby=self.get_orderby(request),
                    offset=offset,
                    referrer=referrer,
                )

                if not top_tags:
                    return {"tags": [], "histogram": {"data": []}}

                # Only pass exactly the number of tags so histogram fetches correct number of rows
                histogram_top_tags = top_tags[0:raw_limit]

                histogram = query_facet_performance_key_histogram(
                    top_tags=histogram_top_tags,
                    tag_key=tag_key,
                    filter_query=filter_query,
                    aggregate_column=aggregate_column,
                    referrer=referrer,
                    snuba_params=snuba_params,
                    limit=raw_limit,
                    num_buckets_per_key=num_buckets_per_key,
                )

                if not histogram:
                    return {"tags": top_tags, "histogram": {"data": []}}

                for row in histogram["data"]:
                    row["tags_key"] = tagstore.backend.get_standardized_key(row["tags_key"])

                return {"tags": top_tags, "histogram": histogram}

        def on_results(data):
            return {
                "tags": self.handle_results_with_meta(
                    request, organization, snuba_params.project_ids, {"data": data["tags"]}
                ),
                "histogram": self.handle_results_with_meta(
                    request, organization, snuba_params.project_ids, data["histogram"]
                ),
            }

        with handle_query_errors():
            return self.paginate(
                request=request,
                paginator=HistogramPaginator(data_fn=data_fn),
                on_results=on_results,
                default_per_page=DEFAULT_TAG_KEY_LIMIT,
                max_per_page=50,
            )


class HistogramPaginator(GenericOffsetPaginator):
    def get_result(self, limit, cursor=None):
        assert limit > 0
        offset = cursor.offset if cursor is not None else 0
        # Request 1 more than limit so we can tell if there is another page
        # Use raw_limit for the histogram itself so bucket calculations are correct
        data = self.data_fn(offset=offset, limit=limit + 1, raw_limit=limit)

        if isinstance(data["tags"], list):
            has_more = len(data["tags"]) == limit + 1
            if has_more:
                data["tags"].pop()
        else:
            raise NotImplementedError

        return CursorResult(
            data,
            prev=Cursor(0, max(0, offset - limit), True, offset > 0),
            next=Cursor(0, max(0, offset + limit), False, has_more),
        )


def query_tag_data(
    snuba_params: SnubaParams,
    referrer: str,
    filter_query: str | None = None,
    aggregate_column: str | None = None,
) -> dict | None:
    """
    Fetch general data about all the transactions with this transaction name to feed into the facet query
    :return: Returns the row with aggregate and count if the query was successful
             Returns None if query was not successful which causes the endpoint to return early
    """
    with sentry_sdk.start_span(
        op="discover.discover", description="facets.filter_transform"
    ) as span:
        span.set_data("query", filter_query)
        tag_query = DiscoverQueryBuilder(
            dataset=Dataset.Discover,
            params={},
            snuba_params=snuba_params,
            query=filter_query,
            selected_columns=[
                "count()",
                f"avg({aggregate_column}) as aggregate",
                f"max({aggregate_column}) as max",
                f"min({aggregate_column}) as min",
            ],
        )
        tag_query.where.append(
            Condition(tag_query.resolve_column(aggregate_column), Op.IS_NOT_NULL)
        )

    with sentry_sdk.start_span(op="discover.discover", description="facets.frequent_tags"):
        # Get the average and count to use to filter the next request to facets
        tag_data = tag_query.run_query(f"{referrer}.all_transactions")

        if len(tag_data["data"]) != 1:
            return None

        counts = [r["count"] for r in tag_data["data"]]
        aggregates = [r["aggregate"] for r in tag_data["data"]]

        # Return early to avoid doing more queries with 0 count transactions or aggregates for columns that don't exist
        if counts[0] == 0 or aggregates[0] is None:
            return None
    if not tag_data["data"][0]:
        return None
    return tag_data["data"][0]


def query_top_tags(
    snuba_params: SnubaParams,
    tag_key: str,
    limit: int,
    referrer: str,
    orderby: list[str] | None,
    offset: int | None = None,
    aggregate_column: str | None = None,
    filter_query: str | None = None,
) -> list[Any] | None:
    """
    Fetch counts by tag value, finding the top tag values for a tag key by a limit.
    :return: Returns the row with the value, the aggregate and the count if the query was successful
             Returns None if query was not successful which causes the endpoint to return early
    """
    translated_aggregate_column = discover.resolve_discover_column(aggregate_column)

    with sentry_sdk.start_span(op="discover.discover", description="facets.top_tags"):
        if not orderby:
            orderby = ["-count"]

        for i, sort in enumerate(orderby):
            if "frequency" in sort:
                # Replacing frequency as it's the same underlying data dimension, this way we don't have to modify the existing histogram query.
                orderby[i] = sort.replace("frequency", "count")

        if "tags_value" not in orderby:
            orderby = orderby + ["tags_value"]

        # Get the average and count to use to filter the next request to facets
        tag_data = discover.query(
            selected_columns=[
                "count()",
                f"avg({aggregate_column}) as aggregate",
                "array_join(tags.value) as tags_value",
            ],
            query=filter_query,
            snuba_params=snuba_params,
            orderby=orderby,
            conditions=[
                Condition(Column(translated_aggregate_column), Op.IS_NOT_NULL),
                Condition(Column("tags_key"), Op.EQ, tag_key),
            ],
            functions_acl=["array_join"],
            referrer=f"{referrer}.top_tags",
            limit=limit,
            offset=offset,
        )

        if len(tag_data["data"]) <= 0:
            return None

        counts = [r["count"] for r in tag_data["data"]]

        # Return early to avoid doing more queries with 0 count transactions or aggregates for columns that don't exist
        if counts[0] == 0:
            return None
    if not tag_data["data"]:
        return None
    return tag_data["data"]


def query_facet_performance(
    snuba_params: SnubaParams,
    tag_data: Mapping[str, Any],
    referrer: str,
    aggregate_column: str | None = None,
    filter_query: str | None = None,
    orderby: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
    all_tag_keys: bool | None = None,
    tag_key: bool | None = None,
    include_count_delta: bool | None = None,
) -> dict:
    # Dynamically sample so at least 50000 transactions are selected
    sample_start_count = 50000
    transaction_count = tag_data["count"]
    sampling_enabled = transaction_count > sample_start_count

    # log-e growth starting at 50,000
    target_sample = max(
        sample_start_count * (math.log(transaction_count) - (math.log(sample_start_count) - 1)),
        transaction_count,
    )

    dynamic_sample_rate = 0 if transaction_count <= 0 else (target_sample / transaction_count)
    sample_rate = min(max(dynamic_sample_rate, 0), 1) if sampling_enabled else None
    frequency_sample_rate = sample_rate if sample_rate else 1

    tag_key_limit = limit if tag_key else 1

    with sentry_sdk.start_span(
        op="discover.discover", description="facets.filter_transform"
    ) as span:
        span.set_data("query", filter_query)
        tag_query = DiscoverQueryBuilder(
            dataset=Dataset.Discover,
            params={},
            snuba_params=snuba_params,
            query=filter_query,
            selected_columns=["count()", "tags_key", "tags_value"],
            sample_rate=sample_rate,
            turbo=sample_rate is not None,
            limit=limit,
            offset=offset,
            limitby=["tags_key", tag_key_limit] if not tag_key else None,
        )
    translated_aggregate_column = tag_query.resolve_column(aggregate_column)

    if include_count_delta:
        middle = snuba_params.start_date + timedelta(
            seconds=(snuba_params.end_date - snuba_params.start_date).total_seconds() * 0.5
        )
        middle = datetime.strftime(middle, DateArg.date_format)

        count_range_1 = tag_query.resolve_function(
            f"count_range(lessOrEquals, {middle})", overwrite_alias="count_range_1"
        )
        count_range_total = tag_query.resolve_function(
            "count()",
            overwrite_alias="count_range_total",
        )

        count_delta = tag_query.resolve_division(
            Function(
                "minus", [Function("minus", [count_range_total, count_range_1]), count_range_1]
            ),
            count_range_1,
            "count_delta",
        )

        tag_query.columns.extend([count_range_1, count_range_total, count_delta])
        tag_query.aggregates.extend([count_range_1, count_range_total, count_delta])

    # Aggregate (avg) and count of all transactions for this query
    transaction_aggregate = tag_data["aggregate"]

    # Exclude tags that have high cardinality are are generally unrelated to performance
    excluded_tags = Condition(
        Column("tags_key"),
        Op.NOT_IN,
        ["trace", "trace.ctx", "trace.span", "project", "browser", "celery_task_id", "url"],
    )

    with sentry_sdk.start_span(op="discover.discover", description="facets.aggregate_tags"):
        span.set_data("sample_rate", sample_rate)
        span.set_data("target_sample", target_sample)
        aggregate_comparison = transaction_aggregate * 1.005 if transaction_aggregate else 0
        aggregate_column = Function("avg", [translated_aggregate_column], "aggregate")
        tag_query.where.append(excluded_tags)
        if not all_tag_keys and not tag_key:
            tag_query.having.append(Condition(aggregate_column, Op.GT, aggregate_comparison))

        tag_query.where.append(Condition(translated_aggregate_column, Op.IS_NOT_NULL))

        if tag_key:
            tag_query.where.append(Condition(Column("tags_key"), Op.IN, [tag_key]))

        tag_query.columns.extend(
            [
                Function(
                    "divide",
                    [
                        Function(
                            "sum",
                            [
                                Function(
                                    "minus", [translated_aggregate_column, transaction_aggregate]
                                )
                            ],
                        ),
                        frequency_sample_rate,
                    ],
                    "sumdelta",
                ),
                Function(
                    "divide",
                    [
                        Function("divide", [Function("count", [], "count"), frequency_sample_rate]),
                        transaction_count,
                    ],
                    "frequency",
                ),
                Function("divide", [aggregate_column, transaction_aggregate], "comparison"),
                aggregate_column,
            ]
        )

        # Need to wait for the custom functions to be added first since they can be orderby options
        tag_query.orderby = tag_query.resolve_orderby(
            ([] if orderby is None else orderby) + ["tags_key", "tags_value"]
        )

        results = tag_query.process_results(tag_query.run_query(f"{referrer}.tag_values"))

        return results


def query_facet_performance_key_histogram(
    snuba_params: SnubaParams,
    top_tags: list[Any],
    tag_key: str,
    num_buckets_per_key: int,
    limit: int,
    referrer: str,
    aggregate_column: str,
    filter_query: str | None = None,
) -> dict:
    precision = 0

    tag_values = [x["tags_value"] for x in top_tags]

    results = discover.histogram_query(
        fields=[aggregate_column],
        user_query=filter_query,
        snuba_params=snuba_params,
        num_buckets=num_buckets_per_key,
        precision=precision,
        group_by=["tags_value", "tags_key"],
        extra_conditions=[
            Condition(Column("tags_key"), Op.EQ, tag_key),
            Condition(Column("tags_value"), Op.IN, tag_values),
        ],
        histogram_rows=limit,
        referrer="api.organization-events-facets-performance-histogram",
        normalize_results=False,
    )
    return results