"""
core/execution/mail_remote_script.py

This file is NOT imported by the server. mail_client.py reads it as text,
fills in the parameters, and sends it through the bridge (command type
"python"), so it runs on the USER'S machine with the user's own Python.

It talks straight to the mail server over IMAP (reading, Sent, Drafts) and
SMTP (sending). Standard library only, nothing to install.

Rules it keeps:
  - Every value (addresses, subject, body, search terms) arrives inside one
    base64-encoded JSON blob, so nothing an LLM writes can ever become code.
  - Output is a single line of ASCII-only JSON, so Chinese mail survives any
    Windows console encoding.
  - Errors come back as {"ok": false, "error": "..."} in plain words.
"""

import base64
import json
import re
import socket
import sys
import time
import imaplib
import smtplib
import mimetypes
import os
from datetime import datetime
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import make_msgid, formatdate, formataddr, parseaddr, getaddresses, parsedate_to_datetime

P = json.loads(base64.b64decode("__BOUNDARY_PARAMS__").decode("utf-8"))
A = P.get("account") or {}
MAX_BODY = int(P.get("max_body") or 4000)
socket.setdefaulttimeout(20)
imaplib.Commands.setdefault("ID", ("NONAUTH", "AUTH", "SELECTED"))

# Fallback names when a server doesn't flag its special folders.
# "&XfJT0ZAB-" is 已发送 and "&g0l6P3ux-" is 草稿箱 in IMAP's modified UTF-7 (NetEase).
SENT_NAMES = ["Sent Messages", "Sent", "Sent Items", "Sent Mail", "[Gmail]/Sent Mail", "&XfJT0ZAB-"]
DRAFT_NAMES = ["Drafts", "Draft", "[Gmail]/Drafts", "&g0l6P3ux-", "&g0l6Pw-"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


class Fail(Exception):
    pass


# ── small helpers ────────────────────────────────────────────────────────

def emit(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=True))
    sys.stdout.flush()


def q(s):
    """Quote a string for an IMAP command (folder names, search values)."""
    s = str(s)
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def clean(s):
    """Strip characters that could break out of an IMAP search value."""
    return re.sub(r'[\\"\r\n\x00]', "", str(s or "")).strip()


def norm_id(mid):
    mid = clean(mid)
    if mid and not mid.startswith("<"):
        mid = "<" + mid
    if mid and not mid.endswith(">"):
        mid = mid + ">"
    return mid


def imap_date(yyyy_mm_dd):
    d = datetime.strptime(str(yyyy_mm_dd)[:10], "%Y-%m-%d")
    return "%02d-%s-%d" % (d.day, MONTHS[d.month - 1], d.year)


def addresses(value):
    """'a@x.com; Bob <b@y.com>' -> ['a@x.com', 'b@y.com'] (validated)."""
    if not value:
        return []
    if isinstance(value, list):
        value = ",".join(str(v) for v in value)
    value = str(value).replace(";", ",").replace("\r", " ").replace("\n", " ")
    found = [addr for _, addr in getaddresses([value]) if addr]
    for addr in found:
        if "@" not in addr or " " in addr:
            raise Fail("Not a valid email address: %s" % addr)
    return found


def own_address():
    return (A.get("address") or "").lower()


# ── IMAP connection and folders ──────────────────────────────────────────

def connect():
    host = A.get("imap_host")
    if not host:
        raise Fail("No IMAP server configured for %s" % A.get("address"))
    try:
        M = imaplib.IMAP4_SSL(host, int(A.get("imap_port") or 993))
    except Exception as e:
        raise Fail("Could not reach %s: %s" % (host, e))
    try:
        M.login(A["address"], A["auth_code"])
    except imaplib.IMAP4.error as e:
        raise Fail(
            "Login refused by %s (%s). Check that IMAP/SMTP is switched on in the "
            "mailbox's settings, and that the authorization code was entered, not "
            "the account password." % (host, e)
        )
    # NetEase (163/126) rejects mailbox access from clients that don't say who
    # they are. Other servers accept or ignore this, so it is always sent.
    try:
        M._simple_command("ID", '("name" "Boundary" "version" "4.0" "vendor" "Xuanwo AI")')
    except Exception:
        pass
    return M


def list_folders(M):
    typ, data = M.list()
    result = []
    for line in data or []:
        if not isinstance(line, bytes):
            continue
        m = re.match(rb'\((?P<f>[^)]*)\)\s+(?:"(?:[^"\\]|\\.)*"|NIL)\s+(?P<n>.+)$', line)
        if m:
            result.append((m.group("f").decode("utf-8", "ignore"),
                           m.group("n").decode("utf-8", "ignore").strip()))
    return result


def find_folder(M, flag, names):
    folders = list_folders(M)
    for flags, name in folders:
        if flag.lower() in flags.lower():
            return q(name)
    by_bare_name = {name.strip('"').lower(): name for _, name in folders}
    for candidate in names:
        if candidate.lower() in by_bare_name:
            return q(by_bare_name[candidate.lower()])
    raise Fail("Could not find the %s folder. Folders on this account: %s"
               % (flag.strip("\\"), ", ".join(n for _, n in folders)))


def select(M, folder, readonly=True):
    typ, data = M.select(folder, readonly=readonly)
    if typ != "OK":
        raise Fail("Could not open folder %s: %s" % (folder, data))


def search(M, *criteria):
    try:
        typ, data = M.uid("SEARCH", *criteria)
    except Exception:
        return []
    if typ != "OK" or not data or not data[0]:
        return []
    return data[0].decode("ascii", "ignore").split()


# ── reading messages ─────────────────────────────────────────────────────

def body_text(msg):
    text = None
    try:
        part = msg.get_body(preferencelist=("plain", "html"))
        if part is not None:
            text = part.get_content()
            if part.get_content_type() == "text/html":
                text = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", text)
                text = re.sub(r"(?i)<br\s*/?>|</p>|</div>", "\n", text)
                text = re.sub(r"(?s)<[^>]+>", " ", text)
                text = text.replace("&nbsp;", " ").replace("&amp;", "&") \
                           .replace("&lt;", "<").replace("&gt;", ">")
    except Exception:
        text = None
    if text is None:
        try:
            raw = msg.get_payload(decode=True) or b""
            text = raw.decode(msg.get_content_charset() or "utf-8", "replace")
        except Exception:
            text = ""
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def header(msg, name):
    try:
        value = msg.get(name)
        return str(value).strip() if value is not None else ""
    except Exception:
        try:
            return str(msg.get_all(name, [""])[0]).strip()
        except Exception:
            return ""


def record(raw, seen, folder_label, max_body=None):
    msg = message_from_bytes(raw, policy=policy.default)
    limit = max_body or MAX_BODY
    sender_name, sender_addr = parseaddr(header(msg, "From"))
    try:
        dt = parsedate_to_datetime(header(msg, "Date"))
        if dt.tzinfo is not None:
            dt = dt.astimezone()
        iso, short = dt.strftime("%Y-%m-%dT%H:%M:%S"), dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        iso, short = "", ""
    body = body_text(msg)
    attachments = []
    try:
        for part in msg.iter_attachments():
            if part.get_filename():
                attachments.append(part.get_filename())
    except Exception:
        pass
    return {
        "MessageID": header(msg, "Message-ID"),
        "InReplyTo": header(msg, "In-Reply-To"),
        "References": " ".join(header(msg, "References").split()),
        "Subject": header(msg, "Subject"),
        "From": sender_name or sender_addr,
        "SenderEmail": sender_addr,
        "To": header(msg, "To"),
        "Cc": header(msg, "Cc"),
        "ReplyTo": header(msg, "Reply-To"),
        "Date": iso,
        "ReceivedTime": short,
        "Body": body[:limit],
        "BodyTruncated": len(body) > limit,
        "Unread": not seen,
        "HasAttachments": bool(attachments),
        "Attachments": attachments,
        "Folder": folder_label,
    }


def fetch(M, uids, folder_label, max_body=None):
    if not uids:
        return []
    typ, data = M.uid("FETCH", ",".join(uids), "(FLAGS BODY.PEEK[])")
    records = []
    for item in data or []:
        if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], bytes):
            meta = item[0].decode("ascii", "ignore") if isinstance(item[0], bytes) else str(item[0])
            records.append(record(item[1], "\\Seen" in meta, folder_label, max_body))
    return records


def scan_for_id(M, mid, window=300):
    """Fallback for servers whose HEADER search is unreliable (QQ):
    read the Message-ID header of the last `window` messages and compare."""
    uids = search(M, "ALL")[-window:]
    if not uids:
        return []
    typ, data = M.uid("FETCH", ",".join(uids), "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])")
    hits = []
    for item in data or []:
        if isinstance(item, tuple) and len(item) >= 2:
            meta = item[0].decode("ascii", "ignore")
            m = re.search(r"UID (\d+)", meta)
            if m and mid.lower() in item[1].decode("utf-8", "ignore").lower():
                hits.append(m.group(1))
    return hits


def find_by_id(M, mid):
    """Look for one Message-ID in the inbox, then in Sent."""
    mid = norm_id(mid)
    if not mid:
        raise Fail("No Message-ID was given.")
    places = [('"INBOX"', "Inbox")]
    try:
        places.append((find_folder(M, "\\Sent", SENT_NAMES), "Sent"))
    except Fail:
        pass
    for folder, label in places:
        select(M, folder)
        uids = search(M, "HEADER", "Message-ID", q(mid)) or scan_for_id(M, mid)
        if uids:
            return folder, label, uids[-1]
    return None, None, None


# ── actions ──────────────────────────────────────────────────────────────

def act_read(M):
    folder_kind = (P.get("folder") or "inbox").lower()
    if folder_kind == "sent":
        folder, label = find_folder(M, "\\Sent", SENT_NAMES), "Sent"
    else:
        folder, label = '"INBOX"', "Inbox"
    select(M, folder)

    criteria = []
    if P.get("unread"):
        criteria.append("UNSEEN")
    if P.get("since"):
        criteria += ["SINCE", imap_date(P["since"])]
    if P.get("sender"):
        criteria += ["TO" if label == "Sent" else "FROM", q(clean(P["sender"]))]
    if not criteria:
        criteria = ["ALL"]

    count = max(1, min(int(P.get("count") or 5), 50))
    uids = sorted(search(M, *criteria), key=int)[-count:]
    emails = fetch(M, uids, label)
    emails.sort(key=lambda r: r["Date"], reverse=True)
    return {"emails": emails, "folder": label}


def act_get(M):
    folder, label, uid = find_by_id(M, P.get("message_id"))
    if not uid:
        return {"emails": [], "found": False}
    select(M, folder)
    return {"emails": fetch(M, [uid], label, max_body=int(P.get("max_body") or 20000)), "found": True}


def act_thread(M):
    """Bounded search behind NOT_SUPERSEDED: the thread of one message, plus
    mail exchanged with its participants since a date."""
    mid = norm_id(P.get("message_id"))
    since = P.get("since")
    participants = [clean(p).lower() for p in (P.get("participants") or []) if clean(p)]
    limit = max(1, min(int(P.get("limit") or 30), 60))

    if mid and not participants:
        folder, label, uid = find_by_id(M, mid)
        if uid:
            select(M, folder)
            original = fetch(M, [uid], label)
            if original:
                o = original[0]
                people = addresses(o["SenderEmail"]) + addresses(o["To"]) + addresses(o["Cc"])
                participants = sorted({p.lower() for p in people if p.lower() != own_address()})
                if not since and o["Date"]:
                    since = o["Date"][:10]

    places = [('"INBOX"', "Inbox", "FROM")]
    try:
        places.append((find_folder(M, "\\Sent", SENT_NAMES), "Sent", "TO"))
    except Fail:
        pass

    found = {}
    for folder, label, field in places:
        select(M, folder)
        uids = set()
        if mid:
            for name in ("Message-ID", "In-Reply-To", "References"):
                uids.update(search(M, "HEADER", name, q(mid)))
        for person in participants:
            criteria = [field, q(person)]
            if since:
                criteria = ["SINCE", imap_date(since)] + criteria
            uids.update(search(M, *criteria))
        for r in fetch(M, sorted(uids, key=int)[-limit:], label):
            found[r["MessageID"] or "%s-%s" % (label, len(found))] = r

    emails = sorted(found.values(), key=lambda r: r["Date"])
    return {"emails": emails[-limit:], "participants": participants, "since": since or ""}


def build_message(M):
    msg = EmailMessage()
    display = A.get("display_name") or ""
    msg["From"] = formataddr((display, A["address"])) if display else A["address"]

    to = addresses(P.get("to"))
    cc = addresses(P.get("cc"))
    subject = str(P.get("subject") or "").replace("\r", " ").replace("\n", " ")
    reply_id = norm_id(P.get("reply_to_message_id"))

    if reply_id:
        folder, label, uid = find_by_id(M, reply_id)
        if not uid:
            raise Fail("Could not find the email being replied to (%s)." % reply_id)
        select(M, folder)
        original = fetch(M, [uid], label)[0]
        if not to:
            to = addresses(original["ReplyTo"] or original["SenderEmail"])
        if not subject:
            subject = original["Subject"]
        if not re.match(r"(?i)^\s*(re|回复|答复)\s*[:：]", subject):
            subject = "Re: " + subject
        msg["In-Reply-To"] = original["MessageID"]
        msg["References"] = " ".join(x for x in (original["References"], original["MessageID"]) if x)

    if not to:
        raise Fail("No recipient was given.")
    msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=A["address"].split("@")[-1])
    msg.set_content(str(P.get("body") or ""))

    for path in P.get("attachments") or []:
        full = os.path.expandvars(os.path.expanduser(str(path)))
        if not os.path.isfile(full):
            raise Fail("Attachment not found: %s" % full)
        ctype, _ = mimetypes.guess_type(full)
        maintype, subtype = (ctype or "application/octet-stream").split("/", 1)
        with open(full, "rb") as f:
            msg.add_attachment(f.read(), maintype=maintype, subtype=subtype,
                               filename=os.path.basename(full))
    return msg


def smtp_send(msg):
    host = A.get("smtp_host")
    port = int(A.get("smtp_port") or 465)
    if not host:
        raise Fail("No SMTP server configured for %s" % A.get("address"))
    try:
        if port == 465:
            server = smtplib.SMTP_SSL(host, port)
        else:
            server = smtplib.SMTP(host, port)
            server.starttls()
        server.login(A["address"], A["auth_code"])
        refused = server.send_message(msg)
    except smtplib.SMTPAuthenticationError as e:
        raise Fail("Sending refused by %s (%s). Check the authorization code." % (host, e))
    except smtplib.SMTPRecipientsRefused as e:
        raise Fail("Every recipient was refused: %s" % ", ".join(e.recipients))
    except (smtplib.SMTPException, OSError) as e:
        raise Fail("Sending failed at %s: %s" % (host, e))
    try:
        server.quit()
    except Exception:
        pass  # QQ sometimes answers QUIT with garbage after a successful send
    return list(refused.keys()) if refused else []


def in_folder(M, folder, mid):
    select(M, folder)
    return bool(search(M, "HEADER", "Message-ID", q(mid)) or scan_for_id(M, mid, window=30))


def act_send(M):
    msg = build_message(M)
    refused = smtp_send(msg)
    mid = msg["Message-ID"]

    # The Sent folder is V4's proof of what was sent. Some providers file SMTP
    # sends there themselves (Gmail); others don't. Check, and file it if not.
    sent_folder = find_folder(M, "\\Sent", SENT_NAMES)
    saved = "provider"
    found = False
    for _ in range(3):
        if in_folder(M, sent_folder, mid):
            found = True
            break
        time.sleep(1.5)
    if not found:
        typ, data = M.append(sent_folder, "(\\Seen)", imaplib.Time2Internaldate(time.time()),
                             msg.as_bytes(policy=policy.SMTP))
        if typ != "OK":
            raise Fail("Sent, but could not save a copy to %s: %s" % (sent_folder, data))
        saved = "appended"
    return {"status": "sent", "MessageID": mid, "To": msg["To"], "Cc": msg["Cc"] or "",
            "Subject": msg["Subject"], "SentCopy": saved, "Refused": refused}


def act_draft(M):
    msg = build_message(M)
    drafts = find_folder(M, "\\Drafts", DRAFT_NAMES)
    typ, data = M.append(drafts, "(\\Draft \\Seen)", imaplib.Time2Internaldate(time.time()),
                         msg.as_bytes(policy=policy.SMTP))
    if typ != "OK":
        raise Fail("Could not save the draft to %s: %s" % (drafts, data))
    return {"status": "draft_saved", "MessageID": msg["Message-ID"], "To": msg["To"],
            "Cc": msg["Cc"] or "", "Subject": msg["Subject"]}


def act_folders(M):
    return {"folders": [{"flags": f, "name": n} for f, n in list_folders(M)]}


ACTIONS = {"read": act_read, "get": act_get, "thread": act_thread,
           "send": act_send, "draft": act_draft, "folders": act_folders}


def main():
    M = None
    try:
        action = ACTIONS.get(P.get("action"))
        if action is None:
            raise Fail("Unknown mail action: %s" % P.get("action"))
        M = connect()
        result = action(M)
        result["ok"] = True
        result["account"] = A.get("address")
        emit(result)
    except Fail as e:
        emit({"ok": False, "error": str(e)})
    except Exception as e:
        emit({"ok": False, "error": "%s: %s" % (type(e).__name__, e)})
    finally:
        if M is not None:
            try:
                M.logout()
            except Exception:
                pass


if __name__ == "__main__":
    main()