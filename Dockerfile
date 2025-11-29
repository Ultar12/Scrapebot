# Render Blueprint for the Web Automation Worker
services:
  - type: worker
    name: pairing-code-scraper
    env: docker
    dockerfilePath: Dockerfile
    autoDeploy: false 
    buildCommand: ""
    # Removed the 'startCommand' line. Docker services must define the startup command 
    # only within the Dockerfile (which we do with CMD ["python", "main.py"]).
    envVars:
      # General Config (non-secret, value is explicit)
      - key: TARGET_URL
        value: https://levanter-delta.vercel.app/
        
      # 🔐 SECRETS - We use 'sync: false' to tell Render to treat these as secrets 
      # that must be entered on the dashboard. We remove the 'value: ""' placeholder
      # because you cannot specify both 'value' and 'sync' simultaneously.
      - key: MOBILE_NUMBER
        sync: false
      - key: TELEGRAM_BOT_TOKEN
        sync: false
      - key: TELEGRAM_CHAT_ID
        sync: false
