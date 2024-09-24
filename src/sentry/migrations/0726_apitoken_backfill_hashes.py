# Generated by Django 5.0.6 on 2024-05-29 21:28

import hashlib
import logging
from enum import IntEnum

from django.db import migrations, router
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps

from sentry.new_migrations.migrations import CheckedMigration
from sentry.utils.query import RangeQuerySetWrapperWithProgressBar

logger = logging.getLogger(__name__)


def backfill_hash_values(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    ApiToken = apps.get_model("sentry", "ApiToken")
    ControlOutbox = apps.get_model("sentry", "ControlOutbox")
    OrganizationMemberMapping = apps.get_model("sentry", "OrganizationMemberMapping")
    OrganizationMapping = apps.get_model("sentry", "OrganizationMapping")

    try:
        from collections.abc import Container

        from django.conf import settings

        from sentry.silo.base import SiloMode, control_silo_function
        from sentry.silo.safety import unguarded_write
    except ImportError:
        logger.exception("Cannot execute migration. Required symbols could not be imported")
        return

    # copied from src/sentry/hybridcloud/outbox/category.py
    class OutboxCategory(IntEnum):
        USER_UPDATE = 0
        UNUSED_TWO = 4
        UNUSUED_THREE = 13
        UNUSED_ONE = 19
        AUTH_IDENTITY_UPDATE = 25
        API_TOKEN_UPDATE = 32

    # copied from src/sentry/hybridcloud/outbox/category.py
    _outbox_categories_for_scope: dict[int, set[OutboxCategory]] = {}
    _used_categories: set[OutboxCategory] = set()

    # copied from src/sentry/hybridcloud/outbox/category.py
    def scope_categories(enum_value: int, categories: set[OutboxCategory]) -> int:
        _outbox_categories_for_scope[enum_value] = categories
        inter = _used_categories.intersection(categories)
        assert not inter, f"OutboxCategories {inter} were already registered to a different scope"
        _used_categories.update(categories)
        return enum_value

    # copied from src/sentry/hybridcloud/outbox/category.py
    class OutboxScope(IntEnum):
        USER_SCOPE = scope_categories(
            1,
            {
                OutboxCategory.USER_UPDATE,
                OutboxCategory.API_TOKEN_UPDATE,
                OutboxCategory.UNUSED_ONE,
                OutboxCategory.UNUSED_TWO,
                OutboxCategory.UNUSUED_THREE,
                OutboxCategory.AUTH_IDENTITY_UPDATE,
            },
        )

    @control_silo_function
    def _find_orgs_for_user(user_id: int) -> set[int]:
        return {
            m["organization_id"]
            for m in OrganizationMemberMapping.objects.filter(user_id=user_id).values(
                "organization_id"
            )
        }

    @control_silo_function
    def find_regions_for_orgs(org_ids: Container[int]) -> set[str]:
        if SiloMode.get_current_mode() == SiloMode.MONOLITH:
            return {settings.SENTRY_MONOLITH_REGION}
        else:
            return set(
                OrganizationMapping.objects.filter(organization_id__in=org_ids).values_list(
                    "region_name", flat=True
                )
            )

    @control_silo_function
    def find_regions_for_user(user_id: int) -> set[str]:
        if SiloMode.get_current_mode() == SiloMode.MONOLITH:
            return {settings.SENTRY_MONOLITH_REGION}

        org_ids = _find_orgs_for_user(user_id)
        return find_regions_for_orgs(org_ids)

    for api_token in RangeQuerySetWrapperWithProgressBar(ApiToken.objects.all()):
        hashed_token = None
        if api_token.hashed_token is None:
            hashed_token = hashlib.sha256(api_token.token.encode()).hexdigest()
            api_token.hashed_token = hashed_token

        # if there's a refresh token make sure it is hashed as well
        hashed_refresh_token = None
        if api_token.refresh_token:
            hashed_refresh_token = hashlib.sha256(api_token.refresh_token.encode()).hexdigest()
            api_token.hashed_refresh_token = hashed_refresh_token

        # only save if we've actually had to hash values
        if hashed_token or hashed_refresh_token:
            with unguarded_write(using=router.db_for_write(ApiToken)):
                api_token.save(update_fields=["hashed_token", "hashed_refresh_token"])
                user_regions = find_regions_for_user(api_token.user_id)
                for region in user_regions:
                    ControlOutbox.objects.create(
                        shard_scope=OutboxScope.USER_SCOPE,
                        shard_identifier=api_token.user_id,
                        category=OutboxCategory.API_TOKEN_UPDATE,
                        region_name=region,
                        object_identifier=api_token.id,
                    )


class Migration(CheckedMigration):
    # This flag is used to mark that a migration shouldn't be automatically run in production.
    # This should only be used for operations where it's safe to run the migration after your
    # code has deployed. So this should not be used for most operations that alter the schema
    # of a table.
    # Here are some things that make sense to mark as post deployment:
    # - Large data migrations. Typically we want these to be run manually so that they can be
    #   monitored and not block the deploy for a long period of time while they run.
    # - Adding indexes to large tables. Since this can take a long time, we'd generally prefer to
    #   run this outside deployments so that we don't block them. Note that while adding an index
    #   is a schema change, it's completely safe to run the operation after the code has deployed.
    # Once deployed, run these manually via: https://develop.sentry.dev/database-migrations/#migration-deployment

    is_post_deployment = True

    dependencies = [
        ("sentry", "0725_create_sentry_groupsearchview_table"),
    ]

    operations = [
        migrations.RunPython(
            backfill_hash_values,
            migrations.RunPython.noop,
            hints={
                "tables": [
                    "sentry_apitoken",
                ]
            },
        )
    ]