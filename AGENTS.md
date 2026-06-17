# Agent Instructions

This document provides guidelines for AI agents working on this codebase.

## General Guidelines

- Every comment should end with a full stop.
- Do not add unnecessary comments.
- Use code block division with a blank line for best readability.
- Add a blank line before each `if` or `for` loop for readability.
- Do not create tests, examples, or run scripts without asking the user first.

## Technology Stack

- This repository uses **Django** as the web framework.
- This repository includes **Kubernetes (k8s)** configurations for deploying the application.

## Project Structure

### Shared App

The `shared` app is used for:

- Endpoints that are common across the entire project.
- All shared utility functions and modules.

## Endpoint Development

When creating a new endpoint or updating an existing endpoint:

- Automatically update the relevant documentation.
- Automatically update or create corresponding tests.

## Running Django Commands

- Always use **Docker Compose** to run any Django-related commands.
- Examples:
  - Migrations: `docker compose exec web python manage.py migrate`
  - Make migrations: `docker compose exec web python manage.py makemigrations`
  - Shell: `docker compose exec web python manage.py shell`

## Python Package Management

- This project uses **uv** for all dependency management.
- Dependencies are declared in `pyproject.toml` and locked in `uv.lock`.
- **Do not edit `uv.lock` by hand** and do not use pip directly.
- To add a new package:
  1. Add it to the `dependencies` list in `pyproject.toml`.
  2. Run `uv lock` locally to update `uv.lock`.
  3. Rebuild the Docker image: `docker compose up --build`.
- To remove a package: remove it from `pyproject.toml`, then run `uv lock`.
