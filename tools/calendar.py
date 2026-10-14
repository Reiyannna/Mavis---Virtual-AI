"""Google Calendar tools for Mavis."""
import datetime
from zoneinfo import ZoneInfo

from tools.google_auth import _as_json, _calendar
def calendar_status() -> str:
    """Checks whether Google Calendar is connected."""
    calendar = _calendar()
    if not calendar:
        return "Google Calendar is not connected. Run the OAuth flow first."
    try:
        calendar.calendarList().list(maxResults=1).execute()
        return "Google Calendar is connected."
    except Exception as e:
        return f"Calendar connection check failed: {e}"
def get_today_calendar_events() -> str:
    """Fetches scheduled events for today from your primary Google Calendar in local Cebu time."""
    calendar = _calendar()
    if not calendar:
        return "Failed to connect to Google Calendar."
    try:
        manila_tz = ZoneInfo("Asia/Manila")
        now_local = datetime.datetime.now(manila_tz)
        start_of_day = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = now_local.replace(hour=23, minute=59, second=59, microsecond=999999)
        events_result = calendar.events().list(
            calendarId='primary',
            timeMin=start_of_day.isoformat(),
            timeMax=end_of_day.isoformat(),
            singleEvents=True,
            orderBy='startTime').execute()
        events = events_result.get('items', [])
        if not events:
            return "No events scheduled for today."
        summary_list = []
        for event in events:
            start_str = event['start'].get('dateTime')
            if start_str:
                dt = datetime.datetime.fromisoformat(start_str.replace('Z', '+00:00'))
                local_dt = dt.astimezone(manila_tz)
                formatted_time = local_dt.strftime("%I:%M %p")
            else:
                formatted_time = "All-day"
            summary_list.append(f"- {event.get('summary', 'No Title')} at {formatted_time}")
        return "Today's Schedule:\n" + "\n".join(summary_list)
    except Exception as e:
        return f"Failed to fetch today's events: {e}"
def get_agenda(days: int = 7, calendar_id: str = "primary") -> str:
    """Agenda for the next N days from one calendar."""
    calendar = _calendar()
    if not calendar:
        return "Failed to connect to Google Calendar."
    try:
        manila_tz = ZoneInfo("Asia/Manila")
        now = datetime.datetime.now(manila_tz)
        end = now + datetime.timedelta(days=days)
        events_result = calendar.events().list(
            calendarId=calendar_id, timeMin=now.isoformat(),
            timeMax=end.isoformat(), singleEvents=True,
            orderBy='startTime').execute()
        events = events_result.get('items', [])
        if not events:
            return f"No events in the next {days} day(s)."
        lines = []
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date', ''))
            lines.append(f"- {start} : {event.get('summary', 'No Title')}")
        return f"Agenda (next {days} days):\n" + "\n".join(lines)
    except Exception as e:
        return f"Failed to get agenda: {e}"
def list_calendars() -> str:
    """Lists calendars on the calendar list (id, name, access role)."""
    calendar = _calendar()
    if not calendar:
        return "Failed to connect to Google Calendar."
    try:
        res = calendar.calendarList().list().execute()
        items = res.get('items', [])
        return _as_json([{'id': c['id'], 'summary': c.get('summary'),
                          'accessRole': c.get('accessRole'),
                          'primary': c.get('primary', False)} for c in items])
    except Exception as e:
        return f"Failed to list calendars: {e}"
def get_calendar_list_entry(calendar_id: str) -> str:
    """Details of one calendar list entry."""
    calendar = _calendar()
    if not calendar:
        return "Failed to connect to Google Calendar."
    try:
        entry = calendar.calendarList().get(calendarId=calendar_id).execute()
        return _as_json(entry)
    except Exception as e:
        return f"Failed to get calendar '{calendar_id}': {e}"
def list_events(calendar_id: str = "primary", time_min: str = "",
                time_max: str = "") -> str:
    """Lists events in a window. Times are RFC3339, eg 2026-10-08T00:00:00+08:00."""
    calendar = _calendar()
    if not calendar:
        return "Failed to connect to Google Calendar."
    try:
        params = {'calendarId': calendar_id, 'singleEvents': True,
                  'orderBy': 'startTime'}
        if time_min:
            params['timeMin'] = time_min
        if time_max:
            params['timeMax'] = time_max
        res = calendar.events().list(**params).execute()
        items = res.get('items', [])
        if not items:
            return "No events found."
        return _as_json([{'id': e['id'], 'summary': e.get('summary'),
                          'start': e.get('start'), 'end': e.get('end'),
                          'location': e.get('location')} for e in items])
    except Exception as e:
        return f"Failed to list events: {e}"
def get_event(calendar_id: str, event_id: str) -> str:
    """Full details of one event."""
    calendar = _calendar()
    if not calendar:
        return "Failed to connect to Google Calendar."
    try:
        event = calendar.events().get(calendarId=calendar_id,
                                       eventId=event_id).execute()
        return _as_json(event)
    except Exception as e:
        return f"Failed to get event: {e}"
def list_event_instances(calendar_id: str, event_id: str) -> str:
    """Instances of a recurring event."""
    calendar = _calendar()
    if not calendar:
        return "Failed to connect to Google Calendar."
    try:
        res = calendar.events().instances(calendarId=calendar_id,
                                           eventId=event_id).execute()
        items = res.get('items', [])
        return _as_json([{'id': e['id'], 'summary': e.get('summary'),
                          'start': e.get('start'), 'end': e.get('end')}
                         for e in items])
    except Exception as e:
        return f"Failed to list instances: {e}"
def check_freebusy(time_min: str, time_max: str,
                   calendar_ids: list = None) -> str:
    """Checks free/busy for calendars in a window. Times are RFC3339."""
    calendar = _calendar()
    if not calendar:
        return "Failed to connect to Google Calendar."
    try:
        items = [{'id': c} for c in (calendar_ids or ['primary'])]
        res = calendar.freebusy().query(
            body={'timeMin': time_min, 'timeMax': time_max,
                  'items': items}).execute()
        return _as_json(res.get('calendars', {}))
    except Exception as e:
        return f"Free/busy check failed: {e}"
def create_calendar_event(summary: str, start_time: str, end_time: str,
                          description: str = None, location: str = None,
                          reminder_minutes: list = None,
                          timezone: str = 'Asia/Manila') -> str:
    """Creates an event on your primary Google Calendar."""
    calendar = _calendar()
    if not calendar:
        return "Failed to connect to Google Calendar."
    try:
        event_body = {
            'summary': summary,
            'start': {'dateTime': start_time, 'timeZone': timezone},
            'end': {'dateTime': end_time, 'timeZone': timezone},
        }
        if description:
            event_body['description'] = description
        if location:
            event_body['location'] = location
        if reminder_minutes:
            event_body['reminders'] = {
                'useDefault': False,
                'overrides': [{'method': 'popup', 'minutes': m}
                              for m in reminder_minutes]}
        else:
            event_body['reminders'] = {'useDefault': True}
        created_event = calendar.events().insert(calendarId='primary',
                                                  body=event_body).execute()
        return (f"Successfully created event '{summary}' from {start_time} to {end_time} "
                f"({timezone}). Event ID: {created_event.get('id')}. "
                f"Link: {created_event.get('htmlLink')}")
    except Exception as e:
        return f"Failed to create calendar event: {e}"
def create_event(summary: str, start: str, end: str,
                 calendar_id: str = "primary", location: str = None,
                 description: str = None, attendees: list = None,
                 all_day: bool = False) -> str:
    """Creates a calendar event with optional guests and all-day support. With guests, ONLY call after the user approved the exact time and attendee list."""
    calendar = _calendar()
    if not calendar:
        return "Failed to connect to Google Calendar."
    try:
        body = {'summary': summary}
        if all_day:
            body['start'] = {'date': start}
            body['end'] = {'date': end}
        else:
            body['start'] = {'dateTime': start}
            body['end'] = {'dateTime': end}
        if location:
            body['location'] = location
        if description:
            body['description'] = description
        params = {'calendarId': calendar_id}
        if attendees:
            body['attendees'] = [{'email': e} for e in attendees]
            params['sendUpdates'] = 'all'
        created = calendar.events().insert(body=body, **params).execute()
        return (f"Created event '{summary}' (ID: {created.get('id')}). "
                f"Link: {created.get('htmlLink')}")
    except Exception as e:
        return f"Failed to create event: {e}"
def update_event(calendar_id: str, event_id: str, updates: dict,
                 notify_guests: bool = True) -> str:
    """Patches an event (only supplied fields change). For attendees pass the FULL list."""
    calendar = _calendar()
    if not calendar:
        return "Failed to connect to Google Calendar."
    try:
        params = {'calendarId': calendar_id, 'eventId': event_id}
        if notify_guests:
            params['sendUpdates'] = 'all'
        updated = calendar.events().patch(body=updates, **params).execute()
        return (f"Updated event '{updated.get('summary')}' (ID: {event_id}). "
                f"Link: {updated.get('htmlLink')}")
    except Exception as e:
        return f"Failed to update event: {e}"
def full_update_event(calendar_id: str, event_id: str, body: dict,
                      notify_guests: bool = True) -> str:
    """Fully replaces an event resource (unsupplied fields are cleared)."""
    calendar = _calendar()
    if not calendar:
        return "Failed to connect to Google Calendar."
    try:
        params = {'calendarId': calendar_id, 'eventId': event_id}
        if notify_guests:
            params['sendUpdates'] = 'all'
        updated = calendar.events().update(body=body, **params).execute()
        return (f"Replaced event '{updated.get('summary')}' (ID: {event_id}). "
                f"Link: {updated.get('htmlLink')}")
    except Exception as e:
        return f"Failed to replace event: {e}"
def move_event(calendar_id: str, event_id: str,
               destination_calendar_id: str,
               notify_guests: bool = True) -> str:
    """Moves an event to another calendar."""
    calendar = _calendar()
    if not calendar:
        return "Failed to connect to Google Calendar."
    try:
        params = {'calendarId': calendar_id, 'eventId': event_id,
                  'destination': destination_calendar_id}
        if notify_guests:
            params['sendUpdates'] = 'all'
        moved = calendar.events().move(**params).execute()
        return f"Moved event to '{destination_calendar_id}' (ID: {moved.get('id')})."
    except Exception as e:
        return f"Failed to move event: {e}"
def delete_event(calendar_id: str, event_id: str,
                 notify_guests: bool = True) -> str:
    """Deletes a calendar event. With guests, ONLY call after approval."""
    calendar = _calendar()
    if not calendar:
        return "Failed to connect to Google Calendar."
    try:
        params = {'calendarId': calendar_id, 'eventId': event_id}
        if notify_guests:
            params['sendUpdates'] = 'all'
        calendar.events().delete(**params).execute()
        return f"Deleted event '{event_id}' from '{calendar_id}'."
    except Exception as e:
        return f"Failed to delete event: {e}"
def list_calendar_acl(calendar_id: str) -> str:
    """Shows the sharing rules for a calendar. Confirm with the user before changing any."""
    calendar = _calendar()
    if not calendar:
        return "Failed to connect to Google Calendar."
    try:
        res = calendar.acl().list(calendarId=calendar_id).execute()
        items = res.get('items', [])
        return _as_json([{'id': r.get('id'), 'role': r.get('role'),
                          'scope': r.get('scope')} for r in items])
    except Exception as e:
        return f"Failed to list calendar sharing rules: {e}"
def share_calendar(calendar_id: str, email: str,
                   role: str = "reader") -> str:
    """Shares a calendar with someone (role: reader/writer/owner). ONLY call after approval."""
    calendar = _calendar()
    if not calendar:
        return "Failed to connect to Google Calendar."
    if role not in ("reader", "writer", "owner", "freeBusyReader"):
        return "Role must be reader, writer, owner, or freeBusyReader."
    try:
        rule = calendar.acl().insert(
            calendarId=calendar_id, sendNotifications=True,
            body={'scope': {'type': 'user', 'value': email},
                  'role': role}).execute()
        return f"Shared calendar with {email} as {role} (rule ID: {rule.get('id')})."
    except Exception as e:
        return f"Failed to share calendar: {e}"
def remove_calendar_share(calendar_id: str, rule_id: str) -> str:
    """Removes a calendar sharing rule. ONLY call after approval."""
    calendar = _calendar()
    if not calendar:
        return "Failed to connect to Google Calendar."
    try:
        calendar.acl().delete(calendarId=calendar_id, ruleId=rule_id).execute()
        return f"Removed sharing rule '{rule_id}' from calendar '{calendar_id}'."
    except Exception as e:
        return f"Failed to remove share: {e}"

__all__ = [
    "calendar_status",
    "get_today_calendar_events",
    "get_agenda",
    "list_calendars",
    "get_calendar_list_entry",
    "list_events",
    "get_event",
    "list_event_instances",
    "check_freebusy",
    "create_calendar_event",
    "create_event",
    "update_event",
    "full_update_event",
    "move_event",
    "delete_event",
    "list_calendar_acl",
    "share_calendar",
    "remove_calendar_share",
]
