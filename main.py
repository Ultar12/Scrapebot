import asyncio
import os
import logging
import re
import io
import time
from selenium import webdriver
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.firefox import GeckoDriverManager
from selenium.webdriver.firefox.service import Service as FirefoxService

from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.error import TelegramError

# --- Logging Setup ---
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- CONFIGURATION ---
PORT = int(os.environ.get("PORT", 8080))
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_URL_BASE = os.getenv("WEBHOOK_URL_BASE")

# Define target URLs
URL_LEVANTER = os.getenv("URL_LEVANTER", "https://levanter-delta.vercel.app/")
URL_RAGANORK = os.getenv("URL_RAGANORK", "https://session.raganork.site/")

# --- Selenium Setup ---
def find_firefox_binary():
    """Searches for the Firefox binary in common Heroku paths."""
    # Path installed by heroku-community/firefox buildpack
    paths = [
        "/app/vendor/firefox/firefox", # Common path for the community buildpack
        "/usr/bin/firefox"            # Default path (if apt worked)
    ]
    for path in paths:
        if os.path.exists(path):
            return path
    raise FileNotFoundError("Firefox binary not found in expected Heroku paths. Check buildpacks and Aptfile.")

def get_firefox_driver():
    """Initializes and returns a configured headless Firefox driver."""
    
    FIREFOX_BIN_PATH = find_firefox_binary()

    # Configure Firefox options for Heroku environment
    options = FirefoxOptions()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1280,720")
    
    # Set the binary location
    options.binary_location = FIREFOX_BIN_PATH

    # Initialize the GeckoDriver using webdriver_manager
    service = FirefoxService(GeckoDriverManager().install())
    
    # Initialize the WebDriver
    driver = webdriver.Firefox(service=service, options=options)
    
    return driver

# --- Telegram Command Handlers (omitted for brevity, assume correct) ---

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
    await update.message.reply_text(f"⏳ Processing Raganork request for `{mobile_number}`. This might take up to 45 seconds...")
    try:
        asyncio.create_task(raganork_pairing_automation_task(update, mobile_number, context))
    except Exception as e:
        await update.message.reply_text(f"🚨 Critical Error: Could not start the Raganork automation process. {e}")

# --- Automation Task 1: Levanter (Disabled) ---
async def levanter_pairing_automation_task(update: Update, mobile_number: str):
    # Disabled for stability
    pass 

# --- Automation Task 2: Raganork (Simpler Sequential Logic with Debugging) ---

async def raganork_pairing_automation_task(update: Update, mobile_number: str, context: ContextTypes.DEFAULT_TYPE):
    
    logger.info(f"Starting Raganork Selenium job for number: {mobile_number}")
    
    # Pre-process the number: separate country code and number body
    match = re.match(r"^\+(\d+)(.*)$", mobile_number)
    if not match:
        await update.message.reply_text("❌ Raganork: Invalid mobile number format.")
        return
        
    country_code = f"+{match.group(1)}"
    number_body = match.group(2)
    if number_body.startswith('0'):
        number_body = number_body[1:]
    
    driver = None
    try:
        # Initialize the driver
        driver = await asyncio.to_thread(get_firefox_driver)
        wait = WebDriverWait(driver, 20) # 20 second wait timeout
        
        # 1. Navigate and take INITIAL screenshot
        driver.get(URL_RAGANORK) 
        logger.info("Navigated to Raganork homepage.")

        # --- INITIAL DEBUG SCREENSHOT ---
        screenshot_buffer = io.BytesIO(driver.get_screenshot_as_png())
        await context.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=screenshot_buffer,
            caption="✅ INITIAL LOAD: This is what the browser sees."
        )
        # --- END INITIAL DEBUG SCREENSHOT ---

        # 2. Click 'Enter code' button
        enter_code_selector = (By.XPATH, '//button[contains(text(), "Enter code")]')
        wait.until(EC.element_to_be_clickable(enter_code_selector)).click()
        logger.info("Clicked 'Enter code'.")
        
        # 3. Click the country code dropdown to open the list
        country_dropdown_selector = (By.XPATH, '//div[contains(@class, "country-code-select")]') 
        wait.until(EC.element_to_be_clickable(country_dropdown_selector)).click()
        logger.info("Clicked country code dropdown.")

        # 4. Select the correct country code
        country_code_option_selector = (By.XPATH, f'//li[text()="{country_code}"]')
        wait.until(EC.presence_of_element_located(country_code_option_selector)).click()
        logger.info(f"Selected country code: {country_code}.")
        
        # 5. Input the phone number body
        phone_input_selector = (By.XPATH, '//input[@placeholder="Enter phone number"]')
        wait.until(EC.presence_of_element_located(phone_input_selector)).send_keys(number_body)
        logger.info(f"Inputted number body: {number_body}")

        # 6. Click 'GET CODE'
        get_code_button_selector = (By.XPATH, '//button[contains(text(), "GET CODE")]')
        wait.until(EC.element_to_be_clickable(get_code_button_selector)).click()
        logger.info("Clicked 'GET CODE'.")
        
        # 7. Wait for the result modal to appear (the readonly input field)
        result_field_selector = (By.XPATH, '//input[@readonly]')
        result_element = wait.until(EC.presence_of_element_located(result_field_selector))
        
        # 8. Extract the code
        code_text = result_element.get_attribute('value').strip()

        if len(code_text) < 4:
             raise ValueError(f"Extraction failed. Resulted in: {code_text}")

        await update.message.reply_html(
            f"🎉 Raganork Code for <code>{mobile_number}</code>:\n\n<code>{code_text}</code>"
        )
            
    except Exception as e:
        logger.error(f"Raganork Automation failed: {e}")
        
        # --- DEBUGGING: TAKE SCREENSHOT ON FINAL FAILURE ---
        if driver:
            screenshot_buffer = io.BytesIO(driver.get_screenshot_as_png())
            
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=screenshot_buffer,
                caption=f"❌ Raganork Failure! Automation stopped here. Error: {type(e).__name__}. Share this final image with me."
            )
        
        # Also send a text error message
        await update.message.reply_text(
            f"❌ Raganork automation failed for `{mobile_number}`. Error: {type(e).__name__}. Check the screenshot above!"
        )
            
    finally:
        if driver:
            driver.quit()
        logger.info("Raganork Browser closed.")


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

    # Construct the app URL dynamically using the provided base URL
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
