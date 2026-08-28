#!/usr/bin/env python3
"""
Main entry point for Lending MVP Backend Server
FastAPI + Strawberry GraphQL Server
"""

import sys
import os

# Add project root to path
backend_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, backend_dir)
os.chdir(backend_dir)

print("Starting Lending MVP Backend Server...")
print(f"Backend root: {backend_dir}")

# Check if requirements are installed
try:
    import fastapi
    print("✓ FastAPI installed")
except ImportError:
    print("✗ FastAPI not installed - installing...")
    os.system('pip install fastapi uvicorn strawberry-graphql')

try:
    import uvicorn
    print("✓ Uvicorn installed")
except ImportError:
    print("✗ Uvicorn not installed - installing...")
    os.system('pip install uvicorn')

try:
    import strawberry
    print("✓ Strawberry GraphQL installed")
except ImportError:
    print("✗ Strawberry GraphQL not installed - installing...")
    os.system('pip install strawberry-graphql')

from fastapi import FastAPI, Request
from strawberry.fastapi import GraphQLRouter

# Import the GraphQL schema from app.graphql
import app.graphql as graphql_module
schema = getattr(graphql_module, 'schema', None)

if not schema:
    # Try to find the schema in Query class
    import strawberry
    @strawberry.type
    class DummyQuery:
        health: str = "ok"
    schema = strawberry.Schema(query=DummyQuery)
    print("Using dummy schema (full schema import failed)")

# Create FastAPI app
app = FastAPI(
    title="Lending MVP API",
    description="Banking application with multi-branch support and security controls",
    version="1.0.0"
)

# Include GraphQL router
graphql_app = GraphQLRouter(schema)
app.include_router(graphql_app, prefix="/graphql")

@app.get("/")
async def root():
    return {"message": "Lending MVP API is running", "docs": "/graphql"}

@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "lending-mvp-backend"}

if __name__ == "__main__":
    print("\nStarting server on http://0.0.0.0:3010")
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=3010,
        reload=True
    )