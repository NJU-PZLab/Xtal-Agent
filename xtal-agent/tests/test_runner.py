from crystal_agent.runner import run_command


def test_run_command_captures_success():
    result = run_command(["python", "-c", "print('hello')"])

    assert result.exit_code == 0
    assert result.stdout.strip() == "hello"
    assert result.stderr == ""
    assert result.duration_seconds >= 0


def test_run_command_captures_failure_without_raising():
    result = run_command(["python", "-c", "import sys; print('bad'); sys.exit(3)"])

    assert result.exit_code == 3
    assert result.stdout.strip() == "bad"
    assert result.duration_seconds >= 0


def test_run_command_with_stdin():
    result = run_command(["python", "-c", "import sys; print(sys.stdin.read())"], stdin="hello stdin")

    assert result.exit_code == 0
    assert result.stdout.strip() == "hello stdin"
