# Generated by Django 5.0.2 on 2024-03-04 10:36

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models

import sentry.db.models.fields.foreignkey
from sentry.new_migrations.migrations import CheckedMigration


class Migration(CheckedMigration):
    # This flag is used to mark that a migration shouldn't be automatically run in production. For
    # the most part, this should only be used for operations where it's safe to run the migration
    # after your code has deployed. So this should not be used for most operations that alter the
    # schema of a table.
    # Here are some things that make sense to mark as post deployment:
    # - Large data migrations. Typically we want these to be run manually by ops so that they can
    #   be monitored and not block the deploy for a long period of time while they run.
    # - Adding indexes to large tables. Since this can take a long time, we'd generally prefer to
    #   have ops run this and not block the deploy. Note that while adding an index is a schema
    #   change, it's completely safe to run the operation after the code has deployed.
    is_post_deployment = False

    dependencies = [
        ("sentry", "0658_projectkey_usecase"),
    ]

    operations = [
        migrations.AlterField(
            model_name="artifactbundleindex",
            name="date_last_modified",
            field=models.DateTimeField(default=django.utils.timezone.now, null=True),
        ),
        migrations.AlterField(
            model_name="artifactbundleindex",
            name="dist_name",
            field=models.CharField(default="", max_length=64, null=True),
        ),
        migrations.AlterField(
            model_name="artifactbundleindex",
            name="release_name",
            field=models.CharField(max_length=250, null=True),
        ),
        migrations.AlterField(
            model_name="flatfileindexstate",
            name="artifact_bundle",
            field=sentry.db.models.fields.foreignkey.FlexibleForeignKey(
                db_constraint=False,
                on_delete=django.db.models.deletion.CASCADE,
                to="sentry.artifactbundle",
            ),
        ),
        migrations.AlterField(
            model_name="flatfileindexstate",
            name="flat_file_index",
            field=sentry.db.models.fields.foreignkey.FlexibleForeignKey(
                db_constraint=False,
                on_delete=django.db.models.deletion.CASCADE,
                to="sentry.artifactbundleflatfileindex",
            ),
        ),
    ]
