import asyncio
import os
import httpx
import logging
from playwright.async_api import async_playwright
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# --- Logging Setup ---
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- CONFIGURATION ---
PORT = int(os.environ.get("PORT", 8080))
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL")
TARGET_URL = os.getenv("TARGET_URL", "https://levanter-delta.vercel.app/")

# List of common keywords/domains associated with ads/tracking to block
AD_BLOCK_DOMAINS = [
    "google-analytics", "doubleclick", "adservice", "googlesyndication", 
    "facebook.com/tr", "hotjar", "analytics", "cloudflareinsights",
    "fonts.gstatic.com"
]

# --- Playwright Request Handler (Fixes SyntaxError) ---

async def route_handler(route):
    """Aborts requests for known ad/tracker domains and non-essential assets."""
    is_non_essential = route.request.resource_type in ["image", "font", "media", "stylesheet"]
    is_ad_or_tracker = any(ad_domain in route.request.url for ad_domain in AD_BLOCK_DOMAINS)
    
    if is_non_essential or is_ad_or_tracker:
        await route.abort()
    else:
        await route.continue_() # Using route.continue_() for maximum compatibility


# --- Telegram Command Handlers (using the new `route_handler`) ---

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
        f"⏳ Processing request for number: `{mobile_number}`. This might take up to 30 seconds..."
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
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
        )
        page = await browser.new_page()

        # Register the clean route handler function
        await page.route("**/*", route_handler)
        logger.info("Ads and non-essential assets blocked.")

        try:
            await page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60000)
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

            # 3. Wait for the mobile number input modal to appear and fill the number
            input_box_selector = 'input[placeholder*="+1234567890"]'
            await page.wait_for_selector(input_box_selector, timeout=10000)
            await page.fill(input_box_selector, mobile_number)
            logger.info(f"Inputted mobile number: {mobile_number}")

            # 4. Click 'Generate Pairing Code'
            generate_button_selector = 'button:has-text("Generate Pairing Code")'
            await page.click(generate_button_selector)
            logger.info("Clicked 'Generate Pairing Code'.")

            # 5. Wait for the resulting pairing code
            result_code_selector = 'h2' 
            await page.wait_for_selector(result_code_selector, state='attached', timeout=25000)
            
            final_code = await page.inner_text(result_code_selector)
            code_text = final_code.strip()
            
            if len(code_text) > 50 or not code_text or "Error" in code_text:
                 # Basic check to see if the extraction was valid
                 raise ValueError("Extraction failed or returned an error message.")

            logger.info(f"Successfully extracted Pairing Code: {code_text}")
            
            await update.message.reply_html(
                f"🎉 Automation Complete! The pairing code for <code>{mobile_number}</code> is:\n\n"
                f"<code>{code_text}</code>"
            )
            
        except Exception as e:
            error_msg = f"Automation failed at {page.url if 'page' in locals() else 'unknown step'}. Error: {type(e).__name__} - {str(e)}"
            logger.error(error_msg)
            
            await update.message.reply_text(
                f"❌ Automation failed for `{mobile_number}`. \n\n"
                f"The process timed out or an element was not found. Please try again. \n\n"
                f"Error details: {type(e).__name__}"
            )
            
        finally:
            await browser.close()
            logger.info("Browser closed.")


# --- Main Application Runner ---

def main() -> None:
    """Start the bot in Webhook or Polling mode."""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN environment variable is not set. Exiting.")
        return

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Register handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("pairlevanter", pair_levanter_command))

    if RENDER_EXTERNAL_URL:
        # --- Webhook Mode (For Render Deployment) ---
        # The bot is set up to listen on the PORT provided by Render
        webhook_url = f"{RENDER_EXTERNAL_URL}/{TELEGRAM_BOT_TOKEN}"
        logger.info(f"Running in Webhook mode on port {PORT}. Webhook URL: {webhook_url}")
        
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=TELEGRAM_BOT_TOKEN,
            webhook_url=webhook_url
        )
    else:
        # --- Polling Mode (For Local Testing) ---
        logger.info("RENDER_EXTERNAL_URL not found. Running in Polling mode for local testing.")
        application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
```eof

---

## 2. `requirements.txt` (Dependencies)

This uses the corrected, available version of the Telegram library (`20.8`).

```text:Python Dependencies:requirements.txt
playwright
httpx
python-telegram-bot==20.8
```eof

---

## 3. `Dockerfile` (Environment Setup)

This is the standard, clean Docker configuration for Playwright.

```dockerfile:Playwright Environment:Dockerfile
# Use a Python image with pre-installed Chromium dependencies
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

# Set the working directory
WORKDIR /app

# Copy the dependency file and install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application code
COPY . .
```eof

---

## 4. `render.yaml` (Web Service Blueprint)

This uses the robust `web` service type and simple start command, which avoids all previous deployment errors.

```yaml:Render Deployment Blueprint (Web Service):render.yaml
# Render Blueprint for the Web Automation Web Service
services:
  - type: web
    name: pairing-code-bot
    env: docker
    dockerfilePath: Dockerfile
    autoDeploy: true 
    buildCommand: ""
    
    # Simple start command for the Telegram bot webhook server
    startCommand: "python main.py"
    
    # Render needs the web service to be open on the port defined by the PORT env var
    port: 8080 

    envVars:
      - key: TARGET_URL
        value: https://levanter-delta.vercel.app/
        
      # 🔐 SECRETS: sync: false means the value MUST be set in the Render dashboard UI.
      - key: TELEGRAM_BOT_TOKEN
        sync: false
```eof

---

**Final Action:** Commit all four of these files to your GitHub repository and trigger the final deployment on Render. Good luck! 🚀
