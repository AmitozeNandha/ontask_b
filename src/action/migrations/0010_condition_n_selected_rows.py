# -*- coding: utf-8 -*-
# Generated by Django 1.11.12 on 2018-05-15 11:58
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('action', '0009_auto_20180428_1425'),
    ]

    operations = [
        migrations.AddField(
            model_name='condition',
            name='n_selected_rows',
            field=models.IntegerField(default=-1, verbose_name='Number of rows selected'),
        ),
    ]
