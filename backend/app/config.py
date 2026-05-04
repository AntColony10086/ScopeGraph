"""Application configuration — Pydantic Settings v2.

A single :class:`Settings` model owns every tunable. Values are loaded with
this precedence (highest first):

1. Process environment variables.
2. ``.env`` file in the working directory (encoded UTF-8).
3. Field defaults defined here.

Use :func:`get_settings` rather than instantiating :class:`Settings` directly —
the result is cached, so the file is parsed exactly once per process.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Strongly-typed runtime configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        # Tolerate keys we don't recognize so that downstream tooling can drop
        # extra entries in shared ``.env`` files without breaking startup.
        extra="ignore",
        case_sensitive=False,
    )

    # ----- LLM (OpenAI-compatible local server, e.g. LM Studio / Ollama) -----
    llm_base_url: str = Field(
        default="http://localhost:1234/v1",
        description="OpenAI-compatible chat-completions base URL.",
    )
    llm_api_key: str = Field(
        default="lm-studio",
        description="API key for the LLM server (often a placeholder for local models).",
    )
    llm_model: str = Field(
        default="local-model",
        description="Primary chat model identifier (used for answer generation).",
    )
    llm_light_model: str = Field(
        default="local-model",
        description="Lightweight model for routing / classification — should be cheap and fast.",
    )

    # Legacy: kept so old ``.env`` files don't fail validation.
    deepseek_api_key: str = Field(
        default="",
        description="(Deprecated) DeepSeek API key — retained for backward compatibility only.",
    )

    # ----- Neo4j: structured (relational data on the graph) -----
    neo4j_structured_uri: str = Field(
        default="bolt://localhost:7687",
        description="Bolt URI of the structured-data Neo4j instance.",
    )
    neo4j_structured_user: str = Field(
        default="neo4j",
        description="Username for the structured Neo4j instance.",
    )
    neo4j_structured_password: str = Field(
        default="",
        description="Password for the structured Neo4j instance.",
    )
    neo4j_structured_database: str = Field(
        default="structured",
        description="Database name inside the structured Neo4j instance.",
    )

    # ----- Neo4j: unstructured (GraphRAG over docs) -----
    neo4j_unstructured_uri: str = Field(
        default="bolt://localhost:7688",
        description="Bolt URI of the unstructured / GraphRAG Neo4j instance.",
    )
    neo4j_unstructured_user: str = Field(
        default="neo4j",
        description="Username for the unstructured Neo4j instance.",
    )
    neo4j_unstructured_password: str = Field(
        default="",
        description="Password for the unstructured Neo4j instance.",
    )
    neo4j_unstructured_database: str = Field(
        default="unstructured",
        description="Database name inside the unstructured Neo4j instance.",
    )

    # ----- Redis (session cache) -----
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL used for session state and short-term caches.",
    )
    redis_session_ttl: int = Field(
        default=1800,
        description="Session TTL in seconds (1800 = 30 minutes).",
        ge=60,
    )

    # ----- MySQL (long-term user / chat persistence) -----
    mysql_host: str = Field(
        default="localhost",
        description="MySQL host name or IP address.",
    )
    mysql_port: int = Field(
        default=3306,
        description="MySQL server port.",
        ge=1,
        le=65535,
    )
    mysql_user: str = Field(
        default="root",
        description="MySQL user name.",
    )
    mysql_password: str = Field(
        default="",
        description="MySQL password — leave empty for password-less local dev.",
    )
    mysql_database: str = Field(
        default="ai_customer_service",
        description="MySQL database / schema name.",
    )

    # ----- JWT (auth) -----
    jwt_secret_key: str = Field(
        default="change-me-in-production",
        description="HMAC secret used to sign access tokens — MUST be overridden in production.",
    )
    jwt_algorithm: str = Field(
        default="HS256",
        description="JWT signing algorithm (HS256 / HS384 / HS512 / RS256).",
    )
    jwt_expire_hours: int = Field(
        default=24,
        description="Lifetime of an issued access token, in hours.",
        ge=1,
    )

    # ----- HTTP server -----
    host: str = Field(
        default="0.0.0.0",
        description="Bind address for the FastAPI server.",
    )
    port: int = Field(
        default=8000,
        description="Bind port for the FastAPI server.",
        ge=1,
        le=65535,
    )
    debug: bool = Field(
        default=True,
        description="Enable verbose SQL echo and FastAPI debug mode.",
    )

    @property
    def mysql_url(self) -> str:
        """Compose the SQLAlchemy DSN for the configured MySQL instance."""
        return (
            f"mysql+aiomysql://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"
        )


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide :class:`Settings` singleton.

    Cached with :func:`functools.lru_cache` so the ``.env`` file is parsed
    exactly once and subsequent calls are O(1).
    """
    return Settings()
