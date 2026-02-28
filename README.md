# KVCU Now Playing Mastodon Bot

Posts the current KVCU spin from Spinitron to Mastodon, including album art when available.

The bot avoids duplicate posts by saving the last posted spin ID in a state file.

## What It Posts

Each post includes:

- played time
- song title
- artist
- album
- DJ
- sanitized artist hashtag
- sanitized DJ hashtag
- static hashtags: `#Radio1190 #KVCU`

If album art is available, the bot uploads and attaches it.

## Files

- `spinitron_to_mastodon.py`: main bot script
- `run_kvcu_mastodon.sh`: wrapper script that loads defaults from env vars
- `.env.example`: sample environment configuration
- `last_spin_id.txt`: dedupe state file (created/updated automatically)

## Requirements

- Python 3.9+
- A Mastodon account and access token with permission to post statuses and upload media

No third-party Python packages are required.

## Setup

1. Copy the example env file:

```bash
cp .env.example .env
```

2. Edit `.env` and set:

- `MASTODON_BASE_URL` (example: `https://mastodon.social`)
- `MASTODON_ACCESS_TOKEN`

## Environment Variables

Required (unless using `--dry-run`):

- `MASTODON_BASE_URL`
- `MASTODON_ACCESS_TOKEN`

Optional:

- `MASTODON_VISIBILITY` (default: `public`)
- `SPINITRON_URL` (default: KVCU widget URL)
- `SPINITRON_FALLBACK_URL` (default: `https://spinitron.com/KVCU/`)
- `STATE_FILE` (default in wrapper: `./last_spin_id.txt`)
- `ENV_FILE` (default in wrapper: `./.env`)

## Usage

Run using the wrapper script (recommended):

```bash
./run_kvcu_mastodon.sh
```

Dry run (fetch + parse + render post text, no Mastodon post):

```bash
./run_kvcu_mastodon.sh --dry-run
```

Verbose logging:

```bash
./run_kvcu_mastodon.sh --verbose
```

Direct Python invocation:

```bash
python3 spinitron_to_mastodon.py \
  --env-file .env \
  --state-file last_spin_id.txt \
  --visibility public
```

## Command-Line Flags

`spinitron_to_mastodon.py` supports:

- `--spinitron-url`
- `--fallback-url`
- `--state-file`
- `--env-file`
- `--visibility`
- `--dry-run`
- `--verbose`

## Duplicate Protection

The bot reads the current spin unique ID from Spinitron and compares it to the saved value in `last_spin_id.txt`.

- If the IDs match, it skips posting.
- If the IDs differ, it posts and updates the state file.

## Fallback Behavior

The bot tries the primary widget URL first. If that request fails, it automatically retries with the fallback page URL.

## Hashtag Formatting

Artist and DJ tags are normalized to hashtag-safe tokens:

- spaces removed
- punctuation removed
- leading `#` stripped
- letters/numbers/underscore retained

Examples:

- `The Great Shatzby` -> `#TheGreatShatzby`
- `Ben Bronte / DJ Set` -> `#BenBronteDJSet`

Static hashtags are always appended at the end:

- `#Radio1190 #KVCU`

## Scheduling (cron example)

Run every 5 minutes:

```bash
*/5 * * * * cd /PATH/TO/YOUR/CODE/kvcu-now-playing-mastodon && ./run_kvcu_mastodon.sh >> /tmp/kvcu-mastodon.log 2>&1
```

## Troubleshooting

- `Missing MASTODON_BASE_URL or MASTODON_ACCESS_TOKEN`:
  - Set those values in `.env` or exported environment vars.
- `Primary URL failed ... HTTP Error 400`:
  - Usually non-fatal if fallback succeeds.
- `Duplicate spin ID; skipping post`:
  - Expected behavior; current spin was already posted.
