"""Test configuration and fixtures."""
import asyncio
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Generator
from unittest.mock import patch
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
# Set test environment before importing app
os.environ["FRIDAY_DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["FRIDAY_ENCRYPTION_KEY"] = "dGVzdC1lbmNyeXB0aW9uLWtleS0zMi1ieXRlcw=="
from friday import database
from friday.database import engine, get_db
from friday.main import app
@pytest.fixture(scope="session")
def event_loop -> Generator[asyncio.AbstractEventLoop, None, None]:
 """Create event loop for async tests."""
 loop = asyncio.get_event_loop_policy.new_event_loop
 yield loop
 loop.close
@pytest_asyncio.fixture(scope="function")
async def db_session -> AsyncGenerator[AsyncSession, None]:
 """Create a test database session."""
 async with engine.begin as conn:
 await conn.run_sync(SQLModel.metadata.create_all)
 async with AsyncSession(engine, expire_on_commit=False) as session:
 yield session
 async with engine.begin as conn:
 await conn.run_sync(SQLModel.metadata.drop_all)
@pytest_asyncio.fixture(scope="function")
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
 """Create a test client with database session override.
 This also patches get_session for webhook handlers that use it directly.
 """
 async def override_get_db:
 yield db_session
 @asynccontextmanager
 async def override_get_session:
 """Override get_session to use the same test session."""
 yield db_session
 app.dependency_overrides[get_db] = override_get_db
 # Also patch get_session for webhook handlers
 with patch.object(database, "get_session", override_get_session):
 async with AsyncClient(
 transport=ASGITransport(app=app),
 base_url="http://test",
 ) as ac:
 yield ac
 app.dependency_overrides.clear
