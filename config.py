# Configuration for the Discord multi-token runner

# The guild (server) ID to navigate to when opening a specific channel.
# Keep this set as a fallback. If you want all accounts to send into a specific channel,
# set TARGET_GUILD_ID and TARGET_CHANNEL_ID below instead of relying on per-token channels.
GUILD_ID = "980693344747388928"

# When set, all accounts will be navigated to TARGET_GUILD_ID / TARGET_CHANNEL_ID before sending commands.
# Example:
# TARGET_GUILD_ID = "980693344747388928"
# TARGET_CHANNEL_ID = "123456789012345678"
# Set either to None to disable and fall back to GUILD_ID / /channels/@me behavior.
TARGET_GUILD_ID = None
TARGET_CHANNEL_ID = None

# Where per-account Chrome profiles will be stored (keeps sessions between runs)
PROFILES_DIR = "profiles"

# File containing tokens (one per line). Format now supports either:
#   token
#   token:ignored_channel   (channel part is ignored)
# DO NOT commit real tokens.
TOKENS_FILE = "tokens.txt"

# Concurrency is respected by other modes but the current runner processes accounts sequentially
# (one account completes before the next starts). Set to >1 only if you reintroduce ThreadPoolExecutor.
CONCURRENCY = 1

# Commands to send (edit as needed) — default to single command for OwO hunting
COMMANDS = [
    "owo hunt",
]

# COMMAND_INTERVAL controls time between messages. Can be:
# - a single number "3" or 3.0 -> fixed 3.0 seconds
# - an integer range string "3-5" -> random float in [3.0, 5.0]
# - a float range string "3.5-5.5" -> random float in [3.5, 5.5]
# Example defaults to a random interval between 2 and 3 seconds
COMMAND_INTERVAL = "2-3"

# ROUNDS_PER_ACCOUNT: set to 0 for infinite loop per account (the runner is sequential)
ROUNDS_PER_ACCOUNT = 0

# Logging
LOG_FILE = "multi_token_runner.log"

# Chrome options you want enabled; keep sensible defaults here.
CHROME_OPTIONS = {
    "disable_automation_features": True,
}
