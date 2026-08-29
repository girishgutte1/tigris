# Configuration for the Discord multi-token runner

# The guild (server) ID to navigate to when opening a specific channel.
GUILD_ID = "980693344747388928"

# Where per-account Chrome profiles will be stored (keeps sessions between runs)
PROFILES_DIR = "profiles"

# File containing tokens (one per line: token:channel_id). DO NOT commit real tokens.
TOKENS_FILE = "tokens.txt"

# Concurrency: how many accounts to run at once
CONCURRENCY = 100

# Commands to send (edit as needed)
COMMANDS = [
    "owo hunt",
    "owo battle",
    "owo sell all",
    "owo cf 3",
    "owo use 75 65 54",
]

# COMMAND_INTERVAL controls time between messages. Can be:
# - a single number "3" or 3.0 -> fixed 3.0 seconds
# - an integer range string "3-5" -> random float in [3.0, 5.0]
# - a float range string "3.5-5.5" -> random float in [3.5, 5.5]
# Example defaults to a random interval between 3.5 and 5.5 seconds
COMMAND_INTERVAL = "2-3"

# ROUNDS_PER_ACCOUNT: set to 0 for infinite loop per account
ROUNDS_PER_ACCOUNT = 0

# Logging
LOG_FILE = "multi_token_runner.log"

# Chrome options you want enabled; keep sensible defaults here.
CHROME_OPTIONS = {
    "disable_automation_features": True,
}
