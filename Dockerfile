# Use a Python image with pre-installed Chromium dependencies
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

# Set the working directory
WORKDIR /app

# Copy the dependency file and install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application code
COPY . .

# The CMD is not strictly needed for this webhook setup but serves as a general container instruction
CMD ["python", "main.py"]
