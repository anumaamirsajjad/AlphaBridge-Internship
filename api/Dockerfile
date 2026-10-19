# Line-by-line notes: lines starting with # are comments. Docker ignores them.
# Docker does NOT allow comments after an instruction on the same line,
# so every comment in this file sits on its own line.
#
# What this file does:
#   Recipe that Docker follows to build the API image.
#   Each instruction below creates one layer of the image.
#   Built automatically by: docker compose up -d --build

# FROM: the starting image. Everything else is added on top of it.
# python:3.12-slim is the official, small Linux image with Python 3.12 installed.
FROM python:3.12-slim

# ENV: sets environment variables that stay in the image.
# PYTHONDONTWRITEBYTECODE=1: do not write .pyc cache files.
# PYTHONUNBUFFERED=1: send log messages immediately, so docker logs shows them live.
# PIP_NO_CACHE_DIR=1: do not keep downloaded packages, which keeps the image smaller.
# The backslash at the end of a line continues the same instruction on the next line.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# WORKDIR: the folder that later commands use. It is created if missing.
# All following commands run inside /app.
WORKDIR /app

# Copy only the requirements first. Docker reuses this layer when only code changes,
# so the packages are not downloaded again every time.
# COPY requirements.txt . : copy the file from the build folder into the current folder (/app).
COPY requirements.txt .
# RUN: run a command inside the image while it is being built.
# pip install installs every package listed in requirements.txt.
RUN pip install -r requirements.txt

# Copy the application code. .dockerignore keeps .venv, .env and tests out.
# COPY main.py database.py banking.py schemas.py ./ : copy the four app files into /app.
COPY main.py database.py banking.py schemas.py ./

# Create a normal user and run the app as that user, not as root.
# useradd --create-home: create the user and its home folder.
RUN useradd --create-home appuser
# USER: every following instruction, and the running app, uses this user.
USER appuser

# EXPOSE: documentation only. It says the app listens on port 8000.
# The compose file does the actual port mapping.
EXPOSE 8000

# CMD: the command that starts when the container starts.
# uvicorn main:app runs the app named "app" in main.py.
# --host 0.0.0.0 lets connections from outside the container reach the app.
# --port 8000 is the port it listens on inside the container.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
