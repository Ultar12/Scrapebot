import asyncio
import os
import httpx
from playwright.async_api import async_playwright

# --- CONFIGURATION (Loaded from Environment Variables) ---
# NOTE: In a cloud environment like Render, these are set in the dashboard/render.yaml
TARGET_URL = os.getenv("TARGET_URL", "https://levanter-delta.vercel.app/")
MOBILE_NUMBER = os.getenv("MOBILE_NUMBER") # e.g., "+15551234567"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# List of common keywords/domains associated with ads/tracking to block
AD_BLOCK_DOMAINS = [
    "google-analytics", "doubleclick", "adservice", "googlesyndication", 
    "facebook.com/tr", "hotjar", "analytics", "cloudflareinsights"
]

# --- Telegram Integration Function ---

async def send_telegram_message(code: str):
    """Sends the extracted pairing code to a Telegram chat."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Telegram environment variables are not set. Skipping message forwarding.")
        return

    message = (
        "✅ *Automation Job Complete*\n\n"
        f"The requested pairing code is:\n\n`{code.strip()}`\n\n"
        f"URL: {TARGET_URL}\n"
        f"Phone: {MOBILE_NUMBER}"
    )
    
    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    
    # Use exponential backoff for retries (simple version)
    max_retries = 3
    for attempt in range(max_retries):
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
                return
        except httpx.HTTPStatusError as e:
            print(f"❌ HTTP Error on Telegram API (Attempt {attempt + 1}/{max_retries}): {e.response.status_code} - {e.response.text}")
        except httpx.RequestError as e:
            print(f"❌ Network Error on Telegram API (Attempt {attempt + 1}/{max_retries}): {e}")
            
        if attempt < max_retries - 1:
            await asyncio.sleep(2 ** attempt) # Exponential backoff
        else:
            print("🛑 Failed to send Telegram message after multiple retries.")


# --- Main Automation Logic ---

async def pairing_code_automation():
    """
    Performs the full automation job: navigate, click buttons, input phone, extract code.
    """
    if not MOBILE_NUMBER:
        print("❌ Error: MOBILE_NUMBER environment variable is not set. Cannot run automation.")
        return

    # Using 'headless=True' for server deployment
    print(f"🚀 Starting automation on {TARGET_URL}...")
    async with async_playwright() as p:
        # Use Docker's required environment and launch arguments
        browser = await p.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox', 
                '--disable-setuid-sandbox', 
                '--disable-dev-shm-usage'
            ]
        )
        page = await browser.new_page()

        # --- OPTIMIZATION: Block ads and non-essential resources ---
        # This function checks resource type and URL keywords
        await page.route("**/*", lambda route: route.abort() 
                         if route.request.resource_type in ["image", "font", "media", "stylesheet"] 
                         or any(ad_domain in route.request.url for ad_domain in AD_BLOCK_DOMAINS)
                         else route.continue())
        print("🛡️ Blocking ads, images, and non-essential assets for speed and reliability.")
        # -------------------------------------------------------------

        try:
            # 1. Navigate to the initial page
            await page.goto(TARGET_URL, wait_until="domcontentloaded")
            print("➡️ Navigated to homepage.")

            # 2. Click on the 'Session' link/card
            session_selector = 'text="Session"'
            await page.click(session_selector)
            print("🖱️ Clicked 'Session' link.")
            
            # 3. Click the 'Get Pairing Code' button
            get_code_button_selector = 'button:has-text("Get Pairing Code")'
            await page.wait_for_selector(get_code_button_selector, timeout=10000)
            await page.click(get_code_button_selector)
            print("🖱️ Clicked 'Get Pairing Code'.")

            # 4. Wait for the mobile number input modal to appear
            input_box_selector = 'input[placeholder*="+1234567890"]'
            await page.wait_for_selector(input_box_selector, timeout=10000)
            
            # 5. Input the mobile number
            await page.fill(input_box_selector, MOBILE_NUMBER)
            print(f"⌨️ Inputted mobile number: {MOBILE_NUMBER}")

            # 6. Click 'Generate Pairing Code' button (in the modal)
            generate_button_selector = 'button:has-text("Generate Pairing Code")'
            await page.click(generate_button_selector)
            print("🖱️ Clicked 'Generate Pairing Code'. Waiting for the result code...")

            # 7. Synchronization & Extraction: Wait for the resulting code to appear
            # Best-guess selector for the final code display
            result_code_selector = 'h2.pairing-code-display' 
            
            # Wait for the result element to appear
            await page.wait_for_selector(result_code_selector, state='attached', timeout=20000)
            
            # Extract the code (trimming potential whitespace)
            final_code = await page.inner_text(result_code_selector)
            
            print(f"⭐ Extracted Pairing Code: {final_code.strip()}")
            
            # 8. Forward the code to Telegram
            await send_telegram_message(final_code)
            
            print("\n✅ Automation finished successfully.")


        except Exception as e:
            error_message = f"❌ AUTOMATION FAILED! An error occurred: {type(e).__name__}: {str(e)}"
            print(error_message)
            
        finally:
            # Ensure the browser is closed
            await browser.close()


if __name__ == '__main__':
    # Run the async function
    try:
        asyncio.run(pairing_code_automation())
    except Exception as e:
        print(f"A critical error occurred during script execution: {e}")
