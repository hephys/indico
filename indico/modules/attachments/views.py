# This file is part of Indico.
# Copyright (C) 2002 - 2018 European Organization for Nuclear Research (CERN).
#
# Indico is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License as
# published by the Free Software Foundation; either version 3 of the
# License, or (at your option) any later version.
#
# Indico is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Indico; if not, see <http://www.gnu.org/licenses/>.

from __future__ import unicode_literals

from indico.modules.events.management.views import WPEventManagement
from indico.modules.events.views import WPConferenceDisplayBase, WPSimpleEventDisplayBase
from indico.web.views import WPJinjaMixin


class AttachmentsMixin(WPJinjaMixin):
    template_prefix = 'attachments/'
    base_wp = None

    def _getPageContent(self, params):
        return WPJinjaMixin._getPageContent(self, params)


class WPEventAttachments(AttachmentsMixin, WPEventManagement):
    base_wp = WPEventManagement
    sidemenu_option = 'attachments'
    ALLOW_JSON = True


class WPEventFolderDisplay(WPSimpleEventDisplayBase, WPJinjaMixin):
    template_prefix = 'attachments/'

    def _getBody(self, params):
        return WPJinjaMixin._getPageContent(self, params)


class WPPackageEventAttachmentsManagement(WPEventAttachments, WPJinjaMixin):
    template_prefix = 'attachments/'

    def _getTabContent(self, params):
        return WPJinjaMixin._getPageContent(self, params)


class WPPackageEventAttachmentsDisplayConference(WPConferenceDisplayBase):
    template_prefix = 'attachments/'


class WPPackageEventAttachmentsDisplay(WPSimpleEventDisplayBase, WPJinjaMixin):
    template_prefix = 'attachments/'

    def _getBody(self, params):
        return WPJinjaMixin._getPageContent(self, params)
