# -*- coding: utf-8 -*-
"""
Stock Data Server - FastAPI entry point.

Usage:
    python -m stock_data.server

Or with uvicorn directly:
    uvicorn stock_data.server:app --host 0.0.0.0 --port 8888
"""

import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Load environment variables
load_dotenv()

from .api.routes import router
from . import __version__

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info(f"Starting Stock Data Server v{__version__}")
    logger.info(f"Server port: {os.getenv('SERVER_PORT', '8888')}")
    yield
    logger.info("Shutting down Stock Data Server")


# Create FastAPI app
app = FastAPI(
    title="Stock Data API",
    description="Local stock data aggregation server for AI agents",
    version=__version__,
    lifespan=lifespan,
    docs_url=None,  # Disable automatic docs
    redoc_url=None,
    openapi_url=None,
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routes
app.include_router(router, prefix="/api/v1")


def main():
    """Run the server."""
    import uvicorn

    port = int(os.getenv("SERVER_PORT", "8888"))
    host = os.getenv("SERVER_HOST", "0.0.0.0")

    logger.info(f"Starting server on {host}:{port}")
    uvicorn.run(
        "stock_data.server:app",
        host=host,
        port=port,
        reload=False,
    )


if __name__ == "__main__":
    main()
