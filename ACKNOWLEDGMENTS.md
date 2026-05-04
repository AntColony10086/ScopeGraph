# Acknowledgments

## Architectural inspiration

This project's multi-agent orchestration architecture was inspired by
[AIRobsProtector/AIconverstionSys](https://github.com/AIRobsProtector/AIconverstionSys).
That repository does not include a LICENSE file at the time of this writing.
**All source code in this repository was independently re-implemented**; no source files were copied.
Heartfelt thanks to the original author for the architectural ideas.

## Direct dependencies

### Backend (Python)

| Package | License | Role |
|---------|---------|------|
| [LangGraph](https://github.com/langchain-ai/langgraph) | MIT | Multi-agent orchestration framework |
| [LangChain](https://github.com/langchain-ai/langchain) | MIT | LLM abstraction layer |
| [FastAPI](https://github.com/tiangolo/fastapi) | MIT | Async web framework |
| [Pydantic](https://github.com/pydantic/pydantic) | MIT | Data validation |
| [Pydantic Settings](https://github.com/pydantic/pydantic-settings) | MIT | Config from env vars |
| [SQLAlchemy](https://www.sqlalchemy.org/) | MIT | ORM (async, MySQL) |
| [Neo4j Python Driver](https://github.com/neo4j/neo4j-python-driver) | Apache 2.0 | Async graph database client |
| [Redis-py](https://github.com/redis/redis-py) | MIT | Async Redis client |
| [bcrypt](https://github.com/pyca/bcrypt) | Apache 2.0 | Password hashing |
| [PyJWT](https://github.com/jpadilla/pyjwt) | MIT | JSON Web Token encoding |
| [sentence-transformers](https://github.com/UKPLab/sentence-transformers) | Apache 2.0 | Multilingual embeddings |
| [pdfplumber](https://github.com/jsvine/pdfplumber) | MIT | PDF parsing |
| [python-docx](https://github.com/python-openxml/python-docx) | MIT | DOCX parsing |
| [openpyxl](https://openpyxl.readthedocs.io/) | MIT | XLSX parsing |
| [tiktoken](https://github.com/openai/tiktoken) | MIT | Token counting |
| [pytest](https://github.com/pytest-dev/pytest) | MIT | Test framework |

### Frontend (TypeScript / Vue)

| Package | License | Role |
|---------|---------|------|
| [Vue 3](https://github.com/vuejs/core) | MIT | Reactive UI framework |
| [Vue Router](https://github.com/vuejs/router) | MIT | Client-side routing |
| [Pinia](https://github.com/vuejs/pinia) | MIT | State management |
| [Element Plus](https://github.com/element-plus/element-plus) | MIT | UI component library |
| [Axios](https://github.com/axios/axios) | MIT | HTTP client |
| [Vite](https://github.com/vitejs/vite) | MIT | Build tool |
| [TypeScript](https://github.com/microsoft/TypeScript) | Apache 2.0 | Type checker |

### Infrastructure

| | License | Role |
|-|---------|------|
| [Neo4j Community Edition](https://neo4j.com/licensing/) | GPLv3 | Graph database |
| [Redis](https://redis.io/) | BSD 3-Clause | In-memory cache (session) |
| [MySQL Community Server](https://www.mysql.com/) | GPLv2 | Relational DB (users) |

## Inspiration / non-code references

- [Microsoft GraphRAG](https://github.com/microsoft/graphrag) — design pattern of hybrid structured + unstructured retrieval
- LangGraph official cookbook examples — supervisor-with-handoffs pattern
- MiniMax public documentation — reasoning-model API quirks (`<think>` blocks, `function_calling` vs `json_schema`)
