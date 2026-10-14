"""Google Drive tools for Mavis."""
import mimetypes
import os

from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

from tools.google_auth import DOWNLOADS_DIR, _as_json, _drive, _escape_query
_DRIVE_FIELDS = ("id,name,mimeType,parents,webViewLink,modifiedTime,"
                 "createdTime,owners,size,trashed")
_NATIVE_EXPORT = {
    'application/vnd.google-apps.document': 'application/pdf',
    'application/vnd.google-apps.spreadsheet':
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'application/vnd.google-apps.presentation':
        'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    'application/vnd.google-apps.drawing': 'application/pdf',
    'application/vnd.google-apps.script': 'application/vnd.google-apps.script+json',
}

def drive_status() -> str:
    """Checks whether Google Drive is connected."""
    drive = _drive()
    if not drive:
        return "Google Drive is not connected. Run the OAuth flow first."
    try:
        drive.about().get(fields='user').execute()
        return "Google Drive is connected."
    except Exception as e:
        return f"Drive connection check failed: {e}"
def drive_about_info() -> str:
    """Drive quota and user info."""
    drive = _drive()
    if not drive:
        return "Failed to connect to Google Drive."
    try:
        about = drive.about().get(fields='user,storageQuota').execute()
        return _as_json(about)
    except Exception as e:
        return f"Failed to read Drive info: {e}"
def list_drive_files(max_results: int = 10) -> str:
    """Lists recent files from your Google Drive."""
    drive = _drive()
    if not drive:
        return "Failed to connect to Google Drive."
    try:
        results = drive.files().list(
            pageSize=max_results,
            fields="nextPageToken, files(id, name, mimeType)").execute()
        items = results.get('files', [])
        if not items:
            return "No files found in Google Drive."
        file_list = [f"- {item['name']} (ID: {item['id']})" for item in items]
        return "Google Drive Files:\n" + "\n".join(file_list)
    except Exception as e:
        return f"Failed to list Drive files: {e}"
def search_drive_files(name_contains: str, max_results: int = 20) -> str:
    """Searches Drive by file name."""
    drive = _drive()
    if not drive:
        return "Failed to connect to Google Drive."
    try:
        q = f"name contains '{_escape_query(name_contains)}' and trashed=false"
        res = drive.files().list(q=q, pageSize=min(max_results, 50),
                                  fields=f"files({_DRIVE_FIELDS})").execute()
        items = res.get('files', [])
        if not items:
            return f"No files found matching '{name_contains}'."
        return _as_json(items)
    except Exception as e:
        return f"Drive search failed: {e}"
def search_drive_content(text: str, max_results: int = 20) -> str:
    """Full-text search inside Drive files."""
    drive = _drive()
    if not drive:
        return "Failed to connect to Google Drive."
    try:
        q = f"fullText contains '{_escape_query(text)}' and trashed=false"
        res = drive.files().list(q=q, pageSize=min(max_results, 50),
                                  fields=f"files({_DRIVE_FIELDS})").execute()
        items = res.get('files', [])
        if not items:
            return f"No files containing '{text}'."
        return _as_json(items)
    except Exception as e:
        return f"Drive content search failed: {e}"
def browse_drive_folder(folder_id: str, max_results: int = 50) -> str:
    """Lists the contents of a Drive folder."""
    drive = _drive()
    if not drive:
        return "Failed to connect to Google Drive."
    try:
        q = f"'{folder_id}' in parents and trashed=false"
        res = drive.files().list(q=q, pageSize=min(max_results, 100),
                                  fields=f"files({_DRIVE_FIELDS})").execute()
        items = res.get('files', [])
        if not items:
            return f"Folder '{folder_id}' is empty."
        return _as_json(items)
    except Exception as e:
        return f"Failed to browse folder: {e}"
def get_drive_file_details(file_id: str) -> str:
    """Metadata for one Drive file (name, type, parents, link, size, owners)."""
    drive = _drive()
    if not drive:
        return "Failed to connect to Google Drive."
    try:
        meta = drive.files().get(fileId=file_id,
                                  fields=_DRIVE_FIELDS).execute()
        return _as_json(meta)
    except Exception as e:
        return f"Failed to get file details: {e}"
def upload_file_to_drive(filename: str) -> str:
    """Uploads a local file from your Download folder directly to Google Drive."""
    gmail, calendar, drive = authenticate_google()
    if not drive:
        return "Failed to connect to Google Drive."
    target_path = None
    for root, _, files in os.walk(DOWNLOADS_DIR):
        if filename in files:
            target_path = os.path.join(root, filename)
            break
    if not target_path or not os.path.exists(target_path):
        return f"Could not find local file '{filename}' in Download folder to upload."
    try:
        file_metadata = {'name': os.path.basename(target_path)}
        media = MediaFileUpload(target_path, resumable=True)
        uploaded_file = drive.files().create(body=file_metadata,
                                             media_body=media,
                                             fields='id').execute()
        return (f"Successfully uploaded '{filename}' to Google Drive "
                f"(File ID: {uploaded_file.get('id')}).")
    except Exception as e:
        return f"Failed to upload file to Google Drive: {e}"
def upload_to_drive(local_path: str, parent_folder_id: str = None,
                    target_name: str = None) -> str:
    """Uploads any local file to Drive, optionally into a folder and/or renamed."""
    drive = _drive()
    if not drive:
        return "Failed to connect to Google Drive."
    path = os.path.expanduser(local_path)
    if not os.path.exists(path):
        return f"Local file not found: {path}"
    try:
        metadata = {'name': target_name or os.path.basename(path)}
        if parent_folder_id:
            metadata['parents'] = [parent_folder_id]
        media = MediaFileUpload(path, resumable=True)
        uploaded = drive.files().create(body=metadata, media_body=media,
                                         fields='id,name,webViewLink').execute()
        return (f"Uploaded '{uploaded.get('name')}' (ID: {uploaded.get('id')}). "
                f"Link: {uploaded.get('webViewLink')}")
    except Exception as e:
        return f"Failed to upload: {e}"
def update_drive_file_content(file_id: str, local_path: str) -> str:
    """Replaces a Drive file's content, keeping its id and link."""
    drive = _drive()
    if not drive:
        return "Failed to connect to Google Drive."
    path = os.path.expanduser(local_path)
    if not os.path.exists(path):
        return f"Local file not found: {path}"
    try:
        media = MediaFileUpload(path, resumable=True)
        updated = drive.files().update(fileId=file_id, media_body=media,
                                        fields='id,name,modifiedTime').execute()
        return (f"Updated content of '{updated.get('name')}' "
                f"(ID: {file_id}).")
    except Exception as e:
        return f"Failed to update file content: {e}"
def download_from_drive(file_id: str, output_path: str = None) -> str:
    """Downloads a Drive file. Google-native Docs/Sheets/Slides are auto-exported (PDF/XLSX/PPTX)."""
    drive = _drive()
    if not drive:
        return "Failed to connect to Google Drive."
    try:
        meta = drive.files().get(fileId=file_id,
                                  fields='id,name,mimeType').execute()
        name, mime = meta.get('name', file_id), meta.get('mimeType', '')
        if not output_path:
            os.makedirs(DOWNLOADS_DIR, exist_ok=True)
            ext = ''
            if mime in _NATIVE_EXPORT:
                ext = {'application/pdf': '.pdf',
                       'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': '.xlsx',
                       'application/vnd.openxmlformats-officedocument.presentationml.presentation': '.pptx'}.get(
                           _NATIVE_EXPORT[mime], '')
            output_path = os.path.join(DOWNLOADS_DIR, name + ext)
        with open(output_path, 'wb') as f:
            if mime in _NATIVE_EXPORT:
                request = drive.files().export_media(
                    fileId=file_id, mimeType=_NATIVE_EXPORT[mime])
            else:
                request = drive.files().get_media(fileId=file_id)
            downloader = MediaIoBaseDownload(f, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
        return f"Downloaded '{name}' to {output_path}."
    except Exception as e:
        return f"Failed to download file: {e}"
def create_drive_folder(name: str, parent_folder_id: str = "root") -> str:
    """Creates a Drive folder."""
    drive = _drive()
    if not drive:
        return "Failed to connect to Google Drive."
    try:
        folder = drive.files().create(
            body={'name': name,
                  'mimeType': 'application/vnd.google-apps.folder',
                  'parents': [parent_folder_id]},
            fields='id,name,webViewLink').execute()
        return (f"Created folder '{name}' (ID: {folder.get('id')}). "
                f"Link: {folder.get('webViewLink')}")
    except Exception as e:
        return f"Failed to create folder: {e}"
def rename_drive_item(file_id: str, new_name: str) -> str:
    """Renames a Drive file or folder."""
    drive = _drive()
    if not drive:
        return "Failed to connect to Google Drive."
    try:
        drive.files().update(fileId=file_id,
                              body={'name': new_name}).execute()
        return f"Renamed item '{file_id}' to '{new_name}'."
    except Exception as e:
        return f"Failed to rename: {e}"
def move_drive_item(file_id: str, dest_folder_id: str) -> str:
    """Moves a Drive file or folder to another folder."""
    drive = _drive()
    if not drive:
        return "Failed to connect to Google Drive."
    try:
        cur = drive.files().get(fileId=file_id, fields='parents').execute()
        parents = cur.get('parents', [])
        params = {'fileId': file_id, 'addParents': dest_folder_id,
                  'fields': 'id,name,parents'}
        if parents:
            params['removeParents'] = ','.join(parents)
        moved = drive.files().update(**params).execute()
        return f"Moved '{moved.get('name')}' to folder '{dest_folder_id}'."
    except Exception as e:
        return f"Failed to move item: {e}"
def copy_drive_item(file_id: str, new_name: str = None,
                    dest_folder_id: str = "root") -> str:
    """Copies a Drive file, optionally renamed and/or into another folder."""
    drive = _drive()
    if not drive:
        return "Failed to connect to Google Drive."
    try:
        body = {'parents': [dest_folder_id]}
        if new_name:
            body['name'] = new_name
        copied = drive.files().copy(fileId=file_id, body=body,
                                     fields='id,name,webViewLink').execute()
        return (f"Copied to '{copied.get('name')}' (ID: {copied.get('id')}). "
                f"Link: {copied.get('webViewLink')}")
    except Exception as e:
        return f"Failed to copy item: {e}"
def trash_drive_item(file_id: str) -> str:
    """Moves a Drive item to trash (reversible). Prefer this over permanent delete."""
    drive = _drive()
    if not drive:
        return "Failed to connect to Google Drive."
    try:
        drive.files().update(fileId=file_id,
                              body={'trashed': True}).execute()
        return f"Trashed Drive item '{file_id}'."
    except Exception as e:
        return f"Failed to trash item: {e}"
def restore_drive_item(file_id: str) -> str:
    """Restores a trashed Drive item."""
    drive = _drive()
    if not drive:
        return "Failed to connect to Google Drive."
    try:
        drive.files().update(fileId=file_id,
                              body={'trashed': False}).execute()
        return f"Restored Drive item '{file_id}' from trash."
    except Exception as e:
        return f"Failed to restore item: {e}"
def delete_drive_item_permanently(file_id: str) -> str:
    """PERMANENTLY deletes a Drive item. Cannot be undone. ONLY call when the user explicitly said permanent."""
    drive = _drive()
    if not drive:
        return "Failed to connect to Google Drive."
    try:
        drive.files().delete(fileId=file_id).execute()
        return f"Permanently deleted Drive item '{file_id}'."
    except Exception as e:
        return f"Failed to permanently delete: {e}"
def share_drive_file(file_id: str, email: str,
                     role: str = "reader") -> str:
    """Shares a Drive file/folder with someone (role: reader/writer/commenter). ONLY call after approval."""
    drive = _drive()
    if not drive:
        return "Failed to connect to Google Drive."
    if role not in ("reader", "writer", "commenter"):
        return "Role must be reader, writer, or commenter."
    try:
        perm = drive.permissions().create(
            fileId=file_id,
            body={'type': 'user', 'role': role, 'emailAddress': email},
            sendNotificationEmail=True, fields='id').execute()
        return (f"Shared with {email} as {role} "
                f"(permission ID: {perm.get('id')}).")
    except Exception as e:
        return f"Failed to share file: {e}"
def list_drive_permissions(file_id: str) -> str:
    """Lists who a Drive file/folder is shared with."""
    drive = _drive()
    if not drive:
        return "Failed to connect to Google Drive."
    try:
        res = drive.permissions().list(fileId=file_id,
                                        fields='permissions(id,type,role,emailAddress,displayName)').execute()
        return _as_json(res.get('permissions', []))
    except Exception as e:
        return f"Failed to list permissions: {e}"
def remove_drive_permission(file_id: str, permission_id: str) -> str:
    """Removes one share from a Drive file/folder. ONLY call after approval."""
    drive = _drive()
    if not drive:
        return "Failed to connect to Google Drive."
    try:
        drive.permissions().delete(fileId=file_id,
                                    permissionId=permission_id).execute()
        return f"Removed permission '{permission_id}' from '{file_id}'."
    except Exception as e:
        return f"Failed to remove permission: {e}"
def list_drive_revisions(file_id: str) -> str:
    """Lists the revision history of a Drive file."""
    drive = _drive()
    if not drive:
        return "Failed to connect to Google Drive."
    try:
        res = drive.revisions().list(
            fileId=file_id,
            fields='revisions(id,modifiedTime,lastModifyingUser,keepForever)').execute()
        return _as_json(res.get('revisions', []))
    except Exception as e:
        return f"Failed to list revisions: {e}"

__all__ = [
    "drive_status",
    "drive_about_info",
    "list_drive_files",
    "search_drive_files",
    "search_drive_content",
    "browse_drive_folder",
    "get_drive_file_details",
    "upload_file_to_drive",
    "upload_to_drive",
    "update_drive_file_content",
    "download_from_drive",
    "create_drive_folder",
    "rename_drive_item",
    "move_drive_item",
    "copy_drive_item",
    "trash_drive_item",
    "restore_drive_item",
    "delete_drive_item_permanently",
    "share_drive_file",
    "list_drive_permissions",
    "remove_drive_permission",
    "list_drive_revisions",
]
