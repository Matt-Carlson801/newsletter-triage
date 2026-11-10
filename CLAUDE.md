# CLAUDE.md: newsletter-digest

Read this file fully before doing anything. It is the source of truth for what we are building, why, and how to work with me.

## 1. Who I am and how to work with me

- I am a GTM / RevOps professional, not a developer. I am **learning Python** through this project.
- This is a **public portfolio project**. It will be linked from my personal website to help me get a job or build my own business. Code quality, a clear README, and a clean commit history matter as much as functionality.
- **Teach as you build.** After writing or changing any file, explain in plain English what it does and why, function by function. Define any new Python concept the first time it appears.
- **Keep code simple.** Prefer readable over clever. Standard library first. Add a dependency only when it clearly earns its place, and tell me why.
- **Comment the code** so a beginner can follow it: what each section does and why, not just what.
- **Build one stage at a time** (see section 6). Do not build ahead. At the end of each stage, stop and summarize what was built, how to run it, and what I should try.
- If a decision could reasonably go two ways, give me one recommendation with a one-sentence reason, then proceed unless I object.
- Make small, logical commits with clear messages. Never commit secrets (see section 8).

## 2. What this project is

A tool that reads newsletters from my Gmail, summarizes each one, and sends me a single **daily TLDR email** with a link to read each piece in full. It also keeps data on which subscriptions I actually read so I can unsubscribe from the rest.

## 3. The problem it solves (the "why")

Newsletters pile up unread, so I pay the cost of subscribing (inbox clutter, guilt) without getting the value. The useful 10% is buried under the other 90%.

Target outcomes, and the metrics for the portfolio case study:
1. **Inbox zero:** newsletters skip the inbox entirely (Gmail filter), and the only newsletter-related email in my inbox is the one daily digest. Metric: newsletter emails hitting the inbox per day, before vs. after.
2. **Time saved:** a 3-minute scan replaces 30 minutes of triage. Metric: estimated minutes per day, before vs. after.
3. **Subscription audit:** the system shows which senders I never engage with and makes unsubscribing one click. Metric: subscriptions cut, based on actual reading behavior.

This is framed as a workflow case study: **input** (raw emails) -> **automation** (filter, extract, summarize) -> **output** (daily digest) -> **result** (metrics above).

## 4. How it works (the "what" and "where")

1. A Gmail filter labels incoming newsletters with `Newsletters` and applies **Skip the Inbox**. This is configured by hand in Gmail, not in code.
2. The Python script connects to Gmail over **IMAP**, reads emails in the `Newsletters` label from the last 24 hours, and extracts: sender, subject, date, plain-text body, links, and the `List-Unsubscribe` header if present.
3. It logs sender + date for every newsletter to a CSV (for the future subscription audit).
4. It sends each newsletter's text to the **Gemini API (free tier)** with a prompt asking for a 2-sentence summary. The original link is always preserved.
5. It assembles one digest email (HTML + plain-text fallback) and sends it to me via SMTP.
6. A **GitHub Actions** cron workflow runs the whole thing every morning (target: 6:00 AM America/New_York).

## 5. Tech stack and constraints (the "how")

- **Language:** Python 3.11+.
- **Email in:** `imaplib` + `email` (standard library). **Email out:** `smtplib` (standard library).
- **Summaries:** Gemini API free tier via the official `google-genai` package. Check current docs for the model name and free-tier limits, and keep the model name in one config constant so it is easy to swap. Design the summarizer behind a single function (`summarize(text) -> str`) so the provider can later be swapped for the Anthropic API without touching the rest of the code.
- **Config/secrets:** `python-dotenv` locally (`.env`), GitHub Secrets in Actions.
- **Cost:** **$0.** No paid services, no servers. If something would cost money, stop and tell me.
- **Hosting:** GitHub Actions only. No always-on server.
- Keep the dependency list short and pinned in `requirements.txt`.

## 6. Build stages (build ONLY the stage I ask for)

**Stage 1: Read and print.** Connect to Gmail over IMAP, fetch last-24-hour emails in the `Newsletters` label, and print sender, subject, date, and extracted links. Also append sender + date to `data/newsletter_log.csv` and capture the `List-Unsubscribe` header if present. No AI, no sending email.

**Stage 2: Summarize.** Add the Gemini summarizer. Print summaries alongside links.

**Stage 3: Send the digest.** Build the HTML + plain-text digest and email it to me via SMTP.

**Stage 4: Automate.** Add `.github/workflows/daily-digest.yml` with a cron schedule and a manual-run trigger. Document the required secrets.

**Stage 5: Subscription audit.** Monthly report section: per-sender counts, engagement, and a one-click unsubscribe link from `List-Unsubscribe`. Engagement tracking approach to be decided together at this stage. Do not design it earlier.

**Stage 6: Portfolio polish.** README case study, demo mode with sample data, a workflow diagram, and a GitHub Pages page.

Each stage should leave the project in a working, committable state.

## 7. Project structure

```
newsletter-digest/
├── CLAUDE.md              # this file
├── README.md              # case-study style (see section 10)
├── requirements.txt
├── .env.example           # placeholder values only
├── .gitignore
├── src/
│   ├── main.py            # entry point: runs the whole pipeline
│   ├── config.py          # loads settings from environment
│   ├── fetch.py           # IMAP: read and parse newsletters
│   ├── summarize.py       # summarizer (provider-swappable)
│   ├── digest.py          # builds the digest email
│   └── send.py            # SMTP sending
├── data/
│   └── newsletter_log.csv # sender + date log (gitignored; see section 8)
├── demo/
│   └── sample_newsletters/ # fake or public sample content for demo mode
└── .github/workflows/
    └── daily-digest.yml
```

Create files only as each stage needs them. Do not scaffold empty files for future stages.

## 8. Security and privacy rules (non-negotiable)

- **Never commit secrets.** Gmail app password, Gemini API key, and email addresses live only in `.env` (local, gitignored) and GitHub Secrets (Actions). Provide `.env.example` with placeholders.
- **Never commit real email content.** `data/` and any real digest output must be gitignored. The repo is public.
- **Demo content must come from fake or clearly public sample newsletters**, never my real inbox.
- **Use a Gmail App Password**, not my real password. Document how to create one in the README.
- Before every commit, check `git status` and `git diff --staged` for anything sensitive.
- Never log full email bodies or credentials to the console or to Actions logs.
- Respect copyright: digests contain short summaries and links, not reproductions of full newsletter text.

## 9. Code conventions

- Small functions that each do one thing, with clear names and docstrings.
- Type hints on function signatures (explain them to me the first time).
- Handle failure explicitly: if IMAP login fails, Gemini errors, or no newsletters are found, print a clear human-readable message and exit cleanly. Never crash with a raw traceback for expected problems.
- No global mutable state. Pass data between functions as arguments.
- Add a basic test or a manual "how to verify" step for each stage.

## 10. README requirements (Stage 6, but keep it in mind throughout)

Write the README as a case study, in this order: the problem, the solution, how it works (with a diagram), setup steps for someone else to run it, results/metrics (before vs. after), what I learned, and what I would build next. Plain, confident language. No hype.

## 11. Definition of done for any stage

- It runs end to end on my machine with one documented command.
- I understand it, because you explained each file and function to me.
- No secrets or real email content are in the repo or its history.
- The change is committed with a clear message.
- You told me what to test and what comes next.

## 12. When in doubt

Ask me one short question rather than guessing, especially about anything involving credentials, cost, or my real inbox data.
