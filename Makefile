# SQLite CDC 同步引擎 - 开发命令

.PHONY: all install install-dev test test-unit test-integration lint format mypy clean build publish help

# 默认目标
all: help

# 安装
install:
	pip install -e .

install-dev:
	pip install -e ".[dev]"

# 测试
test:
	pytest tests/ -v

test-unit:
	pytest tests/unit/ -v

test-integration:
	pytest tests/integration/ -v

test-cov:
	pytest tests/ --cov=sqlite_cdc --cov-report=term-missing --cov-report=html

# 代码检查
lint:
	ruff check src/ tests/
	mypy src/sqlite_cdc/

# 格式化
format:
	ruff format src/ tests/
	ruff check --fix src/ tests/

# 类型检查
mypy:
	mypy src/sqlite_cdc/

# 清理
clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf .pytest_cache/
	rm -rf .mypy_cache/
	rm -rf .ruff_cache/
	rm -rf htmlcov/
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

# 构建
build: clean
	python -m build

# 发布（测试 PyPI）
publish-test:
	python -m twine upload --repository testpypi dist/*

# 发布（正式 PyPI）
publish:
	python -m twine upload dist/*

# 帮助
help:
	@echo "SQLite CDC 同步引擎 - 开发命令"
	@echo ""
	@echo "安装:"
	@echo "  make install      - 安装包"
	@echo "  make install-dev  - 安装包及开发依赖"
	@echo ""
	@echo "测试:"
	@echo "  make test         - 运行所有测试"
	@echo "  make test-unit    - 运行单元测试"
	@echo "  make test-integration - 运行集成测试"
	@echo "  make test-cov     - 运行测试并生成覆盖率报告"
	@echo ""
	@echo "代码质量:"
	@echo "  make lint         - 运行代码检查 (ruff + mypy)"
	@echo "  make format       - 格式化代码"
	@echo "  make mypy         - 运行类型检查"
	@echo ""
	@echo "其他:"
	@echo "  make clean        - 清理构建产物"
	@echo "  make build        - 构建发布包"
	@echo "  make help         - 显示此帮助"
