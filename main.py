import asyncio
import os
import logging
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
TARGET_URL = os.getenv("TARGET_URL", "https://levanter-delta.vercel.app/")

# List of common keywords/domains associated with ads/tracking to block
AD_BLOCK_DOMAINS = [
    "google-analytics", "doubleclick", "adservice", "googlesyndication", 
    "facebook.com/tr", "hotjar", "analytics", "cloudflareinsights",
    "fonts.gstatic.com", "yandex", "popup", "ad", "redirect" 
]

# --- Playwright Request Handler ---

async def route_handler(route):
    """Aborts requests for known ad/tracker domains and non-essential assets."""
    is_non_essential = route.request.resource_type in ["image", "font", "media", "stylesheet"]
    is_ad_or_tracker = any(ad_domain in route.request.url for ad_domain in AD_BLOCK_DOMAINS)
    
    if is_non_essential or is_ad_or_tracker:
        await route.abort()
    else:
        await route.continue_()

# --- Self-Correcting Navigation Function ---

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
        "👋 Welcome! I am the Levanter Pairing Code Bot.\n\n"
        "To start the process, use the command below, replacing <code>+1234567890</code> "
        "with the full international mobile number:\n\n"
        "<code>/pairlevanter +1234567890</code>"
    )

async def pair_levanter_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /pairlevanter command, extracts the number, and starts the job."""
    
    if not context.args:
        await update.message.reply_text(
            "❌ Error: Please provide the mobile number in international format.\n"
            "Example: /pairlevanter +1234567890"
        )
        return

    mobile_number = context.args[0].strip()
    
    if not mobile_number.startswith('+') or len(mobile_number) < 8:
        await update.message.reply_text(
            "❌ Error: The number format seems incorrect. It must start with '+' "
            "and include the country code (e.g., +15551234567)."
        )
        return

    await update.message.reply_text(
        f"⏳ Processing request for number: `{mobile_number}`. This might take up to 60 seconds..."
    )

    try:
        # Create a non-blocking task to run the long-running automation
        asyncio.create_task(pairing_code_automation_task(update, mobile_number))
    except Exception as e:
        logger.error(f"Failed to create automation task: {e}")
        await update.message.reply_text(f"🚨 Critical Error: Could not start the automation process. {e}")


# --- Core Automation Logic (Asynchronous) ---

async def pairing_code_automation_task(update: Update, mobile_number: str):
    """Performs the full asynchronous automation job and sends the result to Telegram."""
    
    logger.info(f"Starting Playwright job for number: {mobile_number}")
    
    async with async_playwright() as p:
        # Launching Chromium. We rely on Heroku/Aptfile for dependencies.
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
        )
        page = await browser.new_page()

        await page.route("**/*", route_handler)
        logger.info("Ads and non-essential assets blocked.")

        try:
            # Navigate to the target site
            await page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=75000) 
            logger.info("Navigated to homepage.")
            
            # 1. Click 'Session' (Uses safe click)
            session_selector = 'text="Session"'
            await safe_click_and_correct(page, session_selector, TARGET_URL)
            logger.info("Successfully clicked 'Session'.")
            
            # 2. Click 'Get Pairing Code' button (Uses safe click)
            get_code_button_selector = 'button:has-text("Get Pairing Code")'
            await page.wait_for_selector(get_code_button_selector, timeout=15000)
            await safe_click_and_correct(page, get_code_button_selector, TARGET_URL)
            logger.info("Successfully clicked 'Get Pairing Code'.")

            # 3. Fill the number (Wait for the input to appear)
            input_box_selector = 'input[placeholder*="+1234567890"]'
            await page.wait_for_selector(input_box_selector, timeout=15000)
            await page.fill(input_box_selector, mobile_number)
            logger.info(f"Inputted mobile number: {mobile_number}")

            # 4. Click 'Generate Pairing Code' (This should not redirect, so use standard click)
            generate_button_selector = 'button:has-text("Generate Pairing Code")'
            await page.click(generate_button_selector)
            logger.info("Clicked 'Generate Pairing Code'.")

            # 5. Wait for the resulting pairing code
            # Wait for the input box to become hidden, signifying form submission success.
            await page.wait_for_selector(input_box_selector, state='hidden', timeout=30000)
            
            # Now, grab the code.
            result_code_selector = 'h2' 
            await page.wait_for_selector(result_code_selector, state='attached', timeout=15000)
            
            final_code = await page.inner_text(result_code_selector)
            code_text = final_code.strip()
            
            if len(code_text) < 4 or len(code_text) > 50 or "Error" in code_text or "Mobile" in code_text:
                 raise ValueError(f"Extraction failed. Resulted in: {code_text}")

            logger.info(f"Successfully extracted Pairing Code: {code_text}")
            
            await update.message.reply_html(
                f"🎉 Automation Complete! The pairing code for <code>{mobile_number}</code> is:\n\n"
                f"<code>{code_text}</code>"
            )
            
        except Exception as e:
            error_msg = f"Automation failed. Error: {type(e).__name__} - {str(e)}"
            logger.error(error_msg)
            
            await update.message.reply_text(
                f"❌ Automation failed for `{mobile_number}`. \n\n"
                f"The web process failed to bypass the redirect or find a crucial element. Please verify the number and try again. \n\n"
                f"Error details: {type(e).__name__}"
            )
            
        finally:
            await browser.close()
            logger.info("Browser closed.")


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
