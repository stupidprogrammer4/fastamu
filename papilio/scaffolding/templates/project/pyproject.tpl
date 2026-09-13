[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "<<PKG>>"
version = "0.1.0"
description = <<DESCRIPTION>>
requires-python = ">=3.13"
dependencies = [
    "<<DEPENDENCY>>",
]

[project.optional-dependencies]
dev = [
    "papilio[test]",
    "ruff",
]

[tool.hatch.build.targets.wheel]
packages = ["<<PKG>>"]

[tool.fastapi]
entrypoint = "<<PKG>>.main:app"

[tool.ruff]
line-length = 79
target-version = "py313"

[tool.ruff.lint]
select = ["E", "F", "I", "W"]

[tool.ruff.lint.isort]
known-first-party = ["<<PKG>>"]
