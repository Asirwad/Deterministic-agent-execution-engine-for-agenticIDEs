# Deterministic Agent Execution Engine

> **Production-ready runtime for agentic systems with full observability, cost tracking, and deterministic execution**

A robust execution engine designed to orchestrate AI agents with complete transparency, reproducibility, and control. Built for enterprises that need reliable, auditable, and cost-effective agentic workflows.

---

## 🎯 Overview

The Deterministic Agent Execution Engine provides a structured runtime for executing multi-step AI agent workflows with:

- **Deterministic Execution**: Every step is tracked, versioned, and reproducible
- **Cost Transparency**: Real-time cost tracking per step and per run
- **Human-in-the-Loop**: Approval workflows for sensitive operations
- **Full Observability**: Complete audit trail of all agent actions
- **Production-Ready**: Built with FastAPI, PostgreSQL, and async/await patterns

## ✨ Key Features

### 🔄 Structured Execution Flow
- **Goal-Driven Planning**: Define high-level goals and let the engine generate execution plans
- **Step-by-Step Execution**: Each step is an atomic, trackable unit of work
- **State Management**: Robust state transitions with validation and error handling
- **Retry & Recovery**: Built-in mechanisms for handling failures gracefully

### 💰 Cost Management
- **Per-Step Cost Tracking**: Monitor LLM costs at granular level
- **Token Usage Metrics**: Track input/output tokens for every LLM call
- **Cost Aggregation**: Get total cost breakdowns per run
- **Budget Controls**: (Coming soon) Set spending limits and alerts

### 🔐 Security & Compliance
- **Approval Workflows**: Require human approval for sensitive operations (file edits, command execution)
- **Audit Trail**: Complete history of all actions with timestamps
- **Immutable Logs**: All execution data persisted in PostgreSQL
- **Workspace Restrictions**: Sandboxed file operations within defined workspaces

### 🎨 Extensible Architecture
- **Pluggable Executors**: Easy to add new step types and executors
- **Smart Model Router Integration**: Automatic model selection based on task complexity
- **Custom Orchestration**: Not tied to any specific framework (LangGraph, etc.)
- **Microservice-Ready**: Designed to integrate with external services

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      FastAPI Application                     │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐            │
│  │  Routes    │  │ Services   │  │ Executors  │            │
│  │  (API)     │→ │ (Business) │→ │ (Workers)  │            │
│  └────────────┘  └────────────┘  └────────────┘            │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│                    PostgreSQL Database                       │
│  ┌────────────┐  ┌────────────┐                            │
│  │ AgentRun   │  │   Step     │                            │
│  │  (Runs)    │←→│  (Steps)   │                            │
│  └────────────┘  └────────────┘                            │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│              Smart Model Router (Microservice)               │
│         Intelligent LLM routing & cost optimization          │
└─────────────────────────────────────────────────────────────┘
```

### Core Components

#### 1. **AgentRun** - Execution Lifecycle
- Represents a single goal-driven execution
- Tracks overall status, metadata, and cost
- Contains ordered sequence of steps

**State Flow:**
```
CREATED → PLANNING → PLANNED → RUNNING → COMPLETED
                              ↓
                     AWAITING_APPROVAL → RUNNING
                              ↓
                           FAILED
```

#### 2. **Step** - Atomic Execution Unit
- Smallest executable unit (read file, analyze, edit, run command, etc.)
- Stores input/output as JSONB for flexibility
- Tracks cost, latency, and execution metadata

**Step Types:**
- `read_file` - Read file contents
- `analyze` - LLM-based analysis
- `edit_file` - Modify file contents (requires approval)
- `run_command` - Execute shell commands (requires approval)
- `summarize` - Generate summaries

#### 3. **Smart Model Router Integration**
- Automatic model selection based on task complexity
- Cost optimization through intelligent routing
- Supports multiple LLM providers (OpenAI, Anthropic, etc.)

## 🚀 Getting Started

### Prerequisites

- **Python**: 3.11 or higher
- **PostgreSQL**: 14 or higher
- **uv**: Fast Python package installer (recommended)

### Installation

1. **Clone the repository**
```bash
git clone <repository-url>
cd deterministic-agent-engine
```

2. **Create virtual environment**
```bash
python -m venv .venv
# On Windows
.venv\Scripts\activate
# On Unix/MacOS
source .venv/bin/activate
```

3. **Install dependencies**
```bash
# Using uv (recommended)
uv pip install -e ".[dev]"

# Or using pip
pip install -e ".[dev]"
```

4. **Set up environment variables**
```bash
cp .env.example .env
# Edit .env with your configuration
```

5. **Initialize the database**
```bash
# Run migrations
alembic upgrade head
```

6. **Start the server**
```bash
uvicorn src.main:app --reload
```

The API will be available at `http://localhost:8000`

## 📚 API Documentation

Once the server is running, visit:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

### Core Endpoints

#### Create Agent Run
```http
POST /v1/agent-runs
Content-Type: application/json

{
  "goal": "Analyze the codebase and suggest improvements"
}
```

#### Get Run Status
```http
GET /v1/agent-runs/{run_id}
```

#### Execute Next Step
```http
POST /v1/agent-runs/{run_id}/execute
```

#### Approve Step
```http
POST /v1/agent-runs/{run_id}/steps/{step_id}/approve
```

#### Get Cost Summary
```http
GET /v1/agent-runs/{run_id}/cost
```

## 🧪 Development

### Running Tests
```bash
pytest
```

### Code Quality
```bash
# Linting and formatting
ruff check .
ruff format .
```

### Database Migrations
```bash
# Create a new migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Rollback
alembic downgrade -1
```

## 📊 Database Schema

### AgentRun Table
| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| goal | Text | User-defined goal |
| status | Enum | Current run status |
| total_cost_usd | Float | Total cost in USD |
| created_at | Timestamp | Creation time |
| completed_at | Timestamp | Completion time |

### Step Table
| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| run_id | UUID | Foreign key to AgentRun |
| step_number | Integer | Order in sequence |
| step_type | Enum | Type of step |
| status | Enum | Current step status |
| input_data | JSONB | Step input |
| output_data | JSONB | Step output |
| cost_usd | Float | Step cost |
| started_at | Timestamp | Start time |
| completed_at | Timestamp | Completion time |

## 🛠️ Technology Stack

- **Framework**: FastAPI 0.115+
- **Database**: PostgreSQL with SQLAlchemy 2.0 (async)
- **Migrations**: Alembic
- **HTTP Client**: httpx (for Smart Model Router)
- **Validation**: Pydantic 2.10+
- **Testing**: pytest with pytest-asyncio
- **Code Quality**: Ruff

## 🗺️ Roadmap

### Phase 1: Foundation ✅
- [x] Database models and migrations
- [x] API routes structure
- [x] Basic project setup

### Phase 2: Core Execution (In Progress)
- [ ] Step executors implementation
- [ ] Smart Model Router integration
- [ ] Plan generation service
- [ ] Execution orchestration

### Phase 3: Advanced Features
- [ ] Streaming execution updates
- [ ] Parallel step execution
- [ ] Advanced retry mechanisms
- [ ] Cost optimization strategies

### Phase 4: Production Hardening
- [ ] Comprehensive error handling
- [ ] Performance optimization
- [ ] Security audit
- [ ] Load testing

## 🤝 Contributing

Contributions are welcome! Please follow these guidelines:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🙏 Acknowledgments

- Built with inspiration from modern agentic frameworks
- Designed for production use in enterprise environments
- Community feedback and contributions appreciated

---

**Built with ❤️ by the Agent Engine Team**
