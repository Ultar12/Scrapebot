import asyncio
import os
import logging
import re
from playwright.async_api import async_playwright

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.error import TelegramError

# --- Logging Setup ---
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- CONFIGURATION ---
PORT = int(os.environ.get("PORT", 8080))
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_URL_BASE = os.getenv("WEBHOOK_URL_BASE")

# Define target URLs for the two services
URL_LEVANTER = os.getenv("URL_LEVANTER", "https://levanter-delta.vercel.app/")
URL_RAGANORK = os.getenv("URL_RAGANORK", "https://session.raganork.site/")

# List of common keywords/domains associated with ads/tracking to block
AD_BLOCK_DOMAINS = [
    "google-analytics", "doubleclick", "adservice", "googlesyndication", 
    "facebook.com/tr", "hotjar", "analytics", "cloudflareinsights",
    "fonts.gstatic.com", "yandex", "popup", "ad", "redirect" 
]

# --- Playwright Request Handler (Ad Blocker) ---

async def route_handler(route):
    """Aborts requests for known ad/tracker domains and non-essential assets."""
    is_non_essential = route.request.resource_type in ["image", "font", "media", "stylesheet"]
    is_ad_or_tracker = any(ad_domain in route.request.url for ad_domain in AD_BLOCK_DOMAINS)
    
    if is_non_essential or is_ad_or_tracker:
        await route.abort()
    else:
        await route.continue_()

# --- Self-Correcting Navigation Function for Levanter ---

async def safe_click_and_correct(page, selector, target_page_url, attempt=1):
    """
    Attempts to click a selector. If it results in a redirect, goes back and retries once.
    Returns True if the click was successful and the browser is on the correct page.
    """
    MAX_ATTEMPTS = 3
    if attempt > MAX_ATTEMPTS:
        raise TimeoutError(f"Failed to execute click on '{selector}' after {MAX_ATTEMPTS} attempts due to constant redirection.")
    
    logger.info(f"Click attempt {attempt} on selector: {selector}")
    
    try:
        # Click the element
        await page.click(selector, timeout=10000)
        
        # Give a small pause for any redirect to kick in
        await asyncio.sleep(0.5)
        
        # Check if the URL is still the base target URL (or the expected next URL)
        if page.url.startswith(target_page_url):
            logger.info(f"Click successful and remains on base URL: {page.url}")
            return True # Success
        else:
            # We were redirected to an ad/junk page
            logger.warning(f"Click on '{selector}' redirected to: {page.url}. Going back...")
            await page.go_back()
            
            # Now, retry the click
            return await safe_click_and_correct(page, selector, target_page_url, attempt + 1)
            
    except Exception as e:
        logger.error(f"Error during safe_click_and_correct: {e}")
        # If the click fails for another reason (e.g., element not found initially), let it propagate
        raise


# --- Telegram Command Handlers ---

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
    if not context.args:
        await update.message.reply_text("❌ Error: Please provide the mobile number. Example: /pairlevanter +1234567890")
        return
    mobile_number = context.args[0].strip()
    await update.message.reply_text(f"⏳ Processing Levanter request for `{mobile_number}`. This might take up to 60 seconds...")
    try:
        asyncio.create_task(levanter_pairing_automation_task(update, mobile_number))
    except Exception as e:
        await update.message.reply_text(f"🚨 Critical Error: Could not start the Levanter automation process. {e}")

async def pair_raganork_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /pairrag command."""
    if not context.args:
        await update.message.reply_text("❌ Error: Please provide the mobile number. Example: /pairrag +2348012345678")
        return
    mobile_number = context.args[0].strip()
    await update.message.reply_text(f"⏳ Processing Raganork request for `{mobile_number}`. This might take up to 45 seconds...")
    try:
        asyncio.create_task(raganork_pairing_automation_task(update, mobile_number))
    except Exception as e:
        await update.message.reply_text(f"🚨 Critical Error: Could not start the Raganork automation process. {e}")


# --- Automation Task 1: Levanter (High Redirect Risk) ---

async def levanter_pairing_automation_task(update: Update, mobile_number: str):
    # This task uses the complex self-correcting logic (safe_click_and_correct)
    
    logger.info(f"Starting Levanter Playwright job for number: {mobile_number}")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'])
        page = await browser.new_page()
        await page.route("**/*", route_handler)

        try:
            await page.goto(URL_LEVANTER, wait_until="domcontentloaded", timeout=75000) 
            
            # 1. Click 'Session' and handle redirection
            session_selector = 'text="Session"'
            await safe_click_and_correct(page, session_selector, URL_LEVANTER)
            
            # 2. Click 'Get Pairing Code' button and handle redirection
            get_code_button_selector = 'button:has-text("Get Pairing Code")'
            await page.wait_for_selector(get_code_button_selector, timeout=15000)
            await safe_click_and_correct(page, get_code_button_selector, URL_LEVANTER)

            # 3. Fill the number 
            input_box_selector = 'input[placeholder*="+1234567890"]'
            await page.wait_for_selector(input_box_selector, timeout=15000)
            await page.fill(input_box_selector, mobile_number)

            # 4. Click 'Generate Pairing Code' (standard click)
            generate_button_selector = 'button:has-text("Generate Pairing Code")'
            await page.click(generate_button_selector)

            # 5. Wait for the resulting pairing code
            await page.wait_for_selector(input_box_selector, state='hidden', timeout=30000)
            
            result_code_selector = 'h2' 
            await page.wait_for_selector(result_code_selector, state='attached', timeout=15000)
            
            final_code = await page.inner_text(result_code_selector)
            code_text = final_code.strip()
            
            if len(code_text) < 4 or "Error" in code_text:
                 raise ValueError(f"Extraction failed. Resulted in: {code_text}")

            await update.message.reply_html(
                f"🎉 Levanter Code for <code>{mobile_number}</code>:\n\n<code>{code_text}</code>"
            )
            
        except Exception as e:
            logger.error(f"Levanter Automation failed: {e}")
            await update.message.reply_text(
                f"❌ Levanter automation failed for `{mobile_number}`. Error: {type(e).__name__}"
            )
            
        finally:
            await browser.close()
            logger.info("Levanter Browser closed.")


# --- Automation Task 2: Raganork (Simpler Sequential Logic) ---

async def raganork_pairing_automation_task(update: Update, mobile_number: str):
    
    logger.info(f"Starting Raganork Playwright job for number: {mobile_number}")
    
    # Pre-process the number: separate country code and number body
    match = re.match(r"^\+(\d+)(.*)$", mobile_number)
    if not match:
        await update.message.reply_text("❌ Raganork: Invalid mobile number format.")
        return
        
    country_code = f"+{match.group(1)}"
    number_body = match.group(2)
    # Raganork requires removing a leading '0' if present in the number body
    if number_body.startswith('0'):
        number_body = number_body[1:]
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'])
        page = await browser.new_page()
        await page.route("**/*", route_handler)

        try:
            await page.goto(URL_RAGANORK, wait_until="domcontentloaded", timeout=45000) 
            logger.info("Navigated to Raganork homepage.")

            # 1. Click 'Enter code' button
            enter_code_selector = 'button:has-text("Enter code")'
            await page.click(enter_code_selector, timeout=10000)
            logger.info("Clicked 'Enter code'.")
            
            # 2. Click the country code dropdown to open the list
            country_dropdown_selector = 'div.country-code-select' # Assuming a generic selector for the dropdown
            await page.wait_for_selector(country_dropdown_selector, timeout=10000)
            await page.click(country_dropdown_selector)
            logger.info("Clicked country code dropdown.")

            # 3. Select the correct country code
            # Since the country list is long and scrollable, we target the specific text.
            country_code_option_selector = f'text="{country_code}"'
            await page.wait_for_selector(country_code_option_selector, timeout=10000)
            
            # Use keyboard interaction/scrolling if needed, but a direct click is usually more reliable
            await page.click(country_code_option_selector)
            logger.info(f"Selected country code: {country_code}.")
            
            # 4. Input the phone number body (without leading zero)
            phone_input_selector = 'input[placeholder="Enter phone number"]'
            await page.wait_for_selector(phone_input_selector, timeout=10000)
            await page.fill(phone_input_selector, number_body)
            logger.info(f"Inputted number body: {number_body}")

            # 5. Click 'GET CODE'
            get_code_button_selector = 'button:has-text("GET CODE")'
            await page.click(get_code_button_selector)
            logger.info("Clicked 'GET CODE'.")
            
            # 6. Wait for the result modal to appear
            # Assuming the result is displayed in a modal that appears after the button click.
            result_field_selector = 'input[readonly]'
            await page.wait_for_selector(result_field_selector, state='attached', timeout=30000)
            
            # Extract the code from the input field
            final_code = await page.get_attribute(result_field_selector, 'value')
            code_text = final_code.strip()

            if len(code_text) < 4:
                 raise ValueError(f"Extraction failed. Resulted in: {code_text}")

            await update.message.reply_html(
                f"🎉 Raganork Code for <code>{mobile_number}</code>:\n\n<code>{code_text}</code>"
            )
            
        except Exception as e:
            logger.error(f"Raganork Automation failed: {e}")
            await update.message.reply_text(
                f"❌ Raganork automation failed for `{mobile_number}`. Error: {type(e).__name__}"
            )
            
        finally:
            await browser.close()
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
