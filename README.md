# PhageFeed for iPhone

The same feed as the Mac app (PubMed in your journal list + bioRxiv, same search terms and filters,
Listeria / Nostoc-Anabaena / Clostridium highlights, two-sentence summaries), rebuilt to run entirely
inside Safari. No Mac service, no Python, no Xcode.

## Put it online (once, about 5 minutes, free)

The app needs a web address, because iPhone apps added from Safari must come from a website.
GitHub Pages is free and permanent:

1. Make a free account at github.com, then click **+ → New repository**. Name it `phagefeed`,
   set it to **Public**, tick **Add a README file**, and click **Create repository**.
2. Click **Add file → Upload files** and drag in every file from this folder
   (`index.html`, `manifest.webmanifest`, `sw.js`, the three `icon-*.png`). Click **Commit changes**.
3. Go to **Settings → Pages**. Under *Branch*, choose `main` and `/ (root)`, then **Save**.
   After a minute the page shows your address, e.g. `https://yourname.github.io/phagefeed/`.

Nothing private is in these files; your API key and papers stay on your phone.

## Install on the iPhone

1. Open that address in **Safari**.
2. Tap **Share** → **Add to Home Screen** → **Add**.
3. Open PhageFeed from the Home Screen icon (not from Safari) from now on. That way it runs
   full-screen and iOS keeps your saved papers.
4. Tap **⚙︎** and paste your Anthropic API key for AI summaries (or pick the free option that
   picks two key sentences from the abstract).

The first refresh scans 60 days of bioRxiv and takes about 10 minutes. Keep the app open on screen;
if you leave, it continues from where it stopped next time.

## What changed from the Mac version

| Mac | iPhone |
|---|---|
| Background service refreshes every hour | Refreshes when you open the app if the last refresh is over an hour old, or when you tap ↻ |
| macOS notifications | A daily email from GitHub (see below) |
| Übersicht desktop widget | Dropped |
| Ollama local model | Dropped (your Mac isn't reachable from the phone); Claude or key-sentence summaries remain |
| papers.db on the Mac | Stored on the phone; **Settings → Export backup** saves a copy, **Import backup** restores it |
| Journal chips wrap in rows | Journal chips scroll sideways |
| — | **Share** link on each paper |

If bioRxiv's own API ever refuses requests from the phone, the app switches automatically to
Europe PMC's copy of bioRxiv preprints and applies the same filters.

## Email alerts (optional)

An iPhone web app can't check for papers while it's closed, so the alerts run on GitHub instead,
in the same repository that hosts the app. Every morning GitHub runs your original `server.py` and
`config.py` (same journals, search terms and filters) and emails you any papers it hasn't seen
before, with the summary, highlight tags and PDF link. On your iPhone, the email arrives as a
normal Mail notification. It's free for public repositories.

**1. A sending account.** The easiest is a Gmail account (a separate one is fine). Turn on
2-Step Verification, then create an app password at myaccount.google.com/apppasswords. Alerts can
go to any address, including your university one.

**2. Upload the files.** In your `phagefeed` repository:
- **Add file → Upload files**, drag in `notify.py`, `server.py` and `config.py`, **Commit changes**.
- **Add file → Create new file**, type the name `.github/workflows/phagefeed-email.yml`
  (the slashes make the folders), paste in the contents of that file from this zip, **Commit changes**.
  (Finder hides folders starting with a dot; press Cmd+Shift+. to show them.)

**3. Add secrets.** **Settings → Secrets and variables → Actions → New repository secret**:

| Name | Value |
|---|---|
| `SMTP_USER` | the Gmail address that sends the alerts |
| `SMTP_PASSWORD` | its 16-character app password |
| `MAIL_TO` | where alerts go (optional; default is `SMTP_USER`) |
| `ANTHROPIC_API_KEY` | optional: Claude summaries in the emails, otherwise key sentences |
| `APP_URL` | optional: your PhageFeed address, linked at the bottom of each email |
| `ONLY_HIGHLIGHTS` | optional: `yes` emails only papers mentioning Listeria, Nostoc/Anabaena or Clostridium |

Using another provider than Gmail? Also set `SMTP_HOST` and `SMTP_PORT` (465 or 587).

**4. Test it.** **Actions → PhageFeed daily email → Run workflow.** The first run takes a few
minutes and sends one "PhageFeed email alerts are on" email instead of every recent paper. After
that you get one email each morning (about 7 am Pacific), only on days with new papers. To change the time,
edit the `cron:` line in the workflow file; the hour is in UTC.

**Test email any time:** **Actions → PhageFeed daily email → Run workflow**, tick
*Send me a test email*, then **Run workflow**. You get the last 7 days of papers, formatted like the
daily email. Only you get it (through Gmail; without Gmail secrets it's saved as a draft in Buttondown
instead), and the next daily email still includes everything new.

Notes:
- The alerts check the last 14 days of PubMed and 7 days of bioRxiv; the app keeps the 60-day archive.
- GitHub pauses scheduled jobs in a repository with no changes for 60 days. It emails you first; click
  **Enable workflow** on the Actions tab (or make any small edit) to keep alerts running.
- If PubMed and bioRxiv both fail, the run is marked failed and GitHub emails you about it.

## Let anyone sign up for the emails (optional)

With this, a ✉︎ button appears in the app. Anyone can enter their email there; they get a
confirmation email first, and every update has an unsubscribe link. The addresses are stored by
Buttondown (a newsletter service, free up to 100 subscribers), not in your public repository.

1. Make a free account at buttondown.com. Your username is the part after `buttondown.com/`.
   In its settings, make sure new subscribers must confirm by email (double opt-in).
2. In `index.html` on GitHub, click the pencil icon, find `EMAIL_SIGNUP_USERNAME: "",` and put your
   username between the quotes, e.g. `EMAIL_SIGNUP_USERNAME: "phagefeed",`. **Commit changes.**
3. In Buttondown, find your API key (Settings → API) and add it as the repository secret
   `BUTTONDOWN_API_KEY`.
4. Subscribe yourself through the ✉︎ button and confirm, so you get the updates too.

Once `BUTTONDOWN_API_KEY` is set, paper emails go to all confirmed subscribers through Buttondown
instead of to you through Gmail. Your Gmail secrets are then only used for the one-time "alerts are on"
email, and you can delete them if you like. Subscribers can be seen and removed in Buttondown.

## Turning search terms on and off

Below the journal chips is a **Terms** row with every search term that matches at least one saved
paper, and how many. Tap a term to turn it off (it's crossed out); tap again to turn it back on;
**All on** resets them. A paper is shown if it matches at least one term that's on, so turning a term
off hides papers that match only that term. Nothing is deleted, and the choices are saved on that
phone. They only change what the app shows; the daily email is unaffected. The term list is
`terms.json`.

## Customising

Journal list, search terms, highlight organisms/colours and the 60-day window are at the top of
`index.html` in the `CFG` block (copied from `config.py`). Edit, upload the file again to GitHub,
then fully close and reopen the app. For the email alerts, edit `config.py`
the same way you edited it on the Mac.
