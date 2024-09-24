# Generated by Django 5.0.2 on 2024-02-21 20:04

import uuid

import django.utils.timezone
from django.db import migrations, models

import sentry.db.models.fields.bounded
import sentry.db.models.fields.hybrid_cloud_foreign_key
from sentry.new_migrations.migrations import CheckedMigration


class Migration(CheckedMigration):
    is_post_deployment = False

    dependencies = [
        ("sentry", "0649_add_index_for_group_priority"),
    ]

    operations = [
        migrations.CreateModel(
            name="SentryShot",
            fields=[
                (
                    "id",
                    sentry.db.models.fields.bounded.BoundedBigAutoField(
                        primary_key=True, serialize=False
                    ),
                ),
                ("uuid", models.UUIDField(db_index=True, default=uuid.uuid4, editable=False)),
                ("sentry_url", models.URLField()),
                ("component_identifier", models.CharField()),
                (
                    "organization_id",
                    sentry.db.models.fields.hybrid_cloud_foreign_key.HybridCloudForeignKey(
                        "sentry.Organization", db_index=True, on_delete="CASCADE"
                    ),
                ),
                (
                    "date_added",
                    models.DateTimeField(db_index=True, default=django.utils.timezone.now),
                ),
            ],
            options={
                "db_table": "sentry_sentryshot",
            },
        ),
    ]