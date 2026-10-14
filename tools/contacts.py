"""Mavis's address book.

A tiny JSON store (contacts.json next to the Obsidian vault) so she stops
burning Gmail searches every time Rey says "email Jayvin". The brain should
call lookup_contact BEFORE searching Gmail for someone's address, and
save_contact whenever it learns a new email/phone number.
"""
import json
import os

from core.settings import BRAIN_DIR

CONTACTS_FILE = os.path.join(BRAIN_DIR, "contacts.json")


def _load() -> list:
    try:
        with open(CONTACTS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("contacts"), list):
            return data["contacts"]
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return []


def _save(contacts: list) -> None:
    os.makedirs(os.path.dirname(CONTACTS_FILE), exist_ok=True)
    tmp = CONTACTS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"contacts": contacts}, f, indent=2, ensure_ascii=False)
    os.replace(tmp, CONTACTS_FILE)


def _matches(contact: dict, query: str) -> bool:
    fields = [contact.get("name", ""), contact.get("email", ""),
              contact.get("phone", ""), contact.get("notes", "")]
    fields += contact.get("aliases") or []
    return any(query in str(f).lower() for f in fields if f)


def lookup_contact(name: str) -> str:
    """Looks up a person's contact details (email, phone, notes) in Mavis's
    address book. Call this BEFORE searching Gmail for someone's email address."""
    q = (name or "").strip().lower()
    if not q:
        return "Please give me a name to look up."
    hits = [c for c in _load() if _matches(c, q)]
    if not hits:
        return (f"No contact found for '{name}'. You can save one with "
                "save_contact.")
    lines = []
    for c in hits[:5]:
        bits = [c.get("name") or "?"]
        if c.get("email"):
            bits.append(f"email: {c['email']}")
        if c.get("phone"):
            bits.append(f"phone: {c['phone']}")
        if c.get("notes"):
            bits.append(f"notes: {c['notes']}")
        lines.append(" | ".join(bits))
    extra = f" (+{len(hits) - 5} more)" if len(hits) > 5 else ""
    return "Found contact(s): " + "; ".join(lines) + extra


def save_contact(name: str, email: str = None, phone: str = None,
                 notes: str = None) -> str:
    """Saves or updates a contact in Mavis's address book. Use this whenever
    you learn someone's email or phone number so you never have to search
    for it again."""
    name = (name or "").strip()
    if not name:
        return "Please give me a name for the contact."
    contacts = _load()
    key = name.lower()
    existing = next(
        (c for c in contacts
         if c.get("name", "").lower() == key
         or key in [str(a).lower() for a in (c.get("aliases") or [])]),
        None,
    )
    if existing:
        if email:
            existing["email"] = email.strip()
        if phone:
            existing["phone"] = phone.strip()
        if notes:
            existing["notes"] = notes.strip()
        action = "updated"
        label = existing.get("name") or name
    else:
        contacts.append({
            "name": name,
            "email": (email or "").strip(),
            "phone": (phone or "").strip(),
            "notes": (notes or "").strip(),
            "aliases": [],
        })
        action = "saved"
        label = name
    _save(contacts)
    return f"Contact '{label}' {action} in the address book."


__all__ = ["lookup_contact", "save_contact"]
