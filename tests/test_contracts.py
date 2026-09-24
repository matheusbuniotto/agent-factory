from factory.contracts import Example, Review, Spec, Task


def test_simple_spec_is_buildable(spec: Spec):
    assert spec.gaps() == []


def test_simple_spec_without_acceptance(spec: Spec):
    assert spec.model_copy(update={"acceptance": []}).gaps() == ["missing acceptance"]


def test_standard_spec_needs_success_and_failure_examples(spec: Spec):
    standard = Spec.model_validate(
        spec.model_dump()
        | {
            "size": "standard",
            "out_of_scope": ["division"],
            "must_not_infer": ["no rounding"],
            "examples": [Example(name="ok", input="2, 3", expected="-1")],
        }
    )
    assert standard.gaps() == ["missing failure example"]


def test_spec_markdown_skips_empty_sections(spec: Spec):
    markdown = spec.to_markdown()
    assert markdown.startswith("# Add subtract")
    assert "## Scenarios" in markdown and "- Given 2 and 3" in markdown
    assert "## Open questions" not in markdown


def test_review_approved():
    assert Review(verdict="approve", summary="ok").approved
    assert not Review(verdict="request_changes", summary="no").approved


def test_task_markdown_links_its_source():
    task = Task(title="Fix login", body="It breaks.", source="issue", url="https://github.com/o/r/issues/1")
    assert task.to_markdown() == "# Fix login\n\nIt breaks.\n\nSource: https://github.com/o/r/issues/1\n"
