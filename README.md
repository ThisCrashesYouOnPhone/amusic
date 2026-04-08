# apple-scrobbler

A GitHub-Actions cron scrobbler that polls Apple Music and submits new plays to Last.fm — without needing an Apple Developer Program account, without paying for Marvis Pro, and without any always-on server.

It runs hourly inside GitHub Actions, costs nothing on a public repo, and stores its state as a JSON file in the repo itself so the entire history is auditable in git.

## What makes this different from other scrobblers

Most Apple Music → Last.fm scrobblers either (a) require you to use a replacement Apple Music player on your phone, (b) require a paid Apple Developer Program membership, or (c) only catch plays from songs you've added to your library. This one is different on three axes:

1. **Heuristic timestamp reconstruction.** Apple's API does not return play timestamps. Instead of stamping every poll's worth of plays at the same second (which is what every other tool that uses the API does), this walks each track's duration backwards from the poll time so the resulting Last.fm timeline shows tracks naturally spaced by their lengths. The error bound is at most one polling interval.

2. **Repeat-play detection.** By tracking each track's *position* in the recent-played list across polls, we can detect when a track was replayed during the polling window — even though Apple gives us no per-play counts. Limitation: back-to-back replays of the same song with no other song between still look like one play.

3. **Free token strategy.** Uses the publicly-exposed `MusicKit.getInstance().developerToken` from `music.apple.com` — same trick the Cider client has used for years. No $99/year Apple Developer Program membership required.

## Limitations (in plain English)

- **Timestamps are heuristic, not exact.** They'll be within an hour of reality but not to the second.
- **The 50-track API window can overflow** if you play more than ~50 tracks in one hour. Polling more often (every 30 min) reduces this risk.
- **Tokens expire roughly every 6 months.** When they do you'll see 401s in the Action logs and need to re-scrape from `music.apple.com`. Takes 30 seconds.
- **Back-to-back replays of the same song count as one play.** Apple gives us no way to fix this.
- **GitHub Actions cron has 5–15 minutes of jitter** during peak hours. This is a known GitHub limitation, not a bug here.

## One-time setup

### 1. Fork this repo

Click "Use this template" or fork it. Whatever fits your style.

### 2. Get a Last.fm session key

Locally:

```bash
cd apple-scrobbler
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python scripts/get_lastfm_session_key.py
```

It will ask for your API key + shared secret, open Last.fm in your browser for one click, and print a session key. Save it.

If you don't have a Last.fm API key yet, get one (free, instant) at https://www.last.fm/api/account/create.

### 3. Get your Apple Music tokens

In Chrome or Safari:

1. Sign in at https://music.apple.com
2. Open DevTools console (Mac: Cmd-Opt-J, Windows: F12)
3. Run these two commands and copy each result:

```js
MusicKit.getInstance().developerToken
MusicKit.getInstance().musicUserToken
```

The developer token is a JWT (long, three dot-separated chunks). The Music-User-Token is a shorter base64-ish string. Both are required.

### 4. Add the secrets to your fork

In your forked repo: **Settings → Secrets and variables → Actions → New repository secret**. Add five secrets:

| Name | Value |
|---|---|
| `APPLE_DEV_TOKEN` | from step 3 |
| `APPLE_MUSIC_USER_TOKEN` | from step 3 |
| `LASTFM_API_KEY` | from your Last.fm app |
| `LASTFM_SHARED_SECRET` | from your Last.fm app |
| `LASTFM_SESSION_KEY` | from step 2 |

### 5. Enable Actions on your fork

GitHub disables workflows on forked repos by default. Go to the **Actions** tab and click the green "I understand my workflows" button.

### 6. Test it (dry run)

In Actions → "scrobble" → "Run workflow" → set `dry_run` to `true` → Run.

Open the run logs. You should see something like:

```
Apple returned 50 tracks in recently-played.
First run — snapshotting 50 tracks WITHOUT scrobbling.
```

That's the bootstrap protection — on the very first run the script just records the current state without scrobbling, so it doesn't flood your Last.fm with 50 backdated guesses. Run it again with `dry_run=true` and you'll see it detect 0 new plays (because nothing has happened since the snapshot).

### 7. Go live

Manually trigger the workflow once with `dry_run=false` to do the real first run. After that, the hourly cron takes over.

If you specifically *want* the initial 50 to be scrobbled (e.g. you played a bunch of stuff right before setting this up), trigger once with `dry_run=false` and `bootstrap=true`.

## Maintenance

### Token expiry (every ~6 months)

When you see this in the Action logs:

```
Apple Music API returned 401. Your developer token or Music-User-Token has expired.
```

Re-scrape both tokens from `music.apple.com` console as in step 3, update the two GitHub secrets, manually trigger the workflow to confirm. That's it.

### The Last.fm session key

It never expires unless you revoke the app at https://www.last.fm/settings/applications.

## How it works (technical)

```
            Apple Music recently-played API
            (max 50 tracks, no timestamps)
                       │
                       │ polled hourly
                       ▼
            ┌──────────────────────┐
            │  GitHub Actions cron │
            └──────────┬───────────┘
                       │
                       ▼
            ┌────────────────────────────────────┐
            │  detect.py: diff vs ledger to find │
            │  new + repeat plays                │
            └──────────┬─────────────────────────┘
                       │
                       ▼
            ┌────────────────────────────────────┐
            │  timestamps.py: walk durations     │
            │  backward from now to assign ts    │
            └──────────┬─────────────────────────┘
                       │
                       ▼
            ┌────────────────────────────────────┐
            │  lastfm.py: signed batch scrobble  │
            └──────────┬─────────────────────────┘
                       │
                       ▼
            ┌────────────────────────────────────┐
            │  ledger.py: save state, commit     │
            │  ledger.json back to repo          │
            └────────────────────────────────────┘
```

Each poll updates `ledger.json` and commits it. The git history of that file is a complete audit log of every poll the scrobbler has ever done.

## Cost

Free, on a public repo. GitHub Actions on public repos has unlimited minutes. The job takes ~15 seconds per run, ~24 runs/day, ≈6 minutes/day.

On a private repo it costs ~180 minutes/month against the 2000-minute free tier.

## Local testing

```bash
export APPLE_DEV_TOKEN="..."
export APPLE_MUSIC_USER_TOKEN="..."
export LASTFM_API_KEY="..."
export LASTFM_SHARED_SECRET="..."
export LASTFM_SESSION_KEY="..."
export DRY_RUN=1

python -m apple_scrobbler.main
```

## Project layout

```
apple_scrobbler/
  __init__.py
  apple.py        — Apple Music API client
  lastfm.py       — Last.fm signed scrobble client
  detect.py       — new + repeat play detection
  timestamps.py   — heuristic timestamp reconstruction
  ledger.py       — persistent state
  main.py         — orchestrator
scripts/
  get_lastfm_session_key.py
.github/workflows/
  scrobble.yml    — hourly cron
ledger.json       — state, committed each run
```

## License

MIT.
