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
| macOS notifications | Dropped (iPhone web apps can't check for papers while closed) |
| Übersicht desktop widget | Dropped |
| Ollama local model | Dropped (your Mac isn't reachable from the phone); Claude or key-sentence summaries remain |
| papers.db on the Mac | Stored on the phone; **Settings → Export backup** saves a copy, **Import backup** restores it |
| Journal chips wrap in rows | Journal chips scroll sideways |
| — | **Share** link on each paper |

If bioRxiv's own API ever refuses requests from the phone, the app switches automatically to
Europe PMC's copy of bioRxiv preprints and applies the same filters.

## Customising

Journal list, search terms, highlight organisms/colours and the 60-day window are at the top of
`index.html` in the `CFG` block (copied from `config.py`). Edit, upload the file again to GitHub,
then fully close and reopen the app.
