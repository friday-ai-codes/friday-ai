## MODIFIED Requirements
### Requirement: Backend Framework Stack
The backend system SHALL be built using Django 6.0 with Django REST Framework for API development.
#### Scenario: Django project initialization
- **WHEN** the server application starts
- **THEN** Django ASGI application SHALL be initialized
- **AND** all configured Django apps SHALL be loaded
- **AND** database migrations SHALL be applied automatically
#### Scenario: REST API framework
- **WHEN** API endpoints are accessed
- **THEN** Django REST Framework SHALL handle request/response serialization
- **AND** authentication SHALL be enforced via JWT tokens
- **AND** appropriate HTTP status codes SHALL be returned
#### Scenario: Admin interface access
- **WHEN** an admin user accesses `/admin/`
- **THEN** Django Admin interface SHALL be displayed
- **AND** all registered models SHALL be manageable through the interface
### Requirement: Database Configuration
The system SHALL use SQLite database with Django ORM for data persistence.
#### Scenario: Database connection
- **WHEN** the application starts
- **THEN** Django SHALL connect to SQLite database file
- **AND** connection pooling SHALL be managed by Django
#### Scenario: Model migrations
- **WHEN** model definitions change
- **THEN** Django migrations SHALL be generated using `python manage.py makemigrations`
- **AND** migrations SHALL be applied using `python manage.py migrate`
### Requirement: Authentication System
The system SHALL use Django's built-in authentication with JWT token support via djangorestframework-simplejwt.
#### Scenario: User login
- **WHEN** valid credentials are provided to `/api/auth/login/`
- **THEN** JWT access and refresh tokens SHALL be returned
- **AND** access token SHALL be valid for 24 hours
- **AND** refresh token SHALL be valid for 7 days
#### Scenario: Token refresh
- **WHEN** a valid refresh token is provided to `/api/auth/refresh/`
- **THEN** a new access token SHALL be returned
#### Scenario: Protected endpoint access
- **WHEN** a request includes valid Bearer token in Authorization header
- **THEN** the request SHALL be authenticated
- **AND** the current user SHALL be available in the view
### Requirement: Async View Support
The system SHALL support asynchronous request handling for I/O-bound operations.
#### Scenario: Async task execution
- **WHEN** task execution is triggered via API
- **THEN** the view SHALL handle the request asynchronously
- **AND** Docker container operations SHALL be performed without blocking
#### Scenario: Async external API calls
- **WHEN** Feishu API is called
- **THEN** HTTP requests SHALL be made asynchronously using httpx
- **AND** response handling SHALL not block other requests
### Requirement: Configuration Management
The system SHALL use django-environ for environment-based configuration.
#### Scenario: Environment variable loading
- **WHEN** the application starts
- **THEN** configuration SHALL be loaded from environment variables
- **AND** `.env` file SHALL be supported for local development
#### Scenario: Required configuration validation
- **WHEN** required environment variables are missing
- **THEN** the application SHALL fail to start with a clear error message
### Requirement: Structured Logging
The system SHALL use structlog for structured logging, integrated with Django's logging system.
#### Scenario: Request logging
- **WHEN** an API request is processed
- **THEN** request details SHALL be logged in structured format
- **AND** log entries SHALL include request ID, user, and timing
#### Scenario: Log format by environment
- **WHEN** DEBUG mode is enabled
- **THEN** logs SHALL be formatted with colors for console readability
- **WHEN** DEBUG mode is disabled
- **THEN** logs SHALL be formatted as JSON for log aggregation
## ADDED Requirements
### Requirement: Production Deployment with Gunicorn + Uvicorn
The system SHALL be deployed in production using Gunicorn as the process manager with Uvicorn workers for ASGI support.
#### Scenario: Container startup
- **WHEN** the Docker container starts
- **THEN** Gunicorn SHALL be launched with Uvicorn worker class
- **AND** database migrations SHALL be applied automatically before starting the server
#### Scenario: Worker configuration
- **WHEN** the application runs in production
- **THEN** Gunicorn SHALL manage multiple worker processes
- **AND** each worker SHALL use `uvicorn.workers.UvicornWorker` for ASGI handling
- **AND** workers SHALL have a configurable timeout (default 120 seconds)
#### Scenario: Logging configuration
- **WHEN** the application is running
- **THEN** access logs SHALL be written to stdout
- **AND** error logs SHALL be written to stderr
- **AND** application output SHALL be captured in logs
### Requirement: Django App Structure
The backend SHALL be organized into modular Django apps for separation of concerns.
#### Scenario: App organization
- **WHEN** the codebase is examined
- **THEN** functionality SHALL be organized into distinct apps:
 - `core` for common models and utilities
 - `projects` for project and repository management
 - `tasks` for task lifecycle management
 - `webhooks` for webhook handling
 - `authentication` for auth endpoints
#### Scenario: App independence
- **WHEN** a Django app is modified
- **THEN** changes SHALL be isolated to that app's directory
- **AND** cross-app dependencies SHALL be through well-defined interfaces
## REMOVED Requirements
### Requirement: FastAPI Framework
**Reason**: Replaced by Django 6.0 + Django REST Framework
**Migration**: All FastAPI routes converted to Django REST Framework views
### Requirement: SQLModel ORM
**Reason**: Replaced by Django ORM
**Migration**: All SQLModel models converted to Django models
### Requirement: Alembic Migrations
**Reason**: Replaced by Django's built-in migration system
**Migration**: Use `python manage.py makemigrations` and `python manage.py migrate`
### Requirement: Pydantic Settings
**Reason**: Replaced by django-environ
**Migration**: Environment configuration moved to Django settings.py with django-environ
