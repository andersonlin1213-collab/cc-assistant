from src.rules.loader import RulesLoader


def test_load_rules(tmp_path):
    """Loader reads skills/rules.md content."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    rules_file = skills_dir / "rules.md"
    rules_file.write_text("# Agent Rules\n\nBe helpful.\n", encoding="utf-8")

    loader = RulesLoader(skills_dir)
    content = loader.load()

    assert "Agent Rules" in content
    assert "Be helpful" in content


def test_load_picks_up_edits(tmp_path):
    """Each load() call re-reads the file from disk (no caching)."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    rules_file = skills_dir / "rules.md"
    rules_file.write_text("v1", encoding="utf-8")

    loader = RulesLoader(skills_dir)
    assert loader.load() == "v1"

    rules_file.write_text("v2", encoding="utf-8")
    assert loader.load() == "v2"


def test_load_missing_returns_empty(tmp_path):
    """If skills/rules.md does not exist, loader returns empty string (no crash)."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()

    loader = RulesLoader(skills_dir)
    assert loader.load() == ""
