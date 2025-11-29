import asyncio
import os
import httpx
import logging
from playwright.async_api import async_playwright
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# --- Logging Setup ---
# Use DEBUG for detailed Playwright output, INFO for general bot activity
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- ENVIRONMENT CONFIGURATION ---
# Render provides the PORT variable for web services
PORT = int(os.environ.get("PORT", 8080))
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TARGET_URL = os.getenv("TARGET_URL", "https://levanter-delta.vercel.app/")

# List of common keywords/domains associated with ads/tracking to block
AD_BLOCK_DOMAINS = [
    "google-analytics", "doubleclick", "adservice", "googlesyndication", 
    "facebook.com/tr", "hotjar", "analytics", "cloudflareinsights",
    "fonts.gstatic.com" # Can often slow down the initial load
]

# --- Telegram Command Handlers ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a welcome message and instructions on /start."""
    await update.message.reply_html(
        "👋 Welcome! I am the Levanter Pairing Code Bot.\n\n"
        "To start the process, use the command below, replacing `+1234567890` "
        "with the full international mobile number:\n\n"
        "<code>/pairlevanter +1234567890</code>"
    )

async def pair_levanter_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /pairlevanter command, extracts the number, and starts the job."""
    
    # 1. Check for mobile number argument
    if not context.args:
        await update.message.reply_text(
            "❌ Error: Please provide the mobile number in international format.\n"
            "Example: /pairlevanter +1234567890"
        )
        return

    mobile_number = context.args[0].strip()
    
    # Simple validation check
    if not mobile_number.startswith('+') or len(mobile_number) < 8:
        await update.message.reply_text(
            "❌ Error: The number format seems incorrect. It must start with '+' "
            "and include the country code (e.g., +15551234567)."
        )
        return

    await update.message.reply_text(
        f"⏳ Processing request for number: `{mobile_number}`. This might take up to 30 seconds..."
    )

    # 2. Run the asynchronous automation task in the background
    # We pass the mobile_number and the chat_id/update object for reply
    try:
        # We use asyncio.create_task to run the long-running automation 
        # without blocking the main Telegram application thread.
        asyncio.create_task(pairing_code_automation_task(update, mobile_number))
    except Exception as e:
        logger.error(f"Failed to create automation task: {e}")
        await update.message.reply_text(
            f"🚨 Critical Error: Could not start the automation process. {e}"
        )


# --- Core Automation Logic (Asynchronous) ---

async def pairing_code_automation_task(update: Update, mobile_number: str):
    """Performs the full asynchronous automation job and sends the result to Telegram."""
    
    logger.info(f"Starting Playwright job for number: {mobile_number}")
    
    async with async_playwright() as p:
        # Launch browser in headless mode for server efficiency
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
        )
        page = await browser.new_page()

        # --- OPTIMIZATION: Request Interception to block ads/trackers ---
        await page.route("**/*", lambda route: route.abort() 
                         if route.request.resource_type in ["image", "font", "media", "stylesheet"] 
                         or any(ad_domain in route.request.url for ad_domain in AD_BLOCK_DOMAINS)
                         else route.continue())
        logger.info("Ads and non-essential assets blocked.")

        try:
            await page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60000) # 60s timeout for navigation
            logger.info("Navigated to homepage.")
            
            # 1. Click 'Session'
            session_selector = 'text="Session"'
            await page.click(session_selector, timeout=10000)
            logger.info("Clicked 'Session'.")
            
            # 2. Click 'Get Pairing Code' button
            get_code_button_selector = 'button:has-text("Get Pairing Code")'
            await page.wait_for_selector(get_code_button_selector, timeout=10000)
            await page.click(get_code_button_selector)
            logger.info("Clicked 'Get Pairing Code'.")

            # 3. Wait for the mobile number input modal to appear
            input_box_selector = 'input[placeholder*="+1234567890"]'
            await page.wait_for_selector(input_box_selector, timeout=10000)
            await page.fill(input_box_selector, mobile_number)
            logger.info(f"Inputted mobile number: {mobile_number}")

            # 4. Click 'Generate Pairing Code' (the second time)
            generate_button_selector = 'button:has-text("Generate Pairing Code")'
            await page.click(generate_button_selector)
            logger.info("Clicked 'Generate Pairing Code'.")

            # 5. Wait for the resulting pairing code to appear on the screen
            # Based on the screenshot, let's use a robust selector like a general H2, hoping the code is there
            result_code_selector = 'h2' # May need adjustment if the code is in a specific element
            
            # Wait for the element to exist and be attached to the DOM
            await page.wait_for_selector(result_code_selector, state='attached', timeout=25000)
            
            # Extract the code
            final_code = await page.inner_text(result_code_selector)
            code_text = final_code.strip()
            
            if len(code_text) > 50 or not code_text:
                 # Check if the extracted text looks like a code or just a generic header
                 raise ValueError("Extracted text does not look like a valid pairing code.")

            logger.info(f"Successfully extracted Pairing Code: {code_text}")
            
            # Send Success message to user
            await update.message.reply_html(
                f"🎉 Automation Complete! The pairing code for `{mobile_number}` is:\n\n"
                f"<code>{code_text}</code>\n\n"
                f"You can now use this code in your device."
            )
            
        except Exception as e:
            error_msg = f"Automation Failed. Error: {type(e).__name__} - {str(e)}"
            logger.error(error_msg)
            
            # Send Failure message to user
            await update.message.reply_text(
                f"❌ Automation failed for `{mobile_number}`. \n\n"
                f"The web process timed out or an element was not found. "
                f"Please check the mobile number and try again later. \n\n"
                f"Error details: {type(e).__name__}"
            )
            
        finally:
            await browser.close()
            logger.info("Browser closed.")


# --- Main Application Runner ---

def main() -> None:
    """Start the bot."""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN environment variable is not set. Exiting.")
        return

    # Create the Application and pass it your bot's token.
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Get the URL of the deployed service from Render (must be set in ENV or passed by Render)
    # This is critical for Webhook setup
    render_url = os.environ.get("RENDER_EXTERNAL_URL")
    
    if render_url:
        # --- Webhook Mode (For Render Deployment) ---
        logger.info(f"Running in Webhook mode on port {PORT}. URL: {render_url}")
        
        # This tells Telegram where to send updates
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=TELEGRAM_BOT_TOKEN, # Use token as URL path for security
            webhook_url=f"{render_url}/{TELEGRAM_BOT_TOKEN}"
        )
    else:
        # --- Polling Mode (For Local Testing) ---
        # If RENDER_EXTERNAL_URL is not set, assume local development
        logger.info("RENDER_EXTERNAL_URL not found. Running in Polling mode for local testing.")
        application.run_polling(allowed_updates=Update.ALL_TYPES)
        
    # Register handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("pairlevanter", pair_levanter_command))

if __name__ == "__main__":
    main()
