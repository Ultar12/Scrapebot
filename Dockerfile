# Use a Python image with pre-installed Chromium dependencies
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

# Set the working directory
WORKDIR /app

# Copy the dependency file and install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application code
COPY . .

# This Dockerfile is used by the Render Web Service blueprint
# The command is defined in render.yaml's startCommand
# No CMD is strictly needed here as the startCommand in render.yaml overrides it, 
# but it's often good practice to include one for a final fallback.
CMD ["gunicorn", "--bind", "0.0.0.0:$PORT", "main:app"]
