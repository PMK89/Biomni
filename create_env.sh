#!/bin/bash

# Create .env file from .env.example
if [ ! -f .env ]; then
    cp .env.example .env
    echo "\nA new .env file has been created from the template."
    echo "Please edit the .env file and add your actual credentials:"
    echo "- OPENAI_API_KEY"
    echo "- OPENAI_ENDPOINT"
    echo "- SESSION_SECRET (can be any random string for development)"
    
    # Generate a random session secret if none exists
    if grep -q "your_session_secret_here" .env; then
        SESSION_SECRET=$(openssl rand -hex 32)
        sed -i "s/your_session_secret_here/$SESSION_SECRET/" .env
        echo "\nA random SESSION_SECRET has been generated for you."
    fi
    
    echo "\nAfter editing, save the file and we'll continue with running the container."
else
    echo ".env file already exists. Please make sure it contains the required credentials."
fi
