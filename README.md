# Close the Loop

[中文说明](README.zh-CN.md)

**AI agents that can keep working without a human, because they check their own memory against reality.**

Close the Loop is an open-source agent system from Xuanwo AI. Its agents set their own wake-up times, keep a written record of what they believe they owe and why, and have a separate agent check those beliefs against the real world before acting on them. Everything runs on your own computer, with your own model keys and your own mailbox.

---

## The problem

Today's agents still need a human to keep them on track. When an agent works on its own for a long time, the notes it leaves for itself drift away from reality. It "remembers" sending an email it never sent, or a meeting that has since been cancelled, and then it acts on those false beliefs. Better memory doesn't fix this, because a memory store records a false belief just as faithfully as a true one.

So every agent product keeps a human in the loop. Agents can be triggered on a schedule, but they can't be trusted to direct their own work.

## The idea

Close the Loop adds three agents, each owning one question:

- **The scheduler owns *when*.** An agent can set its own wake-up. At the chosen time it wakes with the message it left itself and carries on, as if you had typed it. Wake-ups are registered in Windows Task Scheduler, so they fire even if the app was closed, and a wake-up missed while the computer slept fires late rather than never.
- **The ledger owns *what* and *why*.** It writes directives: concrete future actions, each resting on exact evidence such as a Message-ID or a file path. The ledger is a folder of dated, append-only files on your computer, so the record survives the chat.
- **The auditor owns *whether it is still true*.** Before anything acts on a directive, the auditor checks it against records that exist outside the agents' own notes, such as your Sent folder, your inbox and files on disk. It returns one verdict per directive: confirmed, stale, contradicted or unverifiable. The ledger applies the verdict, closing what turned out to be false.

Notes are never evidence for themselves. A "confirmed" verdict with no evidence attached is recorded as "unverifiable", and directives an agent writes for itself start with reversible-only authority: it may draft, never send.

## The proof: a planted false belief

We told the system that two emails had been sent: one titled "Scheduler test", which really had been sent, and one titled "Q4 budget figures", which had not.

The ledger recorded both without judgement. The auditor searched the real Gmail Sent folder, widening its search window three times, confirmed the first email by its Message-ID, and found no trace of the second. The ledger then closed the false directive. A false belief went into the record, was checked against reality, and came out.

Halfway through, the page was accidentally refreshed. When the test was rerun, the ledger found its directives and the auditor's verdicts already on disk and carried on without duplicating anything. The record lives on the machine, not in the chat.

## How it works

Boundary's agent loop runs on a local server. A Summarizer reads the request, a Planner chooses the next executor, the executor does one job, and the loop repeats until the task is done. Independent work can run as parallel sub-agents.

The scheduler, auditor and ledger are ordinary executors to the Planner. Inside, the auditor and ledger each run their own loop beneath the main Planner, dispatching other executors and sub-agents to gather evidence before they finish.

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

- This is an early research release. One clean run proves the idea works; open testing on many machines and messy inboxes is how we'll learn how well it works and where it bends.
- Scheduling is Windows-only for now.
- The bridge runs the commands your local agents send it, on your computer. Run it only on a machine you trust, with a `BRIDGE_TOKEN` nobody else knows.
- The calendar can't be read yet, so the auditor can only check meetings through their email threads.

## Where this is going

Email is the first proving ground. The same problem, agents acting on beliefs nobody has checked, stands between today's AI and machines that work in the physical world. Close the Loop is our path from agents in your inbox to agents on robots, improving their own work with no human in the loop.

## Contributing

Issues and pull requests are welcome. If Close the Loop breaks on your machine or your mailbox, that is exactly what we want to hear about.

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
