import asyncio
import os
import httpx
from playwright.async_api import async_playwright
from flask import Flask, jsonify

# --- ENVIRONMENT CONFIGURATION ---
TARGET_URL = os.getenv("TARGET_URL", "https://levanter-delta.vercel.app/")
MOBILE_NUMBER = os.getenv("MOBILE_NUMBER") 
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
PORT = os.getenv("PORT", 8080) # Render provides the PORT variable

# List of common keywords/domains associated with ads/tracking to block
AD_BLOCK_DOMAINS = [
    "google-analytics", "doubleclick", "adservice", "googlesyndication", 
    "facebook.com/tr", "hotjar", "analytics", "cloudflareinsights"
]

app = Flask(__name__)


# --- Telegram Integration Function ---

async def send_telegram_message(code: str, status: str = "✅ Success"):
    """Sends the extracted pairing code (or an error) to a Telegram chat."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Telegram environment variables are not set. Skipping message forwarding.")
        return

    message = f"*{status}* in Web Automation Job\n\n"
    
    if status == "✅ Success":
        message += (
            f"The requested pairing code is:\n\n`{code.strip()}`\n\n"
            f"URL: {TARGET_URL}\n"
            f"Phone: {MOBILE_NUMBER}"
        )
    else:
        message += f"Error Details: {code}\n"
        
    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    
    # Use synchronous httpx in this context, as the main automation is run via asyncio.run
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                api_url, 
                json={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": message,
                    "parse_mode": "Markdown"
                }
            )
            response.raise_for_status()
            print(f"📡 Telegram message sent successfully to chat ID {TELEGRAM_CHAT_ID}.")
    except Exception as e:
        print(f"❌ Failed to send Telegram message: {e}")


# --- Core Automation Logic (Asynchronous) ---

async def pairing_code_automation_task():
    """Performs the full asynchronous automation job."""
    if not MOBILE_NUMBER:
        error_msg = "MOBILE_NUMBER environment variable is not set."
        await send_telegram_message(error_msg, status="❌ Configuration Error")
        return {"status": "error", "message": error_msg}

    print(f"🚀 Starting automation on {TARGET_URL}...")
    final_result = {"status": "error", "message": "Automation failed before completion."}
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
        )
        page = await browser.new_page()

        # --- OPTIMIZATION: Block ads and non-essential resources ---
        await page.route("**/*", lambda route: route.abort() 
                         if route.request.resource_type in ["image", "font", "media", "stylesheet"] 
                         or any(ad_domain in route.request.url for ad_domain in AD_BLOCK_DOMAINS)
                         else route.continue())
        print("🛡️ Blocking ads, images, and non-essential assets.")

        try:
            await page.goto(TARGET_URL, wait_until="domcontentloaded")
            print("➡️ Navigated to homepage.")

            # Click 'Session'
            session_selector = 'text="Session"'
            await page.click(session_selector)
            print("🖱️ Clicked 'Session' link.")
            
            # Click 'Get Pairing Code'
            get_code_button_selector = 'button:has-text("Get Pairing Code")'
            await page.wait_for_selector(get_code_button_selector, timeout=10000)
            await page.click(get_code_button_selector)
            print("🖱️ Clicked 'Get Pairing Code'.")

            # Input the mobile number
            input_box_selector = 'input[placeholder*="+1234567890"]'
            await page.wait_for_selector(input_box_selector, timeout=10000)
            await page.fill(input_box_selector, MOBILE_NUMBER)
            print(f"⌨️ Inputted mobile number: {MOBILE_NUMBER}")

            # Click 'Generate Pairing Code' (the second time)
            generate_button_selector = 'button:has-text("Generate Pairing Code")'
            await page.click(generate_button_selector)
            print("🖱️ Clicked 'Generate Pairing Code'. Waiting for the result code...")

            # Wait for the resulting code
            result_code_selector = 'h2.pairing-code-display' 
            await page.wait_for_selector(result_code_selector, state='attached', timeout=20000)
            
            # Extract the code
            final_code = await page.inner_text(result_code_selector)
            code_text = final_code.strip()
            
            print(f"⭐ Extracted Pairing Code: {code_text}")
            
            # Forward the code to Telegram
            await send_telegram_message(code_text)
            
            final_result = {"status": "success", "message": "Automation finished successfully.", "code": code_text}

        except Exception as e:
            error_msg = f"Automation Error: {type(e).__name__}: {str(e)}"
            print(f"❌ {error_msg}")
            await send_telegram_message(error_msg, status="🚨 Runtime Failure")
            final_result = {"status": "error", "message": error_msg}
            
        finally:
            await browser.close()
            return final_result


# --- Flask Route to Trigger the Job ---

@app.route('/run', methods=['GET'])
def run_job():
    """Runs the asynchronous job synchronously when the /run endpoint is accessed."""
    print("Received request to run automation job...")
    # Use asyncio.run to execute the async Playwright task
    # Note: This blocks the Flask process until the job completes.
    result = asyncio.run(pairing_code_automation_task())
    return jsonify(result), 200 if result['status'] == 'success' else 500


# --- Flask Root Endpoint ---

@app.route('/', methods=['GET'])
def home():
    """Simple health check endpoint."""
    return jsonify({
        "status": "online", 
        "message": "Service is running. Hit /run to start the automation job."
    })


if __name__ == '__main__':
    # When running locally, Flask runs directly.
    # In production (Render), Gunicorn runs the app.
    app.run(host='0.0.0.0', port=PORT)
