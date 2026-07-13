from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
LOCAL_PREFIX = "/" + "home" + "/" + "b208"


def test_bundled_runtime_files_do_not_contain_local_absolute_paths():
    files_to_check = [
        REPO_ROOT / "crystal-agent" / "env" / "activate.sh",
        REPO_ROOT / "vendored_skills" / "msa-generator" / "scripts" / "run_msa.py",
        REPO_ROOT / "vendored_skills" / "af2-predictor" / "scripts" / "run_af2.py",
        REPO_ROOT / "vendored_skills" / "alphafold3-predictor" / "scripts" / "run_af3.py",
    ]

    for file_path in files_to_check:
        assert LOCAL_PREFIX not in file_path.read_text(), file_path
