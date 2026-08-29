#!/usr/bin/env python3
"""
Bot runner that reads configuration from config.py (no .env), performs a single CDP token injection attempt
and proceeds even if verification fails. Intervals support range strings (e.g. "3-5" or "3.5-5.5").
"""
import os
import time
import logging
import hashlib
import random
from itertools import cycle
from concurrent.futures import ThreadPoolExecutor
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
COMMANDS = config.COMMANDS
COMMAND_INTERVAL_CFG = config.COMMAND_INTERVAL
ROUNDS_PER_ACCOUNT = config.ROUNDS_PER_ACCOUNT
LOG_FILE = config.LOG_FILE

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
            return self.driver.execute_script("return window.localStorage.getItem('token')")
        except Exception as e:
            logger.debug(f"read_local_storage_token error: {e}")
            return None

    def inject_token_once(self, token: str) -> bool:
        """Single injection attempt using CDP addScriptToEvaluateOnNewDocument.
        If verification fails, return False quickly.
        """
        try:
            safe = token.replace("\\", "\\\\").replace('"', '\\"')
            js_value_literal = f'\\"{safe}\\"'
            script = f'window.localStorage.setItem("token", "{js_value_literal}");'

            # Try one CDP call to add script on new document
            try:
                self.driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": script})
                logger.info("CDP injection scheduled (single attempt)")
            except Exception as e:
                logger.info(f"CDP injection call failed (single attempt): {e}")
                # As per your decision: do not do additional attempts — proceed to open channel
                return False

            # Navigate so the injected script runs on load
            try:
                self.driver.get("https://discord.com/channels/@me")
            except Exception:
                pass

            # short wait then check localStorage
            time.sleep(1.0 + random.random() * 1.0)
            read_back = self._read_local_storage_token()
            expected = f'"{token}"'
            logger.debug(f"Single-inject read-back: {read_back}")
            if read_back == expected:
                logger.info("Token verified in localStorage after single CDP attempt")
                return True
            else:
                logger.info("Token not verified after single attempt; proceeding to open channel")
                return False

        except Exception as e:
            logger.error(f"inject_token_once exception: {e}")
            return False

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
            rect = self._get_element_center(element)
            target_x, target_y = rect['x'], rect['y']
            moves = max(6, int(random.uniform(6, 12)))
            for i in range(moves):
                frac = (i + 1) / moves
                ix = int(target_x * frac + random.uniform(-10, 10) * (1 - frac))
                iy = int(target_y * frac + random.uniform(-8, 8) * (1 - frac))
                try:
                    ActionChains(self.driver).move_by_offset(ix, iy).perform()
                except Exception:
                    try:
                        ActionChains(self.driver).move_to_element_with_offset(element, random.randint(-5,5), random.randint(-5,5)).perform()
                    except Exception:
                        pass
                time.sleep(random.uniform(0.02, 0.08))
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


def parse_tokens(path: str):
    if not os.path.exists(path):
        logger.error(f"Tokens file not found: {path}")
        return []
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for ln in f:
            s = ln.strip()
            if not s or s.startswith("#"):
                continue
            if ":" in s:
                token, ch = s.split(":", 1)
                token = token.strip()
                ch = ch.strip()
                if token and ch:
                    out.append((token, ch))
            else:
                logger.warning(f"Malformed tokens line: {s}")
    return out


def handle_account(token, channel_id, guild_id, profiles_base):
    aid = short_id(token)
    profile_dir = os.path.join(profiles_base, aid)
    client = None
    try:
        logger.info(f"Starting account {aid} -> channel {channel_id}")
        client = HumanLikeDiscord(profile_dir)

        injected = client.inject_token_once(token)
        if not injected:
            logger.info(f"Token injection not verified for {aid}; proceeding to open channel")

        # try quick login detection then proceed regardless
        try:
            client.driver.get(f"https://discord.com/channels/{guild_id}/{channel_id}")
        except Exception:
            # fallback to navigate method
            client.navigate_to_channel(guild_id, channel_id)

        # Infinite or finite loop
        logger.info("Starting message loop for account")
        try:
            if ROUNDS_PER_ACCOUNT == 0:
                loop_iter = cycle(COMMANDS)
            else:
                # finite rounds: produce sequence of length ROUNDS_PER_ACCOUNT cycling commands
                seq = []
                for i in range(ROUNDS_PER_ACCOUNT):
                    seq.append(COMMANDS[i % len(COMMANDS)])
                loop_iter = iter(seq)

            for message in loop_iter:
                wait_time = parse_interval(COMMAND_INTERVAL_CFG)
                if wait_time < 0.01:
                    wait_time = 0.01
                logger.info(f"Next message will be sent in {wait_time:.1f} seconds: {message}")
                time.sleep(wait_time)

                box = client.find_message_box()
                if not box:
                    logger.warning(f"No message box for {aid}; will retry after interval")
                    continue

                ok = client.human_type(box, message)
                if ok:
                    logger.info(f"Message sent: {message}")
                else:
                    logger.warning(f"Failed to send message: {message}")

                # tiny random pause before next iteration to vary exact timing
                time.sleep(random.uniform(0.2, 0.8))

        except Exception as loop_exc:
            logger.error(f"Message loop exception for {aid}: {loop_exc}")

        logger.info(f"Finished account {aid}")

    except Exception as e:
        logger.error(f"Exception in handle_account {aid}: {e}")
    finally:
        if client:
            client.close()


def main():
    logger.info("Runner starting")
    if not GUILD_ID:
        logger.error("GUILD_ID not set in config.py")
        return
    accounts = parse_tokens(TOKENS_FILE)
    if not accounts:
        logger.error("No accounts found in tokens file")
        return
    max_workers = len(accounts) if CONCURRENCY <= 0 else min(CONCURRENCY, len(accounts))
    logger.info(f"Running {len(accounts)} accounts with concurrency={max_workers}")
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = []
        for token, ch in accounts:
            futures.append(ex.submit(handle_account, token, ch, GUILD_ID, PROFILES_DIR))
        for f in futures:
            try:
                f.result()
            except Exception as e:
                logger.error(f"Account job failed: {e}")
    logger.info("All done")


if __name__ == "__main__":
    main()
