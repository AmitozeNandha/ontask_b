# -*- coding: utf-8 -*-
from __future__ import unicode_literals, print_function

from django import forms
from django.template.defaultfilters import filesizeformat
from django.utils.translation import ugettext_lazy as _

import ontask.ontask_prefs


class RestrictedFileField(forms.FileField):

    def __init__(self, *args, **kwargs):
        self.content_types = kwargs.pop('content_types', None)
        self.max_upload_size = kwargs.pop('max_upload_size', None)
        if not self.max_upload_size:
            self.max_upload_size = str(ontask.ontask_prefs.MAX_UPLOAD_SIZE)
        super(RestrictedFileField, self).__init__(*args, **kwargs)

    def clean(self, *args, **kwargs):
        data = super(RestrictedFileField, self).clean(*args, **kwargs)
        try:
            if data.content_type in self.content_types:
                if data.size > self.max_upload_size:
                    raise forms.ValidationError(
                        _('File size must be under %s. Current file size is'
                          ' %s.')
                        % (filesizeformat(self.max_upload_size),
                           filesizeformat(data.size)))
            else:
                raise forms.ValidationError(
                    _('File type (%s) is not supported.') % data.content_type)
        except AttributeError:
            pass

        return data
