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
| macOS notifications | Email alerts, sent by GitHub every hour (see below) |
| Übersicht desktop widget | Dropped |
| Ollama local model | Dropped (your Mac isn't reachable from the phone); Claude or key-sentence summaries remain |
| papers.db on the Mac | Stored on the phone; **Settings → Export backup** saves a copy, **Import backup** restores it |
| Journal chips wrap in rows | Journal chips scroll sideways |
| — | **Share** link on each paper |

If bioRxiv's own API ever refuses requests from the phone, the app switches automatically to
Europe PMC's copy of bioRxiv preprints and applies the same filters.

## Email alerts (optional)

An iPhone web app can't check for papers while it's closed, so the alerts run on GitHub instead,
in the same repository that hosts the app. Every hour GitHub runs your original `server.py` and
`config.py` (same journals, search terms and filters) and emails you any papers it hasn't seen
before, with the summary, highlight tags and PDF link. On your iPhone, the email arrives as a
normal Mail notification. It's free for public repositories.

**1. A sending account.** The easiest is a Gmail account (a separate one is fine). Turn on
2-Step Verification, then create an app password at myaccount.google.com/apppasswords. Alerts can
go to any address, including your university one.

**2. Upload the files.** In your `phagefeed` repository:
- **Add file → Upload files**, drag in the `notifier` folder, **Commit changes**.
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

**4. Test it.** **Actions → PhageFeed email alerts → Run workflow.** The first run takes a few
minutes and sends one "PhageFeed email alerts are on" email instead of every recent paper. After
that you only get emails when something new appears.

Notes:
- The alerts check the last 14 days of PubMed and 7 days of bioRxiv; the app keeps the 60-day archive.
- GitHub pauses hourly jobs in a repository with no changes for 60 days. It emails you first; click
  **Enable workflow** on the Actions tab (or make any small edit) to keep alerts running.
- If PubMed and bioRxiv both fail, the run is marked failed and GitHub emails you about it.

## Customising

Journal list, search terms, highlight organisms/colours and the 60-day window are at the top of
`index.html` in the `CFG` block (copied from `config.py`). Edit, upload the file again to GitHub,
then fully close and reopen the app. For the email alerts, edit `notifier/config.py`
the same way you edited it on the Mac.
