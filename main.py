import asyncio
import os
import logging
import re
import io
import time
from typing import Tuple, Optional, Any
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.error import TelegramError

# --- Logging Setup ---
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- CONFIGURATION (Ensure these are set in your environment) ---
PORT = int(os.environ.get("PORT", 8080))
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_URL_BASE = os.getenv("WEBHOOK_URL_BASE")

# Define target URLs
URL_LEVANTER = os.getenv("URL_LEVANTER", "https://levanter-delta.vercel.app/")
URL_RAGANORK = os.getenv("URL_RAGANORK", "https://session.raganork.site/")

# Define the paths provided by the Heroku buildpacks (heroku-buildpack-chromedriver & google-chrome)
CHROME_BIN_PATH = os.environ.get("GOOGLE_CHROME_BIN", "/app/.apt/usr/bin/google-chrome")
CHROME_DRIVER_PATH = os.environ.get("CHROMEDRIVER_PATH", "/app/.chromedriver/bin/chromedriver")

# --- Custom Exception for cleaner error handling ---
class AutomationFailure(Exception):
    """Custom exception to carry the error message and the final screenshot buffer."""
    def __init__(self, message, screenshot_buffer: Optional[io.BytesIO] = None):
        super().__init__(message)
        self.screenshot_buffer = screenshot_buffer
        self.original_exception_type = type(self)

    def set_original_type(self, original_type: Any):
        """Used to store the actual Selenium exception type."""
        self.original_exception_type = original_type


def get_chrome_driver():
    """Initializes and returns a configured headless Chrome driver."""
    
    # Critical Check: Ensure binaries exist
    if not os.path.exists(CHROME_BIN_PATH):
        raise FileNotFoundError(f"Chrome binary not found at {CHROME_BIN_PATH}. Check your Heroku buildpacks.")
    if not os.path.exists(CHROME_DRIVER_PATH):
        raise FileNotFoundError(f"Chromedriver binary not found at {CHROME_DRIVER_PATH}. Check your Heroku buildpacks.")

    options = ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1280,720")
    # Setting binary location is essential for Heroku deployment
    options.binary_location = CHROME_BIN_PATH

    # Service setup using the explicit path for Chromedriver
    service = ChromeService(executable_path=CHROME_DRIVER_PATH)

    driver = webdriver.Chrome(service=service, options=options)
    return driver

# --- SYNCHRONOUS WORKER FUNCTION (All Selenium Logic Runs Here) ---
def perform_raganork_pairing(mobile_number: str) -> Tuple[str, io.BytesIO, io.BytesIO]:
    """
    Synchronous function containing ALL Selenium logic. 
    Returns: (code_text, initial_screenshot, final_screenshot)
    Raises: AutomationFailure on any Selenium error.
    """
    logger.info(f"Starting SYNC Raganork job for number: {mobile_number}")
    
    # Pre-process the number
    match = re.match(r"^\+(\d+)(.*)$", mobile_number)
    if not match:
        raise ValueError("Invalid mobile number format. Must start with '+'.")
        
    country_code_full = f"+{match.group(1)}"
    number_body = match.group(2).lstrip('0')
    
    driver = None
    try:
        # 1. Initialize the driver
        driver = get_chrome_driver()
        wait = WebDriverWait(driver, 30) # Generous wait for Heroku latency
        
        # 2. Navigate and take INITIAL screenshot
        driver.get(URL_RAGANORK) 
        
        # Capture initial state for debugging
        initial_screenshot = io.BytesIO(driver.get_screenshot_as_png())
        logger.info("Navigated to Raganork homepage and captured initial screen.")

        # 3. Click 'Enter code' button (See Screenshot 1)
        enter_code_selector = (By.XPATH, '//button[contains(text(), "Enter code")]')
        wait.until(EC.element_to_be_clickable(enter_code_selector)).click()
        logger.info("Clicked 'Enter code'.")
        
        # 4. Click the country code dropdown to open the list (See Screenshot 2)
        # Using a stable XPath to find the element that holds the current code (e.g., '+1')
        country_dropdown_selector = (By.XPATH, '//div[contains(@class, "country-code-select")]')
        wait.until(EC.element_to_be_clickable(country_dropdown_selector)).click()
        logger.info("Clicked country code dropdown to show the list.")

        # 5. Select the correct country code (See Screenshot 3)
        # The list items are usually present in the DOM when the dropdown is open.
        # Find the specific radio button or list item by its text.
        country_code_option_selector = (By.XPATH, f'//li[contains(text(), "{country_code_full}")]/input[@type="radio"]')
        
        # Wait until the radio button for the specific country code is present and click its parent (or the radio button itself)
        radio_button = wait.until(EC.presence_of_element_located(country_code_option_selector))
        # Use JavaScript click as custom dropdowns sometimes fail with native click()
        driver.execute_script("arguments[0].click();", radio_button)
        logger.info(f"Selected country code: {country_code_full} using JavaScript click.")
        
        # 6. Input the phone number body (See Screenshot 4)
        phone_input_selector = (By.XPATH, '//input[@placeholder="Enter phone number" or contains(@value, "91")]')
        phone_input_field = wait.until(EC.presence_of_element_located(phone_input_selector))
        # Clear just in case there's an existing value
        phone_input_field.clear() 
        phone_input_field.send_keys(number_body)
        logger.info(f"Inputted number body: {number_body}")

        # 7. Click 'GET CODE'
        get_code_button_selector = (By.XPATH, '//button[contains(text(), "GET CODE")]')
        wait.until(EC.element_to_be_clickable(get_code_button_selector)).click()
        logger.info("Clicked 'GET CODE'.")
        
        # 8. Wait for the result modal to appear (the readonly input field) (See Screenshot 5)
        # We need a manual sleep here because we are waiting for a server response 
        # that generates new content, not just a page load event.
        time.sleep(5) # Wait for 5 seconds for the server to process the request and display the code
        
        result_field_selector = (By.XPATH, '//input[@readonly and @placeholder="HMSALVHD"]')
        result_element = wait.until(EC.presence_of_element_located(result_field_selector))
        
        # 9. Extract the code
        code_text = result_element.get_attribute('value').strip()

        if len(code_text) < 4:
             raise ValueError(f"Extraction failed. Resulted in: {code_text}. Code might be too short.")

        final_screenshot = io.BytesIO(driver.get_screenshot_as_png())
        
        return code_text, initial_screenshot, final_screenshot
            
    except Exception as e:
        logger.error(f"Raganork Automation failed in thread: {e}")
        
        # Capture a failure screenshot before quitting
        failure_screenshot = None
        if driver:
            try:
                failure_screenshot = io.BytesIO(driver.get_screenshot_as_png())
            except:
                pass # Ignore errors during failure screenshot
        
        # Raise the custom exception to be caught in the async wrapper
        failure = AutomationFailure(f"Automation sequence failed: {e}", failure_screenshot)
        failure.set_original_type(type(e))
        raise failure
        
    finally:
        if driver:
            driver.quit()
        logger.info("Raganork Browser closed in thread.")

# --- ASYNCHRONOUS COMMAND HANDLERS ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a welcome message and instructions on /start."""
    await update.message.reply_html(
        "👋 Welcome! I am your multi-service pairing code bot.\n\n"
        "Available Commands:\n"
        "1. **Levanter:** <code>/pairlevanter +123...</code> (URL: {})\n"
        "2. **Raganork:** <code>/pairrag +123...</code> (URL: {})\n\n"
        "Please use the full international number format (e.g., +23480...)".format(URL_LEVANTER, URL_RAGANORK)
    )

async def pair_levanter_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /pairlevanter command."""
    await update.message.reply_text("❌ Levanter automation is currently disabled due to complex redirect issues. Please use the /pairrag command.")

async def pair_raganork_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /pairrag command."""
    if not context.args:
        await update.message.reply_text("❌ Error: Please provide the mobile number. Example: /pairrag +2348012345678")
        return
    mobile_number = context.args[0].strip()
    
    # Pre-check format
    if not re.match(r"^\+\d{1,4}\d{6,14}$", mobile_number):
         await update.message.reply_text("❌ Raganork: Invalid mobile number format. Must start with '+' and contain country code + digits.")
         return
         
    await update.message.reply_text(f"⏳ Processing Raganork request for `{mobile_number}`. This might take up to 45 seconds. Please wait...")
    
    try:
        # Start the synchronous Selenium task in a separate thread
        code_text, initial_screenshot, final_screenshot = await asyncio.to_thread(perform_raganork_pairing, mobile_number)

        # 1. Send initial screenshot for verification
        await context.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=initial_screenshot,
            caption="✅ INITIAL LOAD: Browser loaded successfully."
        )

        # 2. Send final success screenshot
        await context.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=final_screenshot,
            caption="✅ FINAL SUCCESS: Pairing code received."
        )
        
        # 3. Send the final code
        await update.message.reply_html(
            f"🎉 Raganork Code for <code>{mobile_number}</code>:\n\n<code>{code_text}</code>"
        )
            
    except AutomationFailure as e:
        # Handle custom failure exception
        error_type_name = e.original_exception_type.__name__
        logger.error(f"Raganork Automation failed with: {error_type_name} - {e}")

        await update.message.reply_text(
            f"❌ Raganork automation failed for `{mobile_number}`. Error: {error_type_name}. Check the screenshot below!"
        )
        
        # Send failure screenshot if available
        if e.screenshot_buffer:
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=e.screenshot_buffer,
                caption=f"⚠️ Automation stopped here. Error type: {error_type_name}."
            )
            
    except Exception as e:
        # Catch any other unexpected exceptions outside of the worker thread
        await update.message.reply_text(f"🚨 Critical Error in pairing task: {type(e).__name__} - {e}")
        logger.critical(f"Unhandled critical error in pairing task: {e}")


# --- Main Application Runner ---

def main() -> None:
    """Start the bot in Webhook mode for Heroku."""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN environment variable is not set. Exiting.")
        return
    if not WEBHOOK_URL_BASE:
        logger.error("WEBHOOK_URL_BASE environment variable is not set. Exiting.")
        return

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("pairlevanter", pair_levanter_command))
    application.add_handler(CommandHandler("pairrag", pair_raganork_command))

    app_url = WEBHOOK_URL_BASE
    
    logger.info(f"Running in Webhook mode on port {PORT}. Base URL: {app_url}")
    
    # Configure the webhook
    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TELEGRAM_BOT_TOKEN, 
        webhook_url=f"{app_url.rstrip('/')}/{TELEGRAM_BOT_TOKEN}"
    )

if __name__ == "__main__":
    main()
