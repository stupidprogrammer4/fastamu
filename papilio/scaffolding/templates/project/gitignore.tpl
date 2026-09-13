# -----------------------------
# Python / FastAPI .gitignore
# -----------------------------

# Bytecode
__pycache__/
*.py[cod]
*$py.class

.claude

# Virtual envs
venv/
.venv/
env/
ENV/
.virtualenv/

# Environment variables / secrets
*.env
*.env.*
!.env.example
!.env.sample

# FastAPI / Uvicorn / Gunicorn logs
*.log
uvicorn.log

# Cache / tooling
.cache/
.pytest_cache/
mypy_cache/
coverage.xml
htmlcov/
*.cover
*.py,cover
.coverage
.coverage.*

# Build / dist
build/
dist/
*.egg-info/
.eggs/

# Static generated files (if using something like templating or builds)
staticfiles/
static/

# IDEs / editors
.idea/
.vscode/
*.swp
*.swo

# OS files
.DS_Store
Thumbs.db

# Docker stuff
docker-data/
docker-volume/

config.yml

*.lock
!frontend/package-lock.json
node_modules/
*.tsbuildinfo
*.zip

seed.sql

storage/*
storage/local/*
test.*

yoyo.ini

test-scripts/*

# uploaded media (runtime data)
media/

# graphify tool cache/output
graphify-out/
