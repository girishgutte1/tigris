# Discord Sequenced Commands Bot (Selenium)

This repository now includes a token-based multi-account runner (token_runner.py) that lets you run many accounts by supplying user tokens and per-account channel IDs.

Important security & safety warnings
- Tokens are powerful and equivalent to account access. Never commit tokens.txt (or any real tokens) to source control.
- Automating many user accounts or message sending is likely to violate Discord's Terms of Service and will put accounts and IPs at risk of suspension or bans. Use at your own risk.

Quick start (download ZIP, extract, run)
1) Prepare the repo
   - Extract the ZIP and open a terminal in the repo folder.

2) Create a virtual environment and install dependencies
   - python -m venv .venv
   - .venv\Scripts\activate    (on Windows)
   - python -m pip install --upgrade pip
   - python -m pip install -r requirements.txt

3) Configure
   - Copy .env.example to .env and edit GUILD_ID and other values.
   - Create tokens.txt in the repo root. Each line: token:channel_id
     Example:
       eyJ...token1...:123456789012345678
       mfa...token2...:234567890123456789

4) Run
   - python token_runner.py
   - The script will create a profiles/ directory and persistent Chrome profiles per token.
   - Chrome windows will open. The script injects each token into localStorage and reloads, then navigates to the target channel.

Notes & tips
- Profiles are stored under profiles/<short-id>. If you want to preserve sessions, reuse those folders across runs.
- If you prefer manual login, create profiles by launching Chrome with --user-data-dir and logging in, then use a profiles.csv approach (not included here).
- To change concurrency or rounds per account edit .env or export env vars.

Files added
- token_runner.py  — new multi-token runner (token injection + per-account messaging)
- .env.example     — example environment file
- tokens.txt.example — example tokens file (do NOT add real tokens)

If you want me to:
- Add optional token encryption helpers
- Add per-account commands files
- Add NoPeCha / captcha-solver extension support
- Add Dockerfile or Windows-friendly start script
Tell me which and I can add them on a follow-up.
