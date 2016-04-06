# This file is part of Indico.
# Copyright (C) 2002 - 2016 European Organization for Nuclear Research (CERN).
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

from collections import Counter
from datetime import timedelta

import dateutil.parser
from flask import request, jsonify
from werkzeug.exceptions import BadRequest, NotFound

from indico.modules.events.contributions import Contribution
from indico.modules.events.contributions.operations import create_contribution
from indico.modules.events.sessions.controllers.management.sessions import RHCreateSession
from indico.modules.events.sessions.models.sessions import Session
from indico.modules.events.timetable.controllers import RHManageTimetableBase
from indico.modules.events.timetable.forms import BreakEntryForm, ContributionEntryForm, SessionBlockEntryForm
from indico.modules.events.timetable.legacy import serialize_contribution, serialize_entry_update, serialize_session
from indico.modules.events.timetable.models.breaks import Break
from indico.modules.events.timetable.operations import (create_break_entry, create_session_block_entry,
                                                        schedule_contribution, fit_session_block_entry)
from indico.modules.events.timetable.reschedule import Rescheduler, RescheduleMode
from indico.modules.events.timetable.util import find_earliest_gap
from indico.modules.events.util import get_random_color, track_time_changes
from indico.web.forms.base import FormDefaults
from indico.web.util import jsonify_data, jsonify_form


class RHLegacyTimetableAddEntryBase(RHManageTimetableBase):
    def _checkParams(self, params):
        RHManageTimetableBase._checkParams(self, params)
        self.day = dateutil.parser.parse(request.args['day']).date()
        self.session_block = None
        if 'session_block_id' in request.args:
            self.session_block = self.event_new.get_session_block(request.args['session_block_id'])

    def _get_form_defaults(self, **kwargs):
        inherited_location = self.event_new.location_data
        inherited_location['inheriting'] = True
        return FormDefaults(location_data=inherited_location, **kwargs)

    def _get_form_params(self):
        return {'event': self.event_new,
                'session_block': self.session_block,
                'day': self.day}


class RHLegacyTimetableAddBreak(RHLegacyTimetableAddEntryBase):
    def _get_default_colors(self):
        breaks = Break.query.filter(Break.timetable_entry.has(event_new=self.event_new)).all()
        common_colors = Counter(b.colors for b in breaks)
        most_common = common_colors.most_common(1)
        colors = most_common[0][0] if most_common else get_random_color(self.event_new)
        return colors

    def _process(self):
        colors = self._get_default_colors()
        defaults = self._get_form_defaults(colors=colors)
        form = BreakEntryForm(obj=defaults, **self._get_form_params())
        if form.validate_on_submit():
            entry = create_break_entry(self.event_new, form.data, session_block=self.session_block)
            return jsonify_data(entry=serialize_entry_update(entry), flash=False)
        return jsonify_form(form, fields=form._display_fields)


class RHLegacyTimetableAddContribution(RHLegacyTimetableAddEntryBase):
    def _process(self):
        defaults = self._get_form_defaults()
        form = ContributionEntryForm(obj=defaults, to_schedule=True, **self._get_form_params())
        if form.validate_on_submit():
            contrib = create_contribution(self.event_new, form.data, session_block=self.session_block)
            return jsonify_data(entries=[serialize_entry_update(contrib.timetable_entry)], flash=False)
        self.commit = False
        return jsonify_form(form, fields=form._display_fields)


class RHLegacyTimetableAddSessionBlock(RHLegacyTimetableAddEntryBase):
    def _checkParams(self, params):
        RHLegacyTimetableAddEntryBase._checkParams(self, params)
        self.session = Session.find_one(id=request.args['session'], event_new=self.event_new, is_deleted=False)

    def _process(self):
        defaults = self._get_form_defaults()
        form = SessionBlockEntryForm(obj=defaults, **self._get_form_params())
        if form.validate_on_submit():
            entry = create_session_block_entry(self.session, form.data)
            return jsonify_data(entry=serialize_entry_update(entry), flash=False)
        self.commit = False
        return jsonify_form(form, fields=form._display_fields)


class RHLegacyTimetableAddSession(RHCreateSession):
    def _get_response(self, new_session):
        return jsonify_data(session=serialize_session(new_session))


class RHLegacyTimetableGetUnscheduledContributions(RHManageTimetableBase):
    def _checkParams(self, params):
        RHManageTimetableBase._checkParams(self, params)
        try:
            # no need to validate whether it's in the event; we just
            # use it to filter the event's contribution list
            self.session_id = int(request.args['session_id'])
        except KeyError:
            self.session_id = None

    def _process(self):
        contributions = Contribution.query.with_parent(self.event_new).filter_by(is_scheduled=False)
        contributions = [c for c in contributions if c.session_id == self.session_id]
        return jsonify(contributions=[serialize_contribution(x) for x in contributions])


class RHLegacyTimetableScheduleContribution(RHManageTimetableBase):
    def _checkParams(self, params):
        RHManageTimetableBase._checkParams(self, params)
        self.session_block = None
        if 'block_id' in request.view_args:
            self.session_block = self.event_new.get_session_block(request.view_args['block_id'])
            if self.session_block is None:
                raise NotFound

    def _process(self):
        data = request.json
        required_keys = {'contribution_ids', 'day'}
        allowed_keys = required_keys | {'session_block_id'}
        if data.viewkeys() > allowed_keys:
            raise BadRequest('Invalid keys found')
        elif required_keys > data.viewkeys():
            raise BadRequest('Required keys missing')
        entries = []
        day = dateutil.parser.parse(data['day']).date()
        query = Contribution.query.with_parent(self.event_new).filter(Contribution.id.in_(data['contribution_ids']))
        for contribution in query:
            start_dt = find_earliest_gap(self.event_new, day, contribution.duration, session_block=self.session_block)
            # TODO: handle scheduling not-fitting contributions
            if start_dt:
                entries.append(self._schedule(contribution, start_dt))
        return jsonify(entries=[serialize_entry_update(x) for x in entries])

    def _schedule(self, contrib, start_dt):
        return schedule_contribution(contrib, start_dt, session_block=self.session_block)


class RHLegacyTimetableReschedule(RHManageTimetableBase):
    _json_schema = {
        'type': 'object',
        'properties': {
            'mode': {'type': 'string', 'enum': ['none', 'time', 'duration']},
            'day': {'type': 'string', 'format': 'date'},
            'gap': {'type': 'integer', 'minimum': 0},
            'fit_blocks': {'type': 'boolean'},
            'session_block_id': {'type': 'integer'},
            'session_id': {'type': 'integer'}
        },
        'required': ['mode', 'day', 'gap', 'fit_blocks']
    }

    def _checkParams(self, params):
        RHManageTimetableBase._checkParams(self, params)
        self.validate_json(self._json_schema)
        self.day = dateutil.parser.parse(request.json['day']).date()
        self.session_block = self.session = None
        if request.json.get('session_block_id') is not None:
            self.session_block = self.event_new.get_session_block(request.json['session_block_id'], scheduled_only=True)
            if self.session_block is None:
                raise NotFound
        elif request.json.get('session_id') is not None:
            self.session = self.event_new.get_session(request.json['session_id'])
            if self.session is None:
                raise NotFound

    def _process(self):
        rescheduler = Rescheduler(self.event_new, RescheduleMode[request.json['mode']], self.day,
                                  session=self.session, session_block=self.session_block,
                                  fit_blocks=request.json['fit_blocks'], gap=timedelta(minutes=request.json['gap']))
        with track_time_changes():
            rescheduler.run()
        return jsonify_data(flash=False)


class RHLegacyTimetableFitBlock(RHManageTimetableBase):
    def _checkParams(self, params):
        RHManageTimetableBase._checkParams(self, params)
        self.session_block = self.event_new.get_session_block(request.view_args['block_id'], scheduled_only=True)
        if self.session_block is None:
            raise NotFound

    def _process(self):
        with track_time_changes():
            fit_session_block_entry(self.session_block.timetable_entry)
        return jsonify_data(flash=False)
