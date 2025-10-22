# Contributing to libcbus

Thank you for your interest in contributing to libcbus! This document provides guidelines and instructions for contributing to the project.

---

## Table of Contents

1. [Getting Started](#getting-started)
2. [Development Environment](#development-environment)
3. [Code Style](#code-style)
4. [Testing](#testing)
5. [Documentation](#documentation)
6. [Pull Request Process](#pull-request-process)
7. [Release Process](#release-process)
8. [Community](#community)

---

## Getting Started

### Prerequisites

- Python 3.7 or later
- Git
- Basic understanding of C-Bus protocol (helpful but not required)
- Familiarity with asyncio

### Fork and Clone

1. Fork the repository on GitHub
2. Clone your fork:
   ```bash
   git clone https://github.com/YOUR-USERNAME/cbus.git
   cd cbus
   ```
3. Add upstream remote:
   ```bash
   git remote add upstream https://github.com/mitchell-johnson/cbus.git
   ```

---

## Development Environment

### Setup

1. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   pip install -r requirements-tests.txt
   ```

3. Install in development mode:
   ```bash
   pip install -e .
   ```

### Using the Simulator

For development without physical hardware:

```bash
cd cbus-simulator
python -m simulator.run_simulator --host 127.0.0.1 --port 10001
```

In another terminal:
```bash
export CMQTTD_VERBOSITY=DEBUG
python -m cbus.protocol.pciprotocol -t 127.0.0.1:10001
```

### Using the Proxy

For debugging protocol communication:

```bash
cd cbus-proxy
python proxy.py --listen-port 10002 --target-host 192.168.1.100 --target-port 10001
```

Then connect your application to `localhost:10002` instead of the real CNI.

---

## Code Style

### Python Style Guide

We follow [PEP 8](https://www.python.org/dev/peps/pep-0008/) with some modifications:

- **Line length**: 100 characters (not 79)
- **Indentation**: 4 spaces (no tabs)
- **Quotes**: Use single quotes for strings unless double quotes avoid escaping
- **Imports**: Group imports (stdlib, third-party, local) with blank lines between groups

### Type Hints

- Add type hints to all new functions and methods
- Use `Optional[T]` for nullable types
- Use `Union[A, B]` when multiple types are acceptable
- Import types from `typing` module

**Example:**

```python
from typing import Optional, Union, Iterable

async def lighting_group_on(
    self,
    group_addr: Union[int, Iterable[int]],
    application_addr: Union[int, Application]
) -> Optional[bytes]:
    """
    Turns on lights for the given group address(es).

    Args:
        group_addr: Group address or list of addresses (0-255)
        application_addr: Application address to use

    Returns:
        Confirmation code if confirmation was requested, None otherwise

    Raises:
        ValueError: If group_addr is out of range or list is too long
        IOError: If transport is not connected
    """
    pass
```

### Docstrings

- Use Google-style docstrings
- Include parameter descriptions
- Document return values
- Document exceptions that can be raised
- Add examples for complex functions

**Example:**

```python
def calculate_checksum(data: bytes) -> int:
    """Calculate C-Bus checksum for given data.

    The checksum is calculated as: ((sum(bytes) & 0xFF) ^ 0xFF) + 1

    Args:
        data: The raw data to calculate checksum for

    Returns:
        The calculated checksum as an integer (0-255)

    Example:
        >>> data = b'\\x05\\x38\\x00\\x79\\x64'
        >>> calculate_checksum(data)
        150
    """
    pass
```

### Naming Conventions

- **Functions/Methods**: `snake_case`
- **Classes**: `PascalCase`
- **Constants**: `UPPER_SNAKE_CASE`
- **Private members**: `_leading_underscore`
- **Module-level private**: `_single_underscore_prefix`

### Formatting Tools

We use `yapf` for code formatting (config in `setup.cfg`):

```bash
# Format a file
yapf -i cbus/protocol/pciprotocol.py

# Format entire project
yapf -ir cbus/
```

### Linting

Use `pytype` for static type checking:

```bash
pytype cbus/
```

---

## Testing

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=cbus --cov-report=html

# Run specific test file
pytest tests/test_lighting.py

# Run specific test
pytest tests/test_lighting.py::TestLighting::test_on_command
```

### Writing Tests

#### Unit Tests

- Place tests in `tests/` directory
- Name test files `test_*.py`
- Use `unittest.TestCase` or pytest functions
- Use `parameterized` for data-driven tests

**Example:**

```python
import unittest
from parameterized import parameterized
from cbus.common import validate_ga

class TestGroupAddress(unittest.TestCase):
    @parameterized.expand([
        (0, True),
        (128, True),
        (255, True),
        (-1, False),
        (256, False),
    ])
    def test_validate_ga(self, addr, expected):
        """Test group address validation."""
        self.assertEqual(validate_ga(addr), expected)
```

#### Async Tests

Use pytest-asyncio for async tests:

```python
import pytest
from cbus.protocol.pciprotocol import PCIProtocol

@pytest.mark.asyncio
async def test_lighting_on():
    """Test lighting on command."""
    protocol = PCIProtocol(timesync_frequency=0)
    # Mock transport setup
    # ...
    conf_code = await protocol.lighting_group_on(1, Application.LIGHTING)
    assert conf_code is not None
```

#### Integration Tests

Mark integration tests so they can be run separately:

```python
@pytest.mark.integration
async def test_mqtt_to_cbus_integration():
    """Test complete MQTT to C-Bus flow."""
    # Start simulator, MQTT broker, etc.
    pass
```

Run only unit tests:
```bash
pytest -m "not integration"
```

Run all tests including integration:
```bash
pytest
```

### Test Coverage Requirements

- All new code should have tests
- Aim for >80% code coverage
- Critical paths should have >95% coverage
- Don't sacrifice test quality for coverage numbers

---

## Documentation

### Code Documentation

- Add docstrings to all public functions, methods, and classes
- Update docstrings when changing function signatures
- Include examples for complex functionality

### User Documentation

When adding features, update:

- `README.md`: If it affects installation or basic usage
- `docs/API_REFERENCE.md`: For API changes
- `docs/DOCUMENTATION_INDEX.md`: For new documentation files

### Architecture Documentation

For significant architectural changes:

1. Update `docs/COMPREHENSIVE_ARCHITECTURE.md`
2. Add sequence diagrams to `docs/DETAILED_FLOW_DIAGRAMS.md`
3. Update `docs/PROTOCOL_DEEP_DIVE.md` if protocol handling changes

---

## Pull Request Process

### Before Submitting

1. **Update your branch**:
   ```bash
   git fetch upstream
   git rebase upstream/main
   ```

2. **Run tests**:
   ```bash
   pytest
   ```

3. **Check code style**:
   ```bash
   yapf -dr cbus/
   pytype cbus/
   ```

4. **Update documentation**:
   - Add/update docstrings
   - Update relevant .md files

5. **Write good commit messages**:
   ```
   Short summary (50 chars or less)

   More detailed explanation if needed. Wrap at 72 characters.

   - Bullet points are okay
   - Use present tense ("Add feature" not "Added feature")
   - Reference issues: Fixes #123
   ```

### Submitting

1. Push to your fork:
   ```bash
   git push origin feature-branch-name
   ```

2. Create Pull Request on GitHub

3. Fill out the PR template:
   - Describe what the PR does
   - Link to related issues
   - Note any breaking changes
   - Include testing steps

### Review Process

1. Automated checks will run (tests, linting)
2. A maintainer will review your code
3. Address any feedback
4. Once approved, a maintainer will merge

### PR Checklist

- [ ] Tests pass locally
- [ ] New tests added for new functionality
- [ ] Documentation updated
- [ ] Code follows style guide
- [ ] No new warnings from pytype
- [ ] Commit messages are clear
- [ ] Branch is up to date with main

---

## Release Process

*Note: Only for maintainers*

### Version Numbering

We use semantic versioning (MAJOR.MINOR.PATCH):

- **MAJOR**: Breaking changes
- **MINOR**: New features (backward compatible)
- **PATCH**: Bug fixes (backward compatible)

### Release Steps

1. Update version in `setup.py`

2. Update `CHANGELOG.md`:
   ```markdown
   ## [0.3.0] - 2024-01-15

   ### Added
   - New feature X

   ### Changed
   - Improved Y

   ### Fixed
   - Bug Z
   ```

3. Create release commit:
   ```bash
   git add setup.py CHANGELOG.md
   git commit -m "Release version 0.3.0"
   ```

4. Tag the release:
   ```bash
   git tag -a v0.3.0 -m "Version 0.3.0"
   git push origin main --tags
   ```

5. Create GitHub release from tag with changelog excerpt

6. Build and upload to PyPI:
   ```bash
   python setup.py sdist bdist_wheel
   twine upload dist/*
   ```

---

## Community

### Getting Help

- **Issues**: For bug reports and feature requests
- **Discussions**: For questions and general discussion
- **Email**: mitchell@johnson.fyi

### Reporting Bugs

When reporting bugs, include:

1. **Environment**:
   - Python version
   - Operating system
   - libcbus version
   - C-Bus hardware (PCI model)

2. **Steps to reproduce**:
   - Minimal code example
   - Configuration used
   - Expected vs actual behavior

3. **Logs**:
   ```bash
   export CMQTTD_VERBOSITY=DEBUG
   cmqttd ... > debug.log 2>&1
   ```
   Include relevant portions of the log

### Feature Requests

When requesting features:

- Describe the use case
- Explain why existing functionality doesn't work
- Provide examples of how you'd like to use it
- Consider submitting a PR!

### Code of Conduct

- Be respectful and inclusive
- Provide constructive feedback
- Focus on what is best for the community
- Show empathy towards other community members

---

## Development Tips

### Debugging

Enable debug logging:
```bash
export CMQTTD_VERBOSITY=DEBUG
```

Use the proxy to see protocol communication:
```bash
cd cbus-proxy
python proxy.py --listen-port 10002 --target-host YOUR_CNI --target-port 10001
```

### Common Tasks

**Add a new packet type:**
1. Create `cbus/protocol/new_packet.py`
2. Subclass `BasePacket`
3. Implement `decode_packet()` and `encode_packet()`
4. Add tests in `tests/test_new_packet.py`
5. Update packet dispatcher in `packet.py`

**Add a new application:**
1. Create `cbus/protocol/application/new_app.py`
2. Create SAL classes
3. Add event handlers to `PCIProtocol`
4. Add tests
5. Update documentation

**Add a new event handler:**
1. Add method to `PCIProtocol` (e.g., `on_new_event()`)
2. Call it from `handle_cbus_packet()`
3. Override in subclasses as needed
4. Add tests
5. Document in API reference

---

## Questions?

If you have questions not covered here, please:

1. Check existing documentation in `docs/`
2. Search existing issues
3. Open a new issue with the "question" label
4. Email the maintainers

---

Thank you for contributing to libcbus!
