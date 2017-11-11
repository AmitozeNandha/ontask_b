# -*- coding: utf-8 -*-
from __future__ import unicode_literals, print_function

import pandas as pd
from django.http import Http404
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import APIView

from dataops import pandas_db, ops
from matrix.serializers import DataFrameSerializer, DataFrameMergeSerializer
from ontask.permissions import UserIsInstructor
from workflow.models import Workflow
from workflow.ops import is_locked, detach_dataframe


class MatrixOps(APIView, UserIsInstructor):
    """
    get:
    Get all the data in the matrix corresponding to the workflow (no matter
    how big). If the workflow has no data, an empty {} is returned.

    post:
    Upload a new matrix to a workflow without. If there is a matrix already, the
    operation will be rejected (consider deleting the matrix first or use PUT)

    put:
    Replace the matrix currently in the workflow with the one given

    delete:
    Flush the data frame from the workflow. The workflow object remains, just
    the data frame is deleted.
    """

    serializer_class = DataFrameSerializer

    def get_object(self, pk, **kwargs):
        user = kwargs['user']
        try:
            if user.is_superuser:
                workflow = Workflow.objects.get(pk=pk)
            else:
                workflow = Workflow.objects.get(pk=pk, user=user)
        except Workflow.DoesNotExist:
            raise APIException('Incorrect object')

        if is_locked(workflow):
            raise APIException('Workflow is locked by another user')

        return workflow

    def override(self, request, pk, format=None):
        # Try to retrieve the wflow to check for permissions
        self.get_object(pk, user=self.request.user)

        serializer = DataFrameSerializer(data=request.data)
        if serializer.is_valid():
            try:
                df = pd.DataFrame(serializer.validated_data)

                # Detect date/time columns
                df = ops.detect_datetime_columns(df)
            except Exception:
                # Something went wrong with the translation to dataframe
                raise Http404

            ops.store_dataframe_in_db(df, pk)

            return Response(serializer.data,
                            status=status.HTTP_201_CREATED)
        return Response(serializer.errors,
                        status=status.HTTP_400_BAD_REQUEST)

    # Retrieve
    def get(self, request, pk, format=None):
        # Try to retrieve the wflow to check for permissions
        self.get_object(pk, user=self.request.user)
        serializer = DataFrameSerializer(pandas_db.load_from_db(pk))
        return Response(serializer.data)

    # Create
    def post(self, request, pk, format=None):
        # If there is a matrix in the workflow, ignore the request
        if pandas_db.load_from_db(pk) is not None:
            raise APIException('Post request requires workflow without '
                               'a matrix')
        return self.override(request, pk, format)

    # Update
    def put(self, request, pk, format=None):
        return self.override(request, pk, format)

    # Delete
    def delete(self, request, pk, format=None):
        wflow = self.get_object(pk, user=self.request.user)
        detach_dataframe(wflow)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MatrixMerge(APIView, UserIsInstructor):
    """
    get:
    Retrieves the data frame attached to the workflow and returns it labeled
    as "src_df"

    post:
    Request to merge a given data frame with the one attached to the workflow.
    """

    serializer_class = DataFrameMergeSerializer

    def get_object(self, pk, **kwargs):
        user = kwargs['user']
        try:
            if user.is_superuser:
                workflow = Workflow.objects.get(pk=pk)
            else:
                workflow = Workflow.objects.get(pk=pk, user=user)
        except Workflow.DoesNotExist:
            raise APIException('Incorrect object')

        if is_locked(workflow):
            raise APIException('Workflow is locked by another user')

        return workflow

    # Retrieve
    def get(self, request, pk, format=None):
        # Try to retrieve the wflow to check for permissions
        self.get_object(pk, user=self.request.user)
        serializer = DataFrameMergeSerializer(
            {'src_df': pandas_db.load_from_db(pk),
             'how': '',
             'left_on': '',
             'right_on': '',
             'dup_column': ''}
        )
        return Response(serializer.data)

    # Update
    def put(self, request, pk, format=None):
        # Try to retrieve the wflow to check for permissions
        self.get_object(pk, user=self.request.user)
        # Get the dst_df
        dst_df = pandas_db.load_from_db(pk)

        serializer = DataFrameMergeSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors,
                            status=status.HTTP_400_BAD_REQUEST)

        # Operation has been accepted by the serializer
        try:
            src_df = pd.DataFrame(serializer.validated_data['src_df'])
        except Exception:
            # Something went wrong with the translation to dataframe
            raise APIException('Unable to load workflow matrix')

        # Check that the parameters are correct
        how = serializer.validated_data['how']
        if how == '' or how not in ['left', 'right', 'outer', 'inner']:
            raise APIException('how must be one of left, right, outer '
                               'or inner')

        left_on = serializer.validated_data['left_on']
        if not ops.is_unique_column(dst_df[left_on]):
            raise APIException('column' + left_on +
                               'does not contain a unique key.')

        right_on = serializer.validated_data['right_on']
        if right_on not in list(src_df.columns):
            raise APIException('column ' + right_on +
                               ' not found in data frame')

        if not ops.is_unique_column(src_df[right_on]):
            raise APIException('column' + right_on +
                               'does not contain a unique key.')

        dup_column = serializer.validated_data['dup_column']
        if dup_column == '' or dup_column not in ['override', 'rename']:
            raise APIException('dup_column must be override or rename')

        override_columns_names = []
        autorename_column_names = None
        if dup_column == 'override':
            # List of columns to drop (the ones in both data sets
            override_columns_names = list(
                (set(dst_df.columns) & set(src_df.columns)) -
                {left_on}
            )
        else:
            autorename_column_names = []
            for colname in list(src_df.columns):
                # If the column is the key, insert as is
                if colname == right_on:
                    autorename_column_names.append(colname)
                    continue

                # If the column does not collide, insert as is
                if colname not in dst_df.columns:
                    autorename_column_names.append(colname)
                    continue

                # Column name collides with existing column
                i = 0  # Suffix to rename
                while True:
                    i += 1
                    new_name = colname + '_{0}'.format(i)
                    if new_name not in dst_df.columns:
                        break
                autorename_column_names.append(new_name)

        merge_info = {
            'how_merge': how,
            'dst_selected_key': left_on,
            'src_selected_key': right_on,
            'initial_column_names': list(src_df.columns),
            'autorename_column_names': autorename_column_names,
            'rename_column_names': list(src_df.columns),
            'columns_to_upload': [True] * len(list(src_df.columns)),
            'override_columns_names': override_columns_names
        }

        # Ready to perform the MERGE
        try:
            merge_result = ops.perform_dataframe_upload_merge(pk,
                                                              dst_df,
                                                              src_df,
                                                              merge_info)
        except Exception:
            raise APIException('Unable to perform merge operation')

        if merge_result:
            # Somthing went wrong, raise the exception
            raise APIException(merge_result)

        # Merge went through.
        return Response(serializer.data,
                        status=status.HTTP_201_CREATED)