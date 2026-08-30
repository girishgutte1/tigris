#!/usr/bin/env python3
"""
Bot runner that reads configuration from config.py (no .env), performs a single CDP token injection attempt
and proceeds even if verification fails. Intervals support range strings (e.g. "3-5" or "3.5-5.5").

Changes made for repo-wide update:
- Send only "owo hunt"
- Do NOT require a channel id in tokens file (token only is supported)
- Run accounts sequentially (one-by-one)
- After sending "owo hunt", wait for the OwO rules button and click it
- Robust CDP/localStorage injection with fallback
- After accepting rules send "owo daily" and "owo give {amount} {user}" and click confirm
"""

import os
import time
import logging
import hashlib
import random
import json
from itertools import cycle
from typing import Optional

import config
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# Load config values
GUILD_ID = config.GUILD_ID
PROFILES_DIR = config.PROFILES_DIR
TOKENS_FILE = config.TOKENS_FILE
CONCURRENCY = config.CONCURRENCY
# COMMANDS replaced with single command "owo hunt" (config still provides it but we enforce single command)
COMMANDS = config.COMMANDS if hasattr(config, 'COMMANDS') else ["owo hunt"]
COMMAND_INTERVAL_CFG = config.COMMAND_INTERVAL
ROUNDS_PER_ACCOUNT = config.ROUNDS_PER_ACCOUNT
LOG_FILE = config.LOG_FILE
# Read optional target channel settings from config
TARGET_GUILD_ID = getattr(config, "TARGET_GUILD_ID", None)
TARGET_CHANNEL_ID = getattr(config, "TARGET_CHANNEL_ID", None)

# Give settings from config
GIVE_AMOUNT = getattr(config, "GIVE_AMOUNT", None)
GIVE_USER = getattr(config, "GIVE_USER", None)
GIVE_CONFIRM_TIMEOUT = getattr(config, "GIVE_CONFIRM_TIMEOUT", 12.0)

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s", handlers=[
    logging.FileHandler(LOG_FILE),
    logging.StreamHandler()
])
logger = logging.getLogger(__name__)


def short_id(token: str) -> str:
    return hashlib.sha1(token.encode("utf-8")).hexdigest()[:10]


def parse_interval(cfg) -> float:
    """Parse an interval config value. Accepts:
    - number (int/float) -> returns float
    - string "A-B" -> returns random.uniform(A, B)
    - string number -> float
    """
    if isinstance(cfg, (int, float)):
        return float(cfg)
    if not isinstance(cfg, str):
        logger.warning("Invalid COMMAND_INTERVAL type; falling back to 20s")
        return 20.0
    s = cfg.strip()
    if "-" in s:
        parts = s.split("-", 1)
        try:
            a = float(parts[0])
            b = float(parts[1])
            lo, hi = (a, b) if a <= b else (b, a)
            return random.uniform(lo, hi)
        except Exception:
            logger.warning(f"Invalid interval range '{cfg}'; falling back to 20s")
            return 20.0
    else:
        try:
            return float(s)
        except Exception:
            logger.warning(f"Invalid interval '{cfg}'; falling back to 20s")
            return 20.0


class HumanLikeDiscord:
    def __init__(self, profile_dir: str):
        self.profile_dir = profile_dir
        self.driver = None
        self._start_browser()

    def _start_browser(self):
        opts = Options()
        opts.add_argument("--window-size=1200,900")
        opts.add_argument("--no-first-run")
        opts.add_argument("--no-default-browser-check")
        if getattr(config, "CHROME_OPTIONS", {}).get("disable_automation_features", True):
            opts.add_argument("--disable-blink-features=AutomationControlled")
            opts.add_experimental_option("excludeSwitches", ["enable-automation"])
            opts.add_experimental_option("useAutomationExtension", False)

        if self.profile_dir:
            os.makedirs(self.profile_dir, exist_ok=True)
            opts.add_argument(f"--user-data-dir={os.path.abspath(self.profile_dir)}")

        svc = Service(ChromeDriverManager().install())
        self.driver = webdriver.Chrome(service=svc, options=opts)
        self.driver.set_page_load_timeout(60)
        time.sleep(1)

    def close(self):
        try:
            if self.driver:
                self.driver.quit()
        except Exception:
            pass

    def _read_local_storage_token(self) -> Optional[str]:
        try:
            # Run JS in page context to read localStorage token
            return self.driver.execute_script("return window.localStorage.getItem('token');")
        except Exception as e:
            logger.debug(f"read_local_storage_token error: {e}")
            return None

    def inject_token_once(self, token: str) -> bool:
        """Single injection attempt using CDP addScriptToEvaluateOnNewDocument.
        If verification fails, return False quickly. If CDP is unavailable, fall back to execute_script.
        This version stores the token surrounded by quotes (e.g. '"token"') in localStorage as requested.
        """
        try:
            # We need the value in localStorage to include quotes, e.g. '"the-token"'.
            value_with_quotes = f'"{token}"'
            js_value_literal = json.dumps(value_with_quotes)  # JS literal for the string that includes quotes
            script = f'window.localStorage.setItem("token", {js_value_literal});'

            # Try one CDP call to add script on new document
            try:
                self.driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": script})
                logger.info("CDP injection scheduled (single attempt)")
            except Exception as e:
                logger.info(f"CDP injection call failed (single attempt): {e}")
                # Try immediate in-page injection as a fallback (will only affect current document)
                try:
                    self.driver.execute_script(script)
                    logger.info("Fallback: localStorage set via execute_script")
                except Exception as e2:
                    logger.info(f"Fallback execute_script injection failed: {e2}")

            # Navigate so the injected script runs on load (if CDP scheduled) or so we land in channel
            try:
                self.driver.get("https://discord.com/channels/@me")
            except Exception:
                # ignore navigation errors here
                pass

            # short wait then check localStorage
            time.sleep(1.0 + random.random() * 1.0)
            read_back = self._read_local_storage_token()
            expected = value_with_quotes
            logger.debug(f"Single-inject read-back: {read_back!r} expected: {expected!r}")
            if read_back == expected:
                logger.info("Token verified in localStorage after single attempt")
                return True
            else:
                logger.info("Token not verified after single attempt; proceeding to open channel")
                return False

        except Exception as e:
            logger.error(f"inject_token_once exception: {e}")
            return False

    def navigate_to_channel(self, guild_id: str = None, channel_id: str = None):
        """Navigate directly to a guild/channel URL or to /channels/@me if none provided."""
        try:
            if guild_id and channel_id:
                url = f"https://discord.com/channels/{guild_id}/{channel_id}"
            else:
                url = "https://discord.com/channels/@me"
            self.driver.get(url)
            # small wait for page JS to run
            time.sleep(1.0 + random.random() * 1.5)
        except Exception as e:
            logger.debug(f"navigate_to_channel failed: {e}")

    def find_message_box(self):
        try:
            xpath = "//div[@role='textbox' and @contenteditable='true']"
            box = WebDriverWait(self.driver, 12).until(EC.element_to_be_clickable((By.XPATH, xpath)))
            return box
        except Exception as e:
            logger.debug(f"find_message_box error: {e}")
            return None

    def _get_element_center(self, element):
        rect = self.driver.execute_script("""
            const r = arguments[0].getBoundingClientRect();
            return {x: Math.floor(r.left + r.width/2), y: Math.floor(r.top + r.height/2),
                    w: Math.floor(r.width), h: Math.floor(r.height)};
        """, element)
        return rect

    def human_move_to_and_click(self, element):
        try:
            # Prefer move_to_element_with_offset so offsets are relative to element rather than global mouse origin
            moves = max(6, int(random.uniform(6, 12)))
            for i in range(moves):
                # offsets shrink as we approach the final position
                offset_x = random.randint(-15, 15)
                offset_y = random.randint(-12, 12)
                try:
                    ActionChains(self.driver).move_to_element_with_offset(
                        element,
                        offset_x,
                        offset_y
                    ).perform()
                except Exception:
                    try:
                        ActionChains(self.driver).move_to_element(element).perform()
                    except Exception:
                        pass
                time.sleep(random.uniform(0.02, 0.08))
            # final precise move and click
            try:
                ActionChains(self.driver).move_to_element(element).pause(random.uniform(0.05, 0.15)).click().perform()
            except Exception:
                try:
                    element.click()
                except Exception as e:
                    logger.debug(f"Final click fallback failed: {e}")
            time.sleep(0.12 + random.random() * 0.2)
        except Exception as e:
            logger.debug(f"human_move_to_and_click error: {e}")
            try:
                element.click()
            except Exception:
                pass

    def human_type(self, element, text: str):
        try:
            # Click into the element first
            try:
                self.human_move_to_and_click(element)
            except Exception:
                try:
                    element.click()
                except Exception:
                    pass
            time.sleep(0.05 + random.random() * 0.12)
            for ch in text:
                element.send_keys(ch)
                time.sleep(random.uniform(0.03, 0.12))
            time.sleep(random.uniform(0.08, 0.25))
            element.send_keys(Keys.RETURN)
            logger.info(f"Typed message: {text}")
            return True
        except Exception as e:
            logger.error(f"human_type error: {e}")
            return False


    def click_owo_accept(self, timeout: float = 20.0) -> bool:
        """
        Wait for the OwO rules accept button and click it.
        The button label often contains "I accept the OwO bot rules". We try a couple of robust XPaths.
        Uses the last() occurrence so we click the most recent button in the DOM.
        """
        try:
            # Try to find button by exact/partial text first, prefer the last matching one
            base_xpaths = [
                "//button[contains(normalize-space(.), 'I accept the OwO bot rules')]",
                "//button[contains(normalize-space(.), 'I accept') and contains(@class, 'button__')]",
                "//div[@role='button' and contains(normalize-space(.), 'I accept the OwO bot rules')]",
                "//button[contains(@class, 'button__201d5')]"  # fallback class fragment (may change)
            ]
            btn = None
            for bx in base_xpaths:
                xp = f"({bx})[last()]"
                try:
                    btn = WebDriverWait(self.driver, timeout).until(EC.element_to_be_clickable((By.XPATH, xp)))
                    if btn:
                        break
                except Exception:
                    btn = None
            if not btn:
                logger.info("OwO accept button not found within timeout")
                return False
            # click it human-like
            self.human_move_to_and_click(btn)
            logger.info("Clicked OwO accept button")
            # small pause to let Discord process the click
            time.sleep(1.0 + random.random() * 1.0)
            return True
        except Exception as e:
            logger.info(f"click_owo_accept failed: {e}")
            return False

    def click_confirm(self, timeout: float = 12.0) -> bool:
        """
        Wait for a confirmation button (label contains 'Confirm' or similar) and click it.
        Returns True if clicked. Uses last() to target the newest confirm button.
        """
        try:
            base_xpaths = [
                "//button[contains(normalize-space(.), 'Confirm')]",
                "//button[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'confirm')]",
                "//div[@role='button' and contains(normalize-space(.), 'Confirm')]",
                "//button[contains(@class, 'button__') and contains(normalize-space(.), 'Confirm')]"
            ]
            btn = None
            for bx in base_xpaths:
                xp = f"({bx})[last()]"
                try:
                    btn = WebDriverWait(self.driver, timeout).until(EC.element_to_be_clickable((By.XPATH, xp)))
                    if btn:
                        break
                except Exception:
                    btn = None
            if not btn:
                logger.info("Confirm button not found within timeout")
                return False
            self.human_move_to_and_click(btn)
            logger.info("Clicked Confirm button")
            time.sleep(0.6 + random.random() * 1.2)
            return True
        except Exception as e:
            logger.info(f"click_confirm failed: {e}")
            return False

def parse_tokens(path: str):
    """
    Parse tokens file.
    Accept lines:
      - token
      - token:ignored_channel (channel part is ignored)
    Comments (#) and blank lines are skipped.
    Returns list of token strings.
    """
    if not os.path.exists(path):
        logger.error(f"Tokens file not found: {path}")
        return []
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for ln in f:
            s = ln.strip()
            if not s or s.startswith("#"):
                continue
            # allow token or token:channel but ignore channel
            if ":" in s:
                token = s.split(":", 1)[0].strip()
                if token:
                    out.append(token)
                else:
                    logger.warning(f"Malformed tokens line (empty token): {s}")
            else:
                out.append(s)
    return out

def handle_account(token, guild_id, channel_id, profiles_base):
    """
    For each account:
    - start browser with profile
    - inject token (single attempt)
    - navigate to TARGET_GUILD_ID/TARGET_CHANNEL_ID if provided, otherwise /channels/@me
    - send "owo hunt"
    - wait for OwO rules button and click it (if present)
    - send "owo daily" and "owo give {amount} {user}" and click confirm
    """
    aid = short_id(token)
    profile_dir = os.path.join(profiles_base, aid)
    client = None
    try:
        logger.info(f"Starting account {aid}")
        client = HumanLikeDiscord(profile_dir)

        injected = client.inject_token_once(token)
        if not injected:
            logger.info(f"Token injection not verified for {aid}; proceeding to open channel")

        # If both guild and channel provided, navigate to that channel; otherwise go to /channels/@me
        if guild_id and channel_id:
            client.navigate_to_channel(guild_id, channel_id)
        else:
            client.navigate_to_channel()  # goes to /channels/@me

        # small wait to ensure page is ready
        time.sleep(1.0 + random.random() * 1.5)

        # send the single command "owo hunt"
        try:
            box = client.find_message_box()
            if not box:
                logger.warning(f"No message box for {aid}; cannot send message")
            else:
                sent = client.human_type(box, COMMANDS[0])
                if sent:
                    logger.info(f"Sent command for {aid}: {COMMANDS[0]}")
                else:
                    logger.warning(f"Failed to send command for {aid}: {COMMANDS[0]}")
        except Exception as e:
            logger.error(f"Error while sending command for {aid}: {e}")

        # wait for OwO's response and try clicking the accept button
        try:
            clicked = client.click_owo_accept(timeout=20.0)
            if clicked:
                logger.info(f"OwO rules accepted for {aid}")
            else:
                logger.info(f"No OwO accept button clicked for {aid}")
        except Exception as e:
            logger.error(f"Error while attempting to click OwO accept for {aid}: {e}")

        # After accepting (or not), send daily and give sequence
        try:
            # small pause to let OwO's reply settle
            time.sleep(0.6 + random.random() * 1.2)

            # send owo daily
            box = client.find_message_box()
            if box:
                client.human_type(box, "owo daily")
                logger.info(f"Sent 'owo daily' for {aid}")
            else:
                logger.warning(f"No message box to send 'owo daily' for {aid}")

            # wait a bit for OwO to respond
            time.sleep(2.0 + random.random() * 2.0)

            # prepare give command from config
            if GIVE_AMOUNT is not None and GIVE_USER:
                box = client.find_message_box()
                give_cmd = f"owo give {GIVE_AMOUNT} {GIVE_USER}"
                if box:
                    client.human_type(box, give_cmd)
                    logger.info(f"Sent give command for {aid}: {give_cmd}")
                else:
                    logger.warning(f"No message box to send give command for {aid}")
                # wait for confirm button to appear
                clicked = client.click_confirm(timeout=GIVE_CONFIRM_TIMEOUT)
                if clicked:
                    logger.info(f"Give confirmed for {aid}")
                else:
                    logger.info(f"No Confirm button clicked for {aid}")
            else:
                logger.info("GIVE_AMOUNT or GIVE_USER not configured; skipping give step")

        except Exception as e:
            logger.error(f"Error in post-accept steps for {aid}: {e}")

        # finished this account
        logger.info(f"Finished account {aid}")

    except Exception as e:
        logger.error(f"Exception in handle_account {aid}: {e}")
    finally:
        if client:
            client.close()

def main():
    logger.info("Runner starting (sequential mode: one account at a time)")
    if not GUILD_ID:
        logger.error("GUILD_ID not set in config.py")
        return
    accounts = parse_tokens(TOKENS_FILE)
    if not accounts:
        logger.error("No accounts found in tokens file")
        return

    # prefer TARGET_* if set in config, otherwise fall back to GUILD_ID and None channel
    target_guild = TARGET_GUILD_ID or GUILD_ID
    target_channel = TARGET_CHANNEL_ID  # may be None — in that case navigate to /channels/@me

    logger.info(f"Running {len(accounts)} accounts sequentially -> target {target_guild}/{target_channel}")
    # Sequential processing: one account fully completes before next starts
    for token in accounts:
        try:
            handle_account(token, target_guild, target_channel, PROFILES_DIR)
        except Exception as e:
            logger.error(f"Account job failed: {e}")

    logger.info("All done")


if __name__ == "__main__":
    main()
