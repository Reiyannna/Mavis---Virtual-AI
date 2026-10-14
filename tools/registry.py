
from tools.local_tools import (
    list_download_files,
    search_download_files,
    read_file, create_note,
    run_local_script,
    get_current_time_and_date,
    save_obsidian_memory,
    read_obsidian_memory,
    rewrite_obsidian_memory,
    search_memory,
    set_alarm,
    check_alarms,
    delete_alarm
)
from tools.google_auth import list_google_accounts
from tools.gmail import (
    # gmail read
    search_emails, read_message, get_message_metadata, list_messages,
    read_thread, list_threads, download_attachment, count_threads,
    get_history, get_unread_emails, gmail_status,
    # gmail labels
    list_labels, get_label, label_counters, create_label,
    delete_label, modify_message_labels, batch_modify_labels,
    # gmail write
    send_email, reply_to_message, forward_message, create_email_draft,
    list_drafts, get_draft, send_draft, send_email_draft,
    delete_draft, unsubscribe_from_messages,
    # gmail organize
    mark_messages, archive_messages, trash_messages, untrash_message,
)
from tools.calendar import (
    get_today_calendar_events, get_agenda, list_calendars,
    get_calendar_list_entry, list_events, get_event,
    list_event_instances, check_freebusy, calendar_status,
    create_calendar_event, create_event, update_event,
    full_update_event, move_event, delete_event,
    list_calendar_acl, share_calendar, remove_calendar_share,
)
from tools.drive import (
    drive_about_info, list_drive_files, search_drive_files,
    search_drive_content, browse_drive_folder, get_drive_file_details,
    upload_file_to_drive, upload_to_drive, update_drive_file_content,
    download_from_drive, create_drive_folder, rename_drive_item,
    move_drive_item, copy_drive_item, trash_drive_item,
    restore_drive_item, delete_drive_item_permanently,
    share_drive_file, list_drive_permissions, remove_drive_permission,
    list_drive_revisions, drive_status,
)

from tools.telegram_tools import send_telegram_file
from tools.contacts import lookup_contact, save_contact

from tools.vscode_tools import (
    read_clipboard,
    scaffold_project,
    generate_code_file
)

MAVIS_TOOLS_LIST = [
    list_download_files,
    search_download_files,
    read_file,
    create_note,
    run_local_script,
    get_current_time_and_date,
    # google connection
    gmail_status, calendar_status, drive_status, list_google_accounts,
    # gmail read
    get_unread_emails, search_emails, read_message, get_message_metadata,
    list_messages, read_thread, list_threads, download_attachment,
    count_threads, get_history,
    # gmail labels
    list_labels, get_label, label_counters, create_label,
    delete_label, modify_message_labels, batch_modify_labels,
    # gmail write
    create_email_draft, send_email, reply_to_message, forward_message,
    list_drafts, get_draft, send_draft, send_email_draft,
    delete_draft, unsubscribe_from_messages,
    # gmail organize
    mark_messages, archive_messages, trash_messages, untrash_message,
    # calendar
    get_today_calendar_events, get_agenda, list_calendars,
    get_calendar_list_entry, list_events, get_event,
    list_event_instances, check_freebusy,
    create_calendar_event, create_event, update_event,
    full_update_event, move_event, delete_event,
    list_calendar_acl, share_calendar, remove_calendar_share,
    # drive
    drive_about_info, list_drive_files, search_drive_files,
    search_drive_content, browse_drive_folder, get_drive_file_details,
    upload_file_to_drive, upload_to_drive, update_drive_file_content,
    download_from_drive, create_drive_folder, rename_drive_item,
    move_drive_item, copy_drive_item, trash_drive_item,
    restore_drive_item, delete_drive_item_permanently,
    share_drive_file, list_drive_permissions, remove_drive_permission,
    list_drive_revisions,
    # memory + alarms
    save_obsidian_memory,
    read_obsidian_memory,
    rewrite_obsidian_memory,
    search_memory,
    set_alarm,
    check_alarms,
    delete_alarm,
    read_clipboard,
    scaffold_project,
    generate_code_file,
    send_telegram_file,
    lookup_contact,
    save_contact,
]

MAVIS_TOOL_MAP = {func.__name__: func for func in MAVIS_TOOLS_LIST}
