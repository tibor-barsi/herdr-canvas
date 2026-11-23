"""NEW-02: the comparison of two versions of an HTML page by element id."""

from __future__ import annotations

import pytest

from agent_canvas.hub.changes import compare, count, diff

pytestmark = pytest.mark.unit

OLD = (
    "<html><head><title>t</title></head><body><h1>Report</h1>"
    '<canvas-plot data-canvas-id="plot"><script type="application/json">'
    '{"x": [1, 2]}</script></canvas-plot>'
    '<section id="notes"><p>Keep.</p></section></body></html>'
)


def test_new_02_one_blocks_config_changed_gives_that_id_as_changed() -> None:
    new = OLD.replace('{"x": [1, 2]}', '{"x": [1, 3]}')
    assert diff(OLD, new) == {
        "added": [], "changed": ["plot"], "removed": [], "outside": False,
    }  # fmt: skip


def test_new_02_a_new_section_gives_added() -> None:
    new = OLD.replace("</body>", '<section id="extra"><p>New.</p></section></body>')
    assert diff(OLD, new) == {
        "added": ["extra"], "changed": [], "removed": [], "outside": False,
    }  # fmt: skip


def test_new_02_a_removed_element_gives_removed() -> None:
    new = OLD.replace('<section id="notes"><p>Keep.</p></section>', "")
    assert diff(OLD, new) == {
        "added": [], "changed": [], "removed": ["notes"], "outside": False,
    }  # fmt: skip


def test_new_02_a_whitespace_only_change_gives_nothing() -> None:
    new = (
        OLD.replace("<h1>Report</h1>", "\n  <h1>  Report \n</h1>\n")
        .replace("<p>Keep.</p>", "\n<p>Keep.</p>\n")
        .replace('"x": [1, 2]', '"x":  [1,\n 2]')
    )
    assert new != OLD
    assert diff(OLD, new) == {
        "added": [], "changed": [], "removed": [], "outside": False,
    }  # fmt: skip


def test_new_02_a_change_outside_the_elements_with_an_id_is_flagged() -> None:
    result = diff(OLD, OLD.replace("<h1>Report</h1>", "<h1>Final report</h1>"))
    assert result == {"added": [], "changed": [], "removed": [], "outside": True}


def test_new_02_a_change_in_the_head_is_flagged_outside() -> None:
    result = diff(OLD, OLD.replace("<title>t</title>", "<title>u</title>"))
    assert result["outside"] is True


def test_new_02_data_canvas_id_wins_over_id_and_only_the_inner_element_is_changed() -> (
    None
):
    old = '<div id="card"><p data-canvas-id="inner" id="other">a</p><p>b</p></div>'
    new = old.replace(">a<", ">c<")
    assert diff(old, new) == {
        "added": [], "changed": ["inner"], "removed": [], "outside": False,
    }  # fmt: skip


def test_new_02_changed_text_beside_an_id_element_marks_the_parent_only() -> None:
    old = '<div id="card"><p data-canvas-id="inner">a</p><p>b</p></div>'
    result = diff(old, old.replace(">b<", ">d<"))
    assert result == {"added": [], "changed": ["card"], "removed": [], "outside": False}


def test_new_02_an_attribute_change_counts_as_changed() -> None:
    old = '<canvas-plot data-canvas-id="p" height="200"></canvas-plot>'
    assert diff(old, old.replace("200", "300"))["changed"] == ["p"]


def test_new_02_void_and_unclosed_tags_do_not_break_the_comparison() -> None:
    old = '<p>a<br>b<img src="x.png"></p><p id="u">one<p>two'
    assert diff(old, old) == {
        "added": [],
        "changed": [],
        "removed": [],
        "outside": False,
    }


def test_new_02_count_adds_each_marked_id_and_one_for_other_changes() -> None:
    result = {"added": ["a"], "changed": ["b", "c"], "removed": ["d"], "outside": True}
    assert count(result) == 4
    assert count({**result, "outside": False}) == 4
    assert count({**result, "outside": False, "removed": []}) == 3


def test_new_02_a_viewer_page_changes_as_a_whole() -> None:
    assert compare("n.md", b"# a\n", b"# b\n") == {
        "added": [], "changed": [], "removed": [], "outside": True,
    }  # fmt: skip
    assert count(compare("n.md", b"# a\n", b"# a\n")) == 0


def test_new_02_f6_ids_inside_an_svg_do_not_count_one_by_one() -> None:
    old = '<p>x</p><svg><g id="line2d_1"><path id="p1" d="M0 0"/></g></svg>'
    new = (
        old.replace("M0 0", "M0 1").replace("p1", "p2").replace("line2d_1", "line2d_9")
    )
    assert diff(old, new) == {
        "added": [], "changed": [], "removed": [], "outside": True,
    }  # fmt: skip
    assert count(diff(old, new)) == 1


def test_new_02_f6_an_svg_with_an_id_is_one_element() -> None:
    old = '<svg id="fig"><g id="inner"><path d="M0 0"/></g></svg>'
    result = diff(old, old.replace("M0 0", "M0 1"))
    assert result == {"added": [], "changed": ["fig"], "removed": [], "outside": False}


def test_new_02_f6_a_repeated_id_is_compared_by_position() -> None:
    old = '<p id="r">one</p><p id="r">two</p>'
    result = diff(old, old.replace("two", "three"))
    assert result == {"added": [], "changed": ["r"], "removed": [], "outside": False}
    assert diff(old, old) == {
        "added": [], "changed": [], "removed": [], "outside": False,
    }  # fmt: skip


def test_new_02_f6_count_has_no_number_for_what_gets_no_mark() -> None:
    result = {"added": ["a"], "changed": ["b"], "removed": ["d", "e"], "outside": False}
    assert count(result) == 3  # a, b and one "other changes" for the removed ones
    assert count({**result, "outside": True}) == 3
    assert count({**result, "removed": []}) == 2
