#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ENV_FILE=${ENV_FILE:-"$SCRIPT_DIR/.env"}
STATE_FILE=${STATE_FILE:-"$SCRIPT_DIR/last_spin_id.txt"}
VISIBILITY=${MASTODON_VISIBILITY:-public}
SPINITRON_URL=${SPINITRON_URL:-"https://widgets.spinitron.com/widget/now-playing-v2?station=kvcu&num=1&meta=1"}
SPINITRON_FALLBACK_URL=${SPINITRON_FALLBACK_URL:-"https://spinitron.com/KVCU/"}
RUN_COUNT=3
SLEEP_SECONDS=$((60 / RUN_COUNT))

iteration=1
while [ "$iteration" -le "$RUN_COUNT" ]; do
  /usr/bin/python3 "$SCRIPT_DIR/spinitron_to_mastodon.py" \
    --env-file "$ENV_FILE" \
    --state-file "$STATE_FILE" \
    --visibility "$VISIBILITY" \
    --spinitron-url "$SPINITRON_URL" \
    --fallback-url "$SPINITRON_FALLBACK_URL" \
    "$@"

  if [ "$iteration" -lt "$RUN_COUNT" ]; then
    sleep "$SLEEP_SECONDS"
  fi
  iteration=$((iteration + 1))
done
