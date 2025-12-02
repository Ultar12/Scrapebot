// --- JAVASCRIPT IMPORTS ---
const TelegramBot = require('node-telegram-bot-api');
const puppeteer = require('puppeteer');
const os = require('os'); // To check platform if needed
const { createWriteStream } = require('fs');
const path = require('path');

// --- CONFIGURATION ---
const PORT = process.env.PORT || 8080;
const TELEGRAM_BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN;
const WEBHOOK_URL_BASE = process.env.WEBHOOK_URL_BASE;

// Define target URLs
const URL_LEVANTER = process.env.URL_LEVANTER || "https://levanter-delta.vercel.app/";
const URL_RAGANORK = process.env.URL_RAGANORK || "https://session.raganork.site/";

// --- Puppeteer Setup for Heroku/Headless Chrome ---

/**
 * Initializes and returns a configured headless Chrome browser instance.
 * @returns {Promise<puppeteer.Browser>} The configured browser instance.
 */
async function getPuppeteerBrowser() {
    // Note: Puppeteer automatically detects necessary paths on Heroku
    // if the Google Chrome buildpack is configured correctly.
    const browser = await puppeteer.launch({
        args: [
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-dev-shm-usage',
            '--disable-gpu',
            '--window-size=1280,720'
        ],
        headless: true, // Use 'new' for modern headless or 'true' for default
        // Executable path is crucial for Heroku. Puppeteer often handles this 
        // if the GOOGLE_CHROME_BIN env var is set by the buildpack.
        executablePath: process.env.GOOGLE_CHROME_BIN,
    });
    return browser;
}

// --- TELEGRAM HANDLERS ---

/**
 * Handles the /start command.
 */
async function start_command(msg) {
    const chatId = msg.chat.id;
    const welcomeMessage = `👋 **Welcome!** I am your multi-service pairing code bot.

Available Commands:
1. **Levanter:** \`/pairlevanter +123...\` (URL: ${URL_LEVANTER})
2. **Raganork:** \`/pairrag +123...\` (URL: ${URL_RAGANORK})

Please use the full international number format (e.g., +23480...)`;
    
    // Use parse_mode: 'Markdown' or 'HTML' for formatting
    await bot.sendMessage(chatId, welcomeMessage, { parse_mode: 'Markdown' });
}

/**
 * Handles the /pairlevanter command (currently disabled).
 */
async function pair_levanter_command(msg) {
    const chatId = msg.chat.id;
    await bot.sendMessage(chatId, "❌ Levanter automation is currently disabled due to complex redirect issues. Please use the /pairrag command.");
}

/**
 * Handles the /pairrag command.
 */
async function pair_raganork_command(msg, match) {
    const chatId = msg.chat.id;
    // match[1] is the text captured by the regex (the arguments)
    const args = match[1] ? match[1].trim().split(/\s+/) : [];
    
    if (args.length === 0 || !args[0]) {
        await bot.sendMessage(chatId, "❌ Error: Please provide the mobile number. Example: /pairrag +2348012345678");
        return;
    }
    
    const mobile_number = args[0];
    await bot.sendMessage(chatId, `⏳ Processing Raganork request for \`${mobile_number}\`. This might take up to 45 seconds...`, { parse_mode: 'Markdown' });
    
    // Start the automation task in the background
    try {
        await raganork_pairing_automation_task(chatId, mobile_number);
    } catch (e) {
        console.error(`🚨 Critical Error: Could not start the Raganork automation process. ${e.message}`);
        await bot.sendMessage(chatId, `🚨 Critical Error: Could not start the Raganork automation process. ${e.message}`);
    }
}

// --- Automation Task 2: Raganork (Using Puppeteer) ---

/**
 * Executes the Raganork web automation using Puppeteer.
 */
async function raganork_pairing_automation_task(chatId, mobile_number) {
    console.log(`Starting Raganork Puppeteer job for number: ${mobile_number}`);
    
    // Pre-process the number: separate country code and number body
    const match = mobile_number.match(/^\+(\d+)(.*)$/);
    if (!match) {
        await bot.sendMessage(chatId, "❌ Raganork: Invalid mobile number format. Must start with '+'.");
        return;
    }
        
    const country_code = `+${match[1]}`;
    // Strip leading '0' that might be left after stripping country code
    const number_body = match[2].replace(/^0+/, ''); 
    
    let browser;
    let page;
    let tempScreenshotPath; 
    
    try {
        browser = await getPuppeteerBrowser();
        page = await browser.newPage();
        page.setDefaultTimeout(25000); // 25 seconds timeout

        // 1. Navigate and take INITIAL screenshot
        await page.goto(URL_RAGANORK, { waitUntil: 'networkidle0' }); 
        console.log("Navigated to Raganork homepage.");

        // --- INITIAL DEBUG SCREENSHOT ---
        tempScreenshotPath = path.join(os.tmpdir(), `raganork_initial_${Date.now()}.png`);
        await page.screenshot({ path: tempScreenshotPath });
        await bot.sendPhoto(chatId, tempScreenshotPath, { caption: "✅ INITIAL LOAD: This is what the browser sees." });
        // --- END INITIAL DEBUG SCREENSHOT ---
        
        // 2. Click 'Enter code' button
        await page.waitForSelector('button', { text: 'Enter code' });
        // Note: Puppeteer uses page.waitForSelector for waiting, and page.click for clicking
        await page.click('xpath///button[contains(text(), "Enter code")]');
        console.log("Clicked 'Enter code'.");
        
        // 3. Click the country code dropdown to open the list
        await page.waitForSelector('.country-code-select');
        await page.click('.country-code-select');
        console.log("Clicked country code dropdown.");

        // 4. Select the correct country code
        // Note: The XPath needs adjustment for Puppeteer/JS string interpolation
        const countryCodeSelector = `xpath///li[contains(text(), "${country_code}")]`; 
        await page.waitForSelector(countryCodeSelector);
        await page.click(countryCodeSelector);
        console.log(`Selected country code: ${country_code}.`);
        
        // 5. Input the phone number body
        const phoneInputSelector = 'xpath///input[@placeholder="Enter phone number"]';
        await page.waitForSelector(phoneInputSelector);
        await page.type(phoneInputSelector, number_body);
        console.log(`Inputted number body: ${number_body}`);

        // 6. Click 'GET CODE'
        const getCodeButtonSelector = 'xpath///button[contains(text(), "GET CODE")]';
        await page.waitForSelector(getCodeButtonSelector);
        await page.click(getCodeButtonSelector);
        console.log("Clicked 'GET CODE'.");
        
        // 7. Wait for the result modal to appear (the readonly input field)
        const resultFieldSelector = 'xpath///input[@readonly]';
        // Wait a short extra time, analogous to Python's time.sleep(2)
        await new Promise(resolve => setTimeout(resolve, 2000)); 
        await page.waitForSelector(resultFieldSelector);
        
        // 8. Extract the code
        const code_text = await page.$eval(resultFieldSelector, el => el.value.trim());

        if (code_text.length < 4) {
             throw new Error(`Extraction failed. Resulted in: ${code_text}`);
        }

        await bot.sendMessage(chatId, 
            `🎉 Raganork Code for \`${mobile_number}\`:\n\n\`${code_text}\``,
            { parse_mode: 'Markdown' }
        );
            
    } catch (e) {
        console.error(`Raganork Automation failed: ${e.message}`);
        
        // --- DEBUGGING: TAKE SCREENSHOT ON FINAL FAILURE ---
        if (page) {
            await bot.sendMessage(chatId, 
                `❌ Raganork automation failed for \`${mobile_number}\`. Error: ${e.name || 'Error'}. Check the screenshot below!`,
                { parse_mode: 'Markdown' }
            );
            
            // Take final screenshot to a temporary path
            const finalScreenshotPath = path.join(os.tmpdir(), `raganork_final_${Date.now()}.png`);
            await page.screenshot({ path: finalScreenshotPath });
            
            await bot.sendPhoto(chatId, finalScreenshotPath, {
                caption: `⚠️ Automation stopped here. Error type: ${e.name || 'Error'}.`
            });

             // Clean up the final screenshot file
             require('fs').unlinkSync(finalScreenshotPath);
        }
        
    } finally {
        if (browser) {
            await browser.close();
        }
        // Clean up the initial screenshot file if it exists
        if (tempScreenshotPath && require('fs').existsSync(tempScreenshotPath)) {
            require('fs').unlinkSync(tempScreenshotPath);
        }
        console.log("Raganork Browser closed.");
    }
}


// --- Main Application Runner ---

if (!TELEGRAM_BOT_TOKEN) {
    console.error("TELEGRAM_BOT_TOKEN environment variable is not set. Exiting.");
    process.exit(1);
}
if (!WEBHOOK_URL_BASE) {
    console.error("WEBHOOK_URL_BASE environment variable is not set. Exiting.");
    process.exit(1);
}

// Create a bot instance
const bot = new TelegramBot(TELEGRAM_BOT_TOKEN, { polling: false });

function main() {
    
    // --- Set up Webhook ---
    const url = `${WEBHOOK_URL_BASE.replace(/\/+$/, '')}/${TELEGRAM_BOT_TOKEN}`;
    bot.setWebHook(url, {
        allowed_updates: ['message']
    })
    .then(() => {
        console.log(`✅ Webhook set to: ${url}`);
        
        // Start the web server to listen for Telegram updates
        const express = require('express');
        const app = express();
        
        app.use(express.json());
        
        // Route to handle updates from Telegram
        app.post(`/${TELEGRAM_BOT_TOKEN}`, (req, res) => {
            bot.processUpdate(req.body);
            res.sendStatus(200);
        });

        // Basic health check route
        app.get('/', (req, res) => {
            res.send('Bot is running.');
        });
        
        app.listen(PORT, () => {
            console.log(`🚀 Bot server listening on port ${PORT}`);
        });

    })
    .catch(error => {
        console.error(`❌ Could not set webhook: ${error.message}`);
        process.exit(1);
    });


    // --- Command Handlers ---
    // Note: Commands in JS/Node-Telegram-Bot-API use regex matching
    bot.onText(/\/start/, start_command);
    bot.onText(/\/pairlevanter/, pair_levanter_command);
    // Regex: Match /pairrag followed by any text (including number)
    bot.onText(/\/pairrag\s*(.*)/, pair_raganork_command); 

    // Error handling
    bot.on('polling_error', (error) => {
        console.error("Polling Error:", error);
    });

}

main();
