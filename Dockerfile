# Use an official Python runtime as a parent image
FROM python:3.10-slim

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code into the container
COPY . .

# Expose the port the app runs on (Render uses 10000 by default)
EXPOSE 10000

# Set environment variables for better containerization
ENV PYTHONUNBUFFERED=1
ENV OPENROUTER_API_KEY=""

# Run the application
CMD ["uvicorn", "web_app:app", "--host", "0.0.0.0", "--port", "10000"]
