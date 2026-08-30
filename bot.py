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
        """
        try:
            # Try to find button by exact/partial text first
            xpaths = [
                "//button[contains(normalize-space(.), 'I accept the OwO bot rules')]",
                "//button[contains(normalize-space(.), 'I accept') and contains(@class, 'button__')]",
                "//div[@role='button' and contains(normalize-space(.), 'I accept the OwO bot rules')]",
                "//button[contains(@class, 'button__201d5')]"  # fallback class fragment (may change)
            ]
            btn = None
            for xp in xpaths:
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


def parse_tokens(path: str):
    """
    Parse tokens file.
    Accept lines:
    """,
