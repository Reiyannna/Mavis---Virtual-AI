"""Gmail tools for Mavis (search, read, labels, drafts, send, organize)."""
import base64
import os
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from tools.google_auth import DOWNLOADS_DIR, _as_json, _gmail
def _get_header(headers, name):
    name = name.lower()
    for h in headers or []:
        if h.get('name', '').lower() == name:
            return h.get('value', '')
    return ''
def _decode_part_data(data):
    if not data:
        return ''
    data += '=' * (-len(data) % 4)
    return base64.urlsafe_b64decode(data).decode('utf-8', errors='replace')
def _strip_html(html):
    import re
    text = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', html, flags=re.S | re.I)
    text = re.sub(r'<[^>]+>', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()
def _extract_body(payload):
    """Returns (plain_text_body, attachments). attachments = list of dicts."""
    body_text, html_text, attachments = '', '', []

    def walk(part):
        nonlocal body_text, html_text
        mime = part.get('mimeType', '')
        filename = part.get('filename', '')
        body = part.get('body', {}) or {}
        if filename:
            attachments.append({
                'filename': filename,
                'mimeType': mime,
                'size': body.get('size'),
                'attachmentId': body.get('attachmentId'),
            })
        if mime == 'text/plain' and not body_text and body.get('data'):
            body_text = _decode_part_data(body['data'])
        elif mime == 'text/html' and not html_text and body.get('data'):
            html_text = _decode_part_data(body['data'])
        for sub in part.get('parts', []) or []:
            walk(sub)

    walk(payload or {})
    text = body_text or (_strip_html(html_text) if html_text else '')
    return text, attachments
def _summarize_message(msg):
    """Compact one-line summary dict for a full message resource."""
    headers = msg.get('payload', {}).get('headers', [])
    text, attachments = _extract_body(msg.get('payload', {}))
    return {
        'id': msg.get('id'),
        'threadId': msg.get('threadId'),
        'from': _get_header(headers, 'From'),
        'to': _get_header(headers, 'To'),
        'subject': _get_header(headers, 'Subject'),
        'date': _get_header(headers, 'Date'),
        'labels': msg.get('labelIds', []),
        'snippet': msg.get('snippet', ''),
        'attachments': [{'filename': a['filename'], 'mimeType': a['mimeType'],
                         'attachmentId': a['attachmentId']} for a in attachments],
    }
def _build_mime(to, subject, body, cc=None, bcc=None, html=False,
                attachments=None, in_reply_to_id=None, references=None):
    if attachments:
        msg = MIMEMultipart()
        msg.attach(MIMEText(body, 'html' if html else 'plain'))
        for path in attachments:
            ctype, _ = mimetypes.guess_type(path)
            maintype, _, subtype = (ctype or 'application/octet-stream').partition('/')
            with open(path, 'rb') as f:
                part = MIMEBase(maintype, subtype)
                part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', 'attachment',
                            filename=os.path.basename(path))
            msg.attach(part)
    else:
        msg = MIMEText(body, 'html' if html else 'plain')
    msg['to'] = to
    msg['subject'] = subject
    if cc:
        msg['cc'] = cc
    if bcc:
        msg['bcc'] = bcc
    if in_reply_to_id:
        msg['In-Reply-To'] = in_reply_to_id
    if references:
        msg['References'] = references
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode('utf-8')
    return {'raw': raw}
def _send_raw_message(gmail, raw_body, thread_id=None):
    body = {'raw': raw_body['raw']}
    if thread_id:
        body['threadId'] = thread_id
    return gmail.users().messages().send(userId='me', body=body).execute()

def gmail_status() -> str:
    """Checks whether Gmail is connected and returns the account email."""
    gmail = _gmail()
    if not gmail:
        return "Gmail is not connected. Run the OAuth flow first."
    try:
        profile = gmail.users().getProfile(userId='me').execute()
        return ("Gmail connected as " + profile.get('emailAddress', 'unknown')
                + f". Total messages: {profile.get('messagesTotal', '?')}.")
    except Exception as e:
        return f"Gmail connection check failed: {e}"
def search_emails(query: str, max_results: int = 20) -> str:
    """Searches mail and returns sender, subject, snippet and attachment inventory per hit. Eg: search_emails('from:boss is:unread', 10)."""
    gmail = _gmail()
    if not gmail:
        return "Failed to connect to Gmail."
    try:
        res = gmail.users().messages().list(userId='me', q=query,
                                             maxResults=min(max_results, 50)).execute()
        messages = res.get('messages', [])
        if not messages:
            return f"No messages found for query: {query}"
        out = []
        for m in messages:
            full = gmail.users().messages().get(userId='me', id=m['id'],
                                                 format='full').execute()
            out.append(_summarize_message(full))
        return _as_json(out)
    except Exception as e:
        return f"Email search failed: {e}"
def read_message(message_id: str) -> str:
    """Reads one message: headers, decoded body text, and attachment inventory."""
    gmail = _gmail()
    if not gmail:
        return "Failed to connect to Gmail."
    try:
        msg = gmail.users().messages().get(userId='me', id=message_id,
                                            format='full').execute()
        headers = msg.get('payload', {}).get('headers', [])
        text, attachments = _extract_body(msg.get('payload', {}))
        return _as_json({
            'id': msg.get('id'),
            'threadId': msg.get('threadId'),
            'from': _get_header(headers, 'From'),
            'to': _get_header(headers, 'To'),
            'cc': _get_header(headers, 'Cc'),
            'subject': _get_header(headers, 'Subject'),
            'date': _get_header(headers, 'Date'),
            'labels': msg.get('labelIds', []),
            'body': text[:8000],
            'attachments': attachments,
        })
    except Exception as e:
        return f"Failed to read message '{message_id}': {e}"
def get_message_metadata(message_id: str) -> str:
    """Lightweight From/Subject/Date for one message, without the full body."""
    gmail = _gmail()
    if not gmail:
        return "Failed to connect to Gmail."
    try:
        msg = gmail.users().messages().get(
            userId='me', id=message_id, format='metadata',
            metadataHeaders=['From', 'Subject', 'Date']).execute()
        headers = msg.get('payload', {}).get('headers', [])
        return _as_json({
            'id': message_id,
            'from': _get_header(headers, 'From'),
            'subject': _get_header(headers, 'Subject'),
            'date': _get_header(headers, 'Date'),
            'labels': msg.get('labelIds', []),
        })
    except Exception as e:
        return f"Failed to get metadata for '{message_id}': {e}"
def list_messages(query: str = "", max_results: int = 20) -> str:
    """Raw id + threadId listing for a query."""
    gmail = _gmail()
    if not gmail:
        return "Failed to connect to Gmail."
    try:
        res = gmail.users().messages().list(userId='me', q=query or None,
                                             maxResults=min(max_results, 50)).execute()
        messages = res.get('messages', [])
        if not messages:
            return "No messages found."
        return _as_json([{'id': m['id'], 'threadId': m.get('threadId')}
                         for m in messages])
    except Exception as e:
        return f"Failed to list messages: {e}"
def read_thread(thread_id: str) -> str:
    """Reads a whole conversation thread, oldest message first."""
    gmail = _gmail()
    if not gmail:
        return "Failed to connect to Gmail."
    try:
        thread = gmail.users().threads().get(userId='me', id=thread_id,
                                              format='full').execute()
        messages = thread.get('messages', [])
        if not messages:
            return f"Thread '{thread_id}' is empty."
        out = []
        for msg in messages:
            s = _summarize_message(msg)
            text, _ = _extract_body(msg.get('payload', {}))
            s['body'] = text[:4000]
            out.append(s)
        return _as_json(out)
    except Exception as e:
        return f"Failed to read thread '{thread_id}': {e}"
def list_threads(query: str = "", max_results: int = 20) -> str:
    """Raw thread listing (id + snippet) for a query."""
    gmail = _gmail()
    if not gmail:
        return "Failed to connect to Gmail."
    try:
        res = gmail.users().threads().list(userId='me', q=query or None,
                                            maxResults=min(max_results, 50)).execute()
        threads = res.get('threads', [])
        if not threads:
            return "No threads found."
        return _as_json([{'id': t['id'], 'snippet': t.get('snippet', '')}
                         for t in threads])
    except Exception as e:
        return f"Failed to list threads: {e}"
def download_attachment(message_id: str, attachment_id: str,
                        output_path: str = None) -> str:
    """Downloads one attachment. Defaults to the Download folder."""
    gmail = _gmail()
    if not gmail:
        return "Failed to connect to Gmail."
    try:
        msg = gmail.users().messages().get(userId='me', id=message_id,
                                            format='full').execute()

        def find(part):
            body = part.get('body', {}) or {}
            if body.get('attachmentId') == attachment_id and part.get('filename'):
                return part.get('filename')
            for sub in part.get('parts', []) or []:
                name = find(sub)
                if name:
                    return name
            return None

        filename = find(msg.get('payload', {})) or f"attachment_{attachment_id}"
        if not output_path:
            os.makedirs(DOWNLOADS_DIR, exist_ok=True)
            output_path = os.path.join(DOWNLOADS_DIR, filename)
        att = gmail.users().messages().attachments().get(
            userId='me', messageId=message_id, id=attachment_id).execute()
        data = att.get('data', '')
        data += '=' * (-len(data) % 4)
        with open(output_path, 'wb') as f:
            f.write(base64.urlsafe_b64decode(data))
        return f"Saved attachment '{filename}' to {output_path}."
    except Exception as e:
        return f"Failed to download attachment: {e}"
def count_threads(query: str) -> str:
    """Counts conversations (threads) matching a query."""
    gmail = _gmail()
    if not gmail:
        return "Failed to connect to Gmail."
    try:
        seen = set()
        token = None
        for _ in range(20):
            params = {'userId': 'me', 'q': query, 'maxResults': 500}
            if token:
                params['pageToken'] = token
            res = gmail.users().messages().list(**params).execute()
            for m in res.get('messages', []) or []:
                seen.add(m.get('threadId', m.get('id', '')))
            token = res.get('nextPageToken')
            if not token:
                break
        return f"{len(seen)} conversation(s) match: {query}"
    except Exception as e:
        return f"Failed to count threads: {e}"
def get_history(start_history_id: str) -> str:
    """Lists mailbox history changes since a history id (for sync)."""
    gmail = _gmail()
    if not gmail:
        return "Failed to connect to Gmail."
    try:
        res = gmail.users().history().list(userId='me',
                                            startHistoryId=start_history_id).execute()
        return _as_json({'historyId': res.get('historyId'),
                         'history': res.get('history', [])})
    except Exception as e:
        return f"Failed to get history: {e}"
def get_unread_emails(max_results: int = 5) -> str:
    """Fetches subject lines, senders, and body snippets of unread Gmail messages."""
    gmail = _gmail()
    if not gmail:
        return "Failed to connect to Gmail."
    try:
        results = gmail.users().messages().list(userId='me', q='is:unread',
                                                 maxResults=max_results).execute()
        messages = results.get('messages', [])
        if not messages:
            return "You have no unread emails."
        email_summaries = []
        for msg in messages:
            msg_data = gmail.users().messages().get(userId='me', id=msg['id'],
                                                     format='full').execute()
            headers = msg_data.get('payload', {}).get('headers', [])
            subject = _get_header(headers, 'Subject') or 'No Subject'
            sender = _get_header(headers, 'From') or 'Unknown Sender'
            snippet = msg_data.get('snippet', 'No content available.')
            email_summaries.append(
                f"From: {sender} | Subject: {subject} | Content: {snippet}...")
        return "Unread Emails:\n" + "\n\n".join(email_summaries)
    except Exception as e:
        return f"Failed to fetch unread emails: {e}"
def list_labels() -> str:
    """Lists all Gmail labels."""
    gmail = _gmail()
    if not gmail:
        return "Failed to connect to Gmail."
    try:
        res = gmail.users().labels().list(userId='me').execute()
        labels = res.get('labels', [])
        return _as_json([{'id': l['id'], 'name': l['name'],
                          'type': l.get('type')} for l in labels])
    except Exception as e:
        return f"Failed to list labels: {e}"
def get_label(label_id: str) -> str:
    """Gets one label, including unread/total counters."""
    gmail = _gmail()
    if not gmail:
        return "Failed to connect to Gmail."
    try:
        label = gmail.users().labels().get(userId='me', id=label_id).execute()
        return _as_json(label)
    except Exception as e:
        return f"Failed to get label '{label_id}': {e}"
def label_counters(label_id: str = "UNREAD") -> str:
    """Message counters for a label (UNREAD, INBOX, CATEGORY_PROMOTIONS, ...)."""
    return get_label(label_id)
def create_label(name: str) -> str:
    """Creates a new Gmail label."""
    gmail = _gmail()
    if not gmail:
        return "Failed to connect to Gmail."
    try:
        label = gmail.users().labels().create(userId='me',
                                               body={'name': name}).execute()
        return f"Created label '{name}' (ID: {label.get('id')})."
    except Exception as e:
        return f"Failed to create label '{name}': {e}"
def delete_label(label_id: str) -> str:
    """Deletes a Gmail label (messages keep their other labels)."""
    gmail = _gmail()
    if not gmail:
        return "Failed to connect to Gmail."
    try:
        gmail.users().labels().delete(userId='me', id=label_id).execute()
        return f"Deleted label '{label_id}'."
    except Exception as e:
        return f"Failed to delete label '{label_id}': {e}"
def modify_message_labels(message_id: str, add: list = None,
                          remove: list = None) -> str:
    """Adds/removes label ids on one message. Eg: modify_message_labels(id, add=['STARRED'], remove=['UNREAD'])."""
    gmail = _gmail()
    if not gmail:
        return "Failed to connect to Gmail."
    try:
        gmail.users().messages().modify(
            userId='me', id=message_id,
            body={'addLabelIds': add or [], 'removeLabelIds': remove or []}
        ).execute()
        return f"Updated labels on message '{message_id}'."
    except Exception as e:
        return f"Failed to modify labels: {e}"
def batch_modify_labels(message_ids: list, add: list = None,
                        remove: list = None) -> str:
    """Adds/removes labels on many messages at once."""
    gmail = _gmail()
    if not gmail:
        return "Failed to connect to Gmail."
    try:
        gmail.users().messages().batchModify(
            userId='me',
            body={'ids': message_ids, 'addLabelIds': add or [],
                  'removeLabelIds': remove or []}).execute()
        return f"Updated labels on {len(message_ids)} message(s)."
    except Exception as e:
        return f"Failed to batch-modify labels: {e}"
def send_email(to: str, subject: str, body: str, cc: str = None,
               bcc: str = None, html: bool = False,
               attachments: list = None) -> str:
    """Sends a new email. ONLY call after the user approved the exact recipients, subject and body."""
    gmail = _gmail()
    if not gmail:
        return "Failed to connect to Gmail."
    try:
        mime = _build_mime(to, subject, body, cc=cc, bcc=bcc, html=html,
                           attachments=attachments)
        sent = _send_raw_message(gmail, mime)
        return f"Sent email to {to} with subject '{subject}' (Message ID: {sent.get('id')})."
    except Exception as e:
        return f"Failed to send email: {e}"
def reply_to_message(message_id: str, body: str, reply_all: bool = False,
                     html: bool = False, attachments: list = None) -> str:
    """Replies to a message in its thread. ONLY call after approval of the exact reply text."""
    gmail = _gmail()
    if not gmail:
        return "Failed to connect to Gmail."
    try:
        orig = gmail.users().messages().get(userId='me', id=message_id,
                                             format='full').execute()
        headers = orig.get('payload', {}).get('headers', [])
        to = _get_header(headers, 'Reply-To') or _get_header(headers, 'From')
        subject = _get_header(headers, 'Subject')
        if subject and not subject.lower().startswith('re:'):
            subject = 'Re: ' + subject
        cc = _get_header(headers, 'Cc') if reply_all else ''
        msg_id = _get_header(headers, 'Message-ID')
        refs = _get_header(headers, 'References')
        references = (refs + ' ' + msg_id).strip() if msg_id else refs
        mime = _build_mime(to, subject, body, cc=cc or None, html=html,
                           attachments=attachments, in_reply_to_id=msg_id,
                           references=references or None)
        sent = _send_raw_message(gmail, mime, thread_id=orig.get('threadId'))
        return f"Replied to '{subject}' (Message ID: {sent.get('id')})."
    except Exception as e:
        return f"Failed to reply: {e}"
def forward_message(message_id: str, to: str, body: str = None) -> str:
    """Forwards a message. ONLY call after approval of the recipient."""
    gmail = _gmail()
    if not gmail:
        return "Failed to connect to Gmail."
    try:
        orig = gmail.users().messages().get(userId='me', id=message_id,
                                             format='full').execute()
        headers = orig.get('payload', {}).get('headers', [])
        subject = _get_header(headers, 'Subject')
        if subject and not subject.lower().startswith('fwd:'):
            subject = 'Fwd: ' + subject
        orig_text, _ = _extract_body(orig.get('payload', {}))
        quoted = (f"\n\n---------- Forwarded message ----------\n"
                  f"From: {_get_header(headers, 'From')}\n"
                  f"Date: {_get_header(headers, 'Date')}\n"
                  f"Subject: {_get_header(headers, 'Subject')}\n\n{orig_text}")
        full_body = (body + quoted) if body else quoted
        mime = _build_mime(to, subject, full_body)
        sent = _send_raw_message(gmail, mime)
        return f"Forwarded to {to} (Message ID: {sent.get('id')})."
    except Exception as e:
        return f"Failed to forward: {e}"
def create_email_draft(to: str, subject: str, body: str, cc: str = None,
                       bcc: str = None, html: bool = False,
                       attachments: list = None, in_reply_to: str = None,
                       forward_of: str = None) -> str:
    """Creates a draft email in Gmail for review before sending."""
    gmail = _gmail()
    if not gmail:
        return "Failed to connect to Gmail."
    if body:
        body = body.replace('\\n', '\n')
    try:
        thread_id = None
        if in_reply_to:
            orig = gmail.users().messages().get(userId='me', id=in_reply_to,
                                                 format='full').execute()
            headers = orig.get('payload', {}).get('headers', [])
            msg_id = _get_header(headers, 'Message-ID')
            refs = _get_header(headers, 'References')
            references = (refs + ' ' + msg_id).strip() if msg_id else refs
            mime = _build_mime(to, subject, body, cc=cc, bcc=bcc, html=html,
                               attachments=attachments, in_reply_to_id=msg_id,
                               references=references or None)
            thread_id = orig.get('threadId')
        elif forward_of:
            orig = gmail.users().messages().get(userId='me', id=forward_of,
                                                 format='full').execute()
            orig_text, _ = _extract_body(orig.get('payload', {}))
            body = body + "\n\n---------- Forwarded message ----------\n" + orig_text
            mime = _build_mime(to, subject, body, cc=cc, bcc=bcc, html=html,
                               attachments=attachments)
        else:
            mime = _build_mime(to, subject, body, cc=cc, bcc=bcc, html=html,
                               attachments=attachments)
        draft_body = {'message': mime}
        if thread_id:
            draft_body['message']['threadId'] = thread_id
        draft = gmail.users().drafts().create(userId='me',
                                               body=draft_body).execute()
        draft_id = draft.get('id')
        return (f"Successfully created email draft to {to} with subject '{subject}'. "
                f"Draft ID: {draft_id} (use this with send_draft to send it).")
    except Exception as e:
        return f"Failed to create draft: {e}"
def list_drafts() -> str:
    """Lists Gmail drafts."""
    gmail = _gmail()
    if not gmail:
        return "Failed to connect to Gmail."
    try:
        res = gmail.users().drafts().list(userId='me').execute()
        drafts = res.get('drafts', [])
        if not drafts:
            return "No drafts."
        out = []
        for d in drafts:
            full = gmail.users().drafts().get(userId='me', id=d['id'],
                                               format='metadata',
                                               metadataHeaders=['To', 'Subject']
                                               ).execute()
            headers = full.get('message', {}).get('payload', {}).get('headers', [])
            out.append({'id': d['id'],
                        'to': _get_header(headers, 'To'),
                        'subject': _get_header(headers, 'Subject')})
        return _as_json(out)
    except Exception as e:
        return f"Failed to list drafts: {e}"
def get_draft(draft_id: str) -> str:
    """Reads one draft with its body."""
    gmail = _gmail()
    if not gmail:
        return "Failed to connect to Gmail."
    try:
        full = gmail.users().drafts().get(userId='me', id=draft_id,
                                           format='full').execute()
        payload = full.get('message', {}).get('payload', {})
        headers = payload.get('headers', [])
        text, attachments = _extract_body(payload)
        return _as_json({
            'id': draft_id,
            'to': _get_header(headers, 'To'),
            'subject': _get_header(headers, 'Subject'),
            'body': text[:8000],
            'attachments': [a['filename'] for a in attachments],
        })
    except Exception as e:
        return f"Failed to get draft '{draft_id}': {e}"
def send_draft(draft_id: str) -> str:
    """Sends an existing draft. ONLY call after the user approved its exact content."""
    return send_email_draft(draft_id)
def send_email_draft(draft_id: str) -> str:
    """Sends a previously created Gmail draft. ONLY call after approval of its exact content."""
    gmail = _gmail()
    if not gmail:
        return "Failed to connect to Gmail."
    try:
        sent_message = gmail.users().drafts().send(userId='me',
                                                    body={'id': draft_id}).execute()
        return (f"Successfully sent draft (Draft ID: {draft_id}, "
                f"Message ID: {sent_message.get('id')}).")
    except Exception as e:
        return f"Failed to send draft '{draft_id}': {e}"
def delete_draft(draft_id: str) -> str:
    """Deletes a draft without sending."""
    gmail = _gmail()
    if not gmail:
        return "Failed to connect to Gmail."
    try:
        gmail.users().drafts().delete(userId='me', id=draft_id).execute()
        return f"Deleted draft '{draft_id}'."
    except Exception as e:
        return f"Failed to delete draft '{draft_id}': {e}"
def unsubscribe_from_messages(message_ids: list) -> str:
    """Finds List-Unsubscribe targets for messages (one-click HTTPS or mailto). Does NOT send anything; the user acts on the results."""
    gmail = _gmail()
    if not gmail:
        return "Failed to connect to Gmail."
    try:
        out = []
        for mid in message_ids[:20]:
            msg = gmail.users().messages().get(
                userId='me', id=mid, format='metadata',
                metadataHeaders=['From', 'Subject', 'List-Unsubscribe',
                                 'List-Unsubscribe-Post']).execute()
            headers = msg.get('payload', {}).get('headers', [])
            out.append({
                'id': mid,
                'from': _get_header(headers, 'From'),
                'subject': _get_header(headers, 'Subject'),
                'list_unsubscribe': _get_header(headers, 'List-Unsubscribe'),
                'one_click': _get_header(headers, 'List-Unsubscribe-Post'),
            })
        return _as_json(out)
    except Exception as e:
        return f"Failed to check unsubscribe info: {e}"
def _resolve_targets(message_ids, thread_ids):
    return (message_ids or [], thread_ids or [])


def mark_messages(message_ids: list = None, thread_ids: list = None,
                  read: bool = True) -> str:
    """Marks messages/threads read (or unread)."""
    gmail = _gmail()
    if not gmail:
        return "Failed to connect to Gmail."
    mids, tids = _resolve_targets(message_ids, thread_ids)
    try:
        if read:
            add, remove = [], ['UNREAD']
        else:
            add, remove = ['UNREAD'], []
        for mid in mids:
            gmail.users().messages().modify(
                userId='me', id=mid,
                body={'addLabelIds': add, 'removeLabelIds': remove}).execute()
        for tid in tids:
            gmail.users().threads().modify(
                userId='me', id=tid,
                body={'addLabelIds': add, 'removeLabelIds': remove}).execute()
        return f"Marked {len(mids) + len(tids)} item(s) as {'read' if read else 'unread'}."
    except Exception as e:
        return f"Failed to mark messages: {e}"
def archive_messages(message_ids: list = None, thread_ids: list = None) -> str:
    """Archives messages/threads (removes INBOX label)."""
    gmail = _gmail()
    if not gmail:
        return "Failed to connect to Gmail."
    mids, tids = _resolve_targets(message_ids, thread_ids)
    try:
        for mid in mids:
            gmail.users().messages().modify(
                userId='me', id=mid, body={'removeLabelIds': ['INBOX']}).execute()
        for tid in tids:
            gmail.users().threads().modify(
                userId='me', id=tid, body={'removeLabelIds': ['INBOX']}).execute()
        return f"Archived {len(mids) + len(tids)} item(s)."
    except Exception as e:
        return f"Failed to archive: {e}"
def trash_messages(message_ids: list = None, thread_ids: list = None) -> str:
    """Moves messages/threads to trash (reversible for 30 days). Prefer this over permanent delete."""
    gmail = _gmail()
    if not gmail:
        return "Failed to connect to Gmail."
    mids, tids = _resolve_targets(message_ids, thread_ids)
    try:
        for mid in mids:
            gmail.users().messages().trash(userId='me', id=mid).execute()
        for tid in tids:
            gmail.users().threads().trash(userId='me', id=tid).execute()
        return f"Trashed {len(mids) + len(tids)} item(s)."
    except Exception as e:
        return f"Failed to trash: {e}"
def untrash_message(message_id: str) -> str:
    """Restores a trashed message back to the inbox."""
    gmail = _gmail()
    if not gmail:
        return "Failed to connect to Gmail."
    try:
        gmail.users().messages().untrash(userId='me', id=message_id).execute()
        return f"Restored message '{message_id}' from trash."
    except Exception as e:
        return f"Failed to restore message: {e}"

__all__ = [
    "gmail_status",
    "search_emails",
    "read_message",
    "get_message_metadata",
    "list_messages",
    "read_thread",
    "list_threads",
    "download_attachment",
    "count_threads",
    "get_history",
    "get_unread_emails",
    "list_labels",
    "get_label",
    "label_counters",
    "create_label",
    "delete_label",
    "modify_message_labels",
    "batch_modify_labels",
    "send_email",
    "reply_to_message",
    "forward_message",
    "create_email_draft",
    "list_drafts",
    "get_draft",
    "send_draft",
    "send_email_draft",
    "delete_draft",
    "unsubscribe_from_messages",
    "mark_messages",
    "archive_messages",
    "trash_messages",
    "untrash_message",
]
