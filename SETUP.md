# Setting up the daily run (GitHub Actions)

The workflow in `.github/workflows/daily-digest.yml` runs the digest every morning
on GitHub's servers, so your computer does not need to be on.

## 1. Add the four secrets

Secrets are private settings that GitHub stores encrypted and hands to the workflow
while it runs. They are never in the code.

In your repo on GitHub: **Settings > Secrets and variables > Actions > Repository secrets > New repository secret**.
Add these four, using the exact names:

| Name | What goes in it |
| --- | --- |
| `GMAIL_ADDRESS` | The Gmail address that holds your `Newsletters` label |
| `GMAIL_APP_PASSWORD` | A Gmail App Password (16 characters), not your normal password. Create one at <https://myaccount.google.com/apppasswords> (needs 2-Step Verification) |
| `GEMINI_API_KEY` | A free key from <https://aistudio.google.com/apikey> |
| `DIGEST_TO` | The address the digest is sent to |

These are the same four values as in your local `.env` file. Paste only the value,
with no quotes and no `NAME=` prefix. Never put real values in this file or in the workflow.

## 2. Try it once by hand

1. Open the **Actions** tab, choose **Daily digest** in the left list.
2. Click **Run workflow**, then the green **Run workflow** button.
3. Open the run. A healthy log shows counts only, for example
   `Found 12 newsletter(s)`, `Summaries: 11 ok, 1 skipped ...`, `Digest sent.`
4. Check your inbox for the digest.

The workflow sends a real email, so a manual run counts as that day's digest.

## 3. What to expect

- **Schedule:** 11:30 UTC every day. That is 6:30 AM Eastern in winter (EST) and
  7:30 AM in summer (EDT), because GitHub's cron cannot follow daylight saving.
  For 6:30 AM in summer, change `11` to `10` in the `cron:` line. GitHub can start
  scheduled runs several minutes late.
- **Public logs:** this repo is public, so the logs are too. In Actions, `main.py`
  prints only counts and statuses, never subjects, senders, summaries, links or
  addresses, and it hides the text of error messages (you see only the kind of error).
  To see full details, reproduce the problem on your own computer.
- **Failures:** a failed run turns red and GitHub emails you (check your Actions
  notification settings). The log tells you which stage failed, for example
  `Error: FetchError (...)`, or names a missing secret.
- **Nothing is saved:** no artifacts are uploaded, and `data/newsletter_log.csv`
  is not written in Actions. The subscription audit (Stage 5) will need its own
  plan for where to keep reading data.
- **Inactivity:** GitHub turns off scheduled workflows in a public repo after
  60 days with no repo activity. If the digest stops, open the Actions tab and
  click **Enable workflow**.
- **Who can run it:** only people with write access to the repo can click
  **Run workflow**. There is no pull request trigger, so code from a fork can never
  reach your secrets.
