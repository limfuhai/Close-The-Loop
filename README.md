# Close the Loop

[中文说明](README.zh-CN.md)

**AI agents that can keep working without a human, because they check their own memory against reality.**

Close the Loop is an open-source agent system from Xuanwo Huanliu （漩涡环流）. Its agents set their own wake-up times, keep a written record of what they believe they owe and why, and have a separate agent check those beliefs against the real world before acting on them. Everything runs on your own computer, with your own model keys and your own mailbox.

---

## The problem

Today's agents still need a human to keep them on track. When an agent works on its own for a long time, the notes it leaves for itself drift away from reality. This problem of "agentic degradation" is a well-known one, and today's agents appear to need better memory implementations.

Close The Loop's premise is that the agentic degradation problem is not a memory problem. Agents degrade not because of imperfect memory, but because a perfect memory cannot perfectly deal with an everchanging outside world. What agents are lacking is verification of what's real and what isn't, whether the context has changed, what has changed about the plan, etc. 

## The idea

Close the Loop adds a trifecta of agentic capabilities to regular local agents:
1. The scheduler agent sets its own wake-up, and Windows wakes it with the message it left itself, even if the app was closed. This enables continuous, around-the-clock checking for mailbox activity amongst the agents. You can use the scheduler to have the other agents regularly check into your mailbox throughout a working day.
2. The ledger agent records every single piece of evidence in a diary-like format. It also takes the findings of the auditor and records that down too, allowing the removal of incorrect beliefs or records that may previously exist within the ledger.
3. The auditor agent is activated before anything acts. It checks each entry against records outside the agents' own notes (your Sent folder, your inbox, your files) and returns confirmed, stale, contradicted or unverifiable.

## How it works

Anything that touches your computer goes through the **bridge**, a small Python script with no dependencies that you run in a terminal. Email is read and sent directly over IMAP and SMTP from your machine, so any provider with an app password works.

Everything Close the Loop keeps lives in one folder in your home directory:

| Path | What it holds |
|---|---|
| `~/Boundary/ledger/` | Dated, append-only directive and verdict files, plus `LIVE.md`, the current index |
| `~/Boundary/wake/` | Pending wake-ups and the runner Task Scheduler calls |
| `~/Boundary/chats/messages.jsonl` | Saved chat replies, including those from scheduled wake-ups |

## Getting started

### Requirements

- Windows 10 or 11 (the scheduler uses Windows Task Scheduler)
- Python 3.10 or later
- Node.js 18 or later
- An API key for DeepSeek, Moonshot (Kimi), or both
- An email account with an app password or authorization code (Gmail, QQ Mail, 163 and others)

### 1. Get the code

```
git clone https://github.com/limfuhai/close-the-loop.git
cd close-the-loop
pip install -r requirements.txt
npm install
```

### 2. Add your model keys

Open `core/api_client.py` and put your keys in `deepseek_api_key` and `moonshot_api_key` near the top. You can fill in one or both: models without a key are skipped.

### 3. Create your settings files

Copy `.env.example` to `.env` and `.env.local.example` to `.env.local`, then fill in `.env`:

- `BRIDGE_TOKEN`: any long random string. It's the secret shared by your server and your bridge. Make one with:
  ```
  python -c "import secrets;print(secrets.token_urlsafe(32))"
  ```
- `MAIL_ADDRESS` and `MAIL_AUTH_CODE`: the email account your agents use. Mail providers don't let apps sign in with your normal password, so use an app password instead:
  - **Gmail:** turn on 2-Step Verification, then create one under Google Account → Security → App passwords.
  - **QQ Mail:** in QQ Mail's settings, turn on the IMAP/SMTP service and generate an authorization code (授权码).

The provider is worked out from your address. For a custom mail server, also set `MAIL_IMAP_HOST`, `MAIL_IMAP_PORT`, `MAIL_SMTP_HOST` and `MAIL_SMTP_PORT`.

### 4. Start it

In one terminal:
```
python core/compiler.py
```
In a second terminal:
```
npm run dev
```
Then open http://localhost:3000.

### 5. Connect the bridge

Click **Download Bridge**. In a third terminal, go to where it was saved and run:
```
python bridge.py
```
Keep that window open while you use Close the Loop.

### 6. Try it

Create an agent and ask it:

> In 3 minutes, send an email to *your own address* with the subject "Scheduler test", saying hello from your scheduled future self. For now, just set the wake-up and nothing else.

Three minutes later, Windows wakes the agent, and it sends the email with only the message its past self left behind.

Then try the planted error. Tell the ledger about one email you really sent and one you never sent, and ask the auditor to check both against your Sent folder. Watch the false one get closed in `~/Boundary/ledger/`.

## Limits

- This is an early research release, with very limited testing to prove capabilities.
- Scheduling is Windows-only for now.
- The bridge runs the commands your local agents send it, on your computer. Run it only on a machine you trust, with a `BRIDGE_TOKEN` nobody else knows.
- The calendar can't be read yet, so the auditor can only check meetings through their email threads.
- There is a known problem with the DocsExecutor, an agent that produces Word documents, being called up instead of the auditor. If the agents are stuck here, please request them to try again to call up the auditor, a retry usually fixes it.

## Contributing

Issues and pull requests are welcome. If Close the Loop breaks on your machine or your mailbox, that is exactly what we want to hear about.

## Paid Version

**Don't want to run it yourself?** Close the Loop also runs as a hosted app, Boundary, at https://boundary.xuanwo.ai: no setup, no model keys and no server to keep running, on paid plans. You still run the small bridge on your own computer. Note that users may register for free, but free users have zero tokens. Please sign up with a payment plan to receive tokens and run the app.

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
