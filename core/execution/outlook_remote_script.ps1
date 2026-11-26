# core/execution/outlook_remote_script.ps1
#
# NOT run on the server. mail_client.py reads this as text and sends it to the
# user's machine for Microsoft accounts (Outlook.com / Microsoft 365), which
# block password logins over IMAP. It drives classic Outlook through COM.
#
# $P (the parameters) is defined before this script runs, decoded from
# base64 JSON, so no value from an LLM is ever pasted into the code.
# Output: one line, base64 of UTF-8 JSON.

$ErrorActionPreference = 'Stop'
$PR_MESSAGE_ID  = 'http://schemas.microsoft.com/mapi/proptag/0x1035001F'
$PR_IN_REPLY_TO = 'http://schemas.microsoft.com/mapi/proptag/0x1042001F'
$PR_REFERENCES  = 'http://schemas.microsoft.com/mapi/proptag/0x1039001F'
$max = 4000
if ($P.max_body) { $max = [int]$P.max_body }

function Emit($obj) {
    $json = $obj | ConvertTo-Json -Depth 6 -Compress
    [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($json))
}

function Prop($item, $tag) {
    try { return [string]$item.PropertyAccessor.GetProperty($tag) } catch { return '' }
}

function SenderAddress($m) {
    try {
        if ($m.SenderEmailType -eq 'EX') {
            $u = $m.Sender.GetExchangeUser()
            if ($u) { return [string]$u.PrimarySmtpAddress }
        }
    } catch {}
    return [string]$m.SenderEmailAddress
}

function Rec($m, $label) {
    $body = [string]$m.Body
    $truncated = $false
    if ($body.Length -gt $max) { $body = $body.Substring(0, $max); $truncated = $true }
    $atts = @()
    foreach ($a in $m.Attachments) { $atts += [string]$a.FileName }
    $t = $m.ReceivedTime
    if ($label -eq 'Sent') { $t = $m.SentOn }
    return [ordered]@{
        MessageID      = (Prop $m $PR_MESSAGE_ID)
        InReplyTo      = (Prop $m $PR_IN_REPLY_TO)
        References     = (Prop $m $PR_REFERENCES)
        Subject        = [string]$m.Subject
        From           = [string]$m.SenderName
        SenderEmail    = (SenderAddress $m)
        To             = [string]$m.To
        Cc             = [string]$m.CC
        ReplyTo        = ''
        Date           = $t.ToString('yyyy-MM-ddTHH:mm:ss')
        ReceivedTime   = $t.ToString('yyyy-MM-dd HH:mm')
        Body           = $body
        BodyTruncated  = $truncated
        Unread         = [bool]$m.UnRead
        HasAttachments = ($atts.Count -gt 0)
        Attachments    = $atts
        Folder         = $label
        EntryID        = [string]$m.EntryID
    }
}

try {
    $outlook = New-Object -ComObject Outlook.Application
    $ns = $outlook.GetNamespace('MAPI')

    # The account must match exactly. No silent fallback to the default account.
    $want = ([string]$P.account.address).ToLower()
    $account = $null
    $seen = @()
    foreach ($a in $ns.Accounts) {
        $seen += [string]$a.SmtpAddress
        if (([string]$a.SmtpAddress).ToLower() -eq $want) { $account = $a }
    }
    if (-not $account) {
        throw ("Classic Outlook has no account for " + $P.account.address + ". Accounts found: " + ($seen -join ', '))
    }
    $store = $account.DeliveryStore

    function FindById($id) {
        $id = [string]$id
        if (-not $id.StartsWith('<')) { $id = '<' + $id + '>' }
        $escaped = $id.Replace("'", "''")
        foreach ($pair in @(@(6, 'Inbox'), @(5, 'Sent'))) {
            $folder = $store.GetDefaultFolder($pair[0])
            $hits = $folder.Items.Restrict("@SQL=""$PR_MESSAGE_ID"" = '$escaped'")
            if ($hits.Count -gt 0) { return @($hits.Item(1), $pair[1]) }
        }
        return $null
    }

    $result = $null
    switch ([string]$P.action) {

        'read' {
            $fid = 6; $label = 'Inbox'; $timeField = '[ReceivedTime]'
            if ([string]$P.folder -eq 'sent') { $fid = 5; $label = 'Sent'; $timeField = '[SentOn]' }
            $items = $store.GetDefaultFolder($fid).Items
            $items.Sort($timeField, $true)
            $filters = @()
            if ($P.unread) { $filters += '[UnRead] = True' }
            if ($P.since) {
                $d = [datetime]::ParseExact([string]$P.since, 'yyyy-MM-dd', $null)
                $filters += ($timeField + " >= '" + $d.ToString('g') + "'")
            }
            if ($filters.Count -gt 0) { $items = $items.Restrict($filters -join ' AND ') }
            $sender = ([string]$P.sender).ToLower()
            $count = 5
            if ($P.count) { $count = [Math]::Min([int]$P.count, 50) }
            $emails = @(); $scanned = 0
            foreach ($m in $items) {
                $scanned++
                if ($scanned -gt 500) { break }
                if ($m.Class -ne 43) { continue }   # mail items only
                if ($sender) {
                    $who = if ($label -eq 'Sent') { ([string]$m.To).ToLower() } else { (SenderAddress $m).ToLower() }
                    if (-not $who.Contains($sender)) { continue }
                }
                $emails += (Rec $m $label)
                if ($emails.Count -ge $count) { break }
            }
            $result = [ordered]@{ ok = $true; emails = $emails; folder = $label }
        }

        'get' {
            $hit = FindById $P.message_id
            if ($hit) {
                $max = 20000
                $result = [ordered]@{ ok = $true; found = $true; emails = @((Rec $hit[0] $hit[1])) }
            } else {
                $result = [ordered]@{ ok = $true; found = $false; emails = @() }
            }
        }

        { $_ -in @('send', 'draft') } {
            if ($P.reply_to_message_id) {
                $hit = FindById $P.reply_to_message_id
                if (-not $hit) { throw ("Could not find the email being replied to (" + $P.reply_to_message_id + ").") }
                $mail = $hit[0].Reply()
                $mail.Body = [string]$P.body + "`r`n`r`n" + $mail.Body
                if ($P.to) { $mail.To = [string]$P.to }
            } else {
                if (-not $P.to) { throw 'No recipient was given.' }
                $mail = $outlook.CreateItem(0)
                $mail.To = [string]$P.to
                $mail.Subject = [string]$P.subject
                $mail.Body = [string]$P.body
            }
            if ($P.cc) { $mail.CC = [string]$P.cc }
            $mail.SendUsingAccount = $account
            foreach ($path in @($P.attachments)) {
                if (-not $path) { continue }
                $full = [Environment]::ExpandEnvironmentVariables([string]$path)
                if ($full.StartsWith('~')) { $full = $HOME + $full.Substring(1) }
                if (-not (Test-Path -LiteralPath $full)) { throw ("Attachment not found: " + $full) }
                [void]$mail.Attachments.Add($full)
            }
            $to = [string]$mail.To; $subject = [string]$mail.Subject
            if ([string]$P.action -eq 'send') {
                $mail.Send()
                # Outlook assigns the Message-ID during sending; the copy in
                # Sent Items carries it once Outlook has synced.
                $result = [ordered]@{ ok = $true; status = 'sent'; MessageID = ''; To = $to; Subject = $subject; SentCopy = 'provider' }
            } else {
                $mail.Save()
                $result = [ordered]@{ ok = $true; status = 'draft_saved'; MessageID = ''; EntryID = [string]$mail.EntryID; To = $to; Subject = $subject }
            }
        }

        default {
            throw ("'" + $P.action + "' is not available for Outlook accounts yet. Use an IMAP account (QQ, 163, Gmail) for this.")
        }
    }
    $result['account'] = [string]$P.account.address
    Emit $result
} catch {
    Emit ([ordered]@{ ok = $false; error = $_.Exception.Message })
}