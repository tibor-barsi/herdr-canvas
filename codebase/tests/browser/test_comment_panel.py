"""The comment panel: entries, filters, chips, hover links, edit and delete (P22.4).

COM-06, COM-07 and COM-09 are owned here. The frame's half of COM-07 (lighting a
marker, scrolling it into view) belongs to the marker package; these tests check
the messages the shell sends to the frame and reacts to.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent_canvas.hub import comments
from agent_canvas.hub.sends import SEND_DELIVERIES

from .support import SCROLL_PAGE
from .test_comment_layer import comment_file, comment_mode, write_comment

pytestmark = pytest.mark.browser

NEXT_MESSAGE = SEND_DELIVERIES[1]

RECT = {
    "space": "page-px",
    "x": 100,
    "y": 420,
    "w": 80,
    "h": 40,
    "fx": 0,
    "fy": 0,
    "fw": 1,
    "fh": 1,
}


def record(n: int, status: str = "sent", **fields) -> dict:  # noqa: ANN003
    """A comment record (5.13) with its status, as a ``comments`` message has it."""
    base = {
        "n": n,
        "id": f"cmt_{n}",
        "kind": "rect",
        "text": f"text {n}",
        "status": status,
        "sent": None if status == "draft" else "2026-11-09T09:14:40Z",
        "delivery": "now",
        "lost": False,
        "unread": False,
        "replies": [],
        "anchor": RECT,
        "target": {"canvas_id": None, "selector": "#target", "text": f"Target {n}"},
    }
    return base | fields


def show_comments(
    studio, sid: str, records: list[dict], page: str = "page.html"
) -> None:  # noqa: ANN001
    """Hand the shell a ``comments`` message, as the hub does after a change."""
    message = {
        "type": "comments",
        "session": sid,
        "page": page,
        "next": 99,
        "comments": records,
    }
    studio.page.evaluate("(m) => onCommentsMessage(m)", message)


def steady_layout(studio) -> None:  # noqa: ANN001
    """Make the panel and the send button take their room before a measurement.

    Without comments and unsent actions neither is there, and the first save
    would narrow and shorten the frame under a measurement. A stand-in done
    comment opens the panel without an entry under the Open filter (the hub's
    answer to the save replaces it); a queued action shows the button.
    """
    tab = studio.page.evaluate("window.__shell.activeTab()")
    show_comments(studio, tab["id"], [record(99, "done")], tab["page"])
    studio.queue_action()
    studio.page.locator("#comment-panel").wait_for()
    studio.page.locator("#send-button").wait_for()


def entries(studio):  # noqa: ANN001, ANN201
    return studio.page.locator("#comment-panel .ent")


def numbers(studio) -> list[str]:  # noqa: ANN001
    return [e.locator(".cn").inner_text() for e in entries(studio).all()]


def filter_button(studio, name: str):  # noqa: ANN001, ANN201
    return studio.page.locator(f'.filters button[data-filter="{name}"]')


MIXED = [
    record(1, "draft"),
    record(2, "sent", delivery=NEXT_MESSAGE),
    record(3, "seen", kind="point"),
    record(
        4,
        "answered",
        kind="text",
        unread=True,
        anchor={"space": "page-px", "quote": "damping ratios between 0.8 and 1.9"},
        replies=[
            {
                "from": "claude-code",
                "text": "Added the % sign.",
                "at": "2026-11-09T14:06:00",
                "sent": None,
            },
            {
                "from": None,
                "text": "Thanks.",
                "at": "2026-11-09T14:09:00",
                "sent": None,
            },
        ],
    ),
    record(5, "sent", kind="lasso", lost=True),
    record(6, "done"),
]


def test_com_06_entries_in_number_order_and_the_lost_ones_last_under_a_heading(
    studio,
) -> None:  # noqa: ANN001
    sid = studio.make(SCROLL_PAGE)
    # arriving out of order; the lost comment has a number between the others
    show_comments(
        studio, sid, [MIXED[3], record(2, "sent", lost=True), MIXED[0], MIXED[2]]
    )
    labels = studio.page.locator("#comment-panel .plist > *").evaluate_all(
        "els => els.map(e => e.classList.contains('lgrp')"
        " ? e.textContent : e.dataset.n)"
    )
    assert labels == ["1", "3", "4", "Lost after a page change", "2"]


def test_com_06_the_panel_is_headed_by_the_page_and_the_filters_count_open_done_and_all(
    studio,
) -> None:  # noqa: ANN001
    sid = studio.make(SCROLL_PAGE)
    show_comments(studio, sid, MIXED)
    comment_mode(studio)
    head = studio.page.locator("#comment-panel .ph .t").inner_text()
    assert head.replace("\n", " ").split() == ["Comments", "page.html"]
    names = [b.inner_text() for b in studio.page.locator(".filters button").all()]
    assert names == ["Open 5", "Done 1", "All 6"]
    assert filter_button(studio, "open").get_attribute("aria-pressed") == "true"
    assert numbers(studio) == [
        "1",
        "2",
        "3",
        "4",
        "5",
    ]  # Open is every comment not done
    filter_button(studio, "done").click()
    assert numbers(studio) == ["6"]
    filter_button(studio, "all").click()
    assert numbers(studio) == ["1", "2", "3", "4", "6", "5"]  # the lost one last
    assert studio.page.locator("#comment-panel .lgrp").inner_text().lower() == (
        "lost after a page change"
    )


def test_com_06_chips_carry_the_status_words_the_lost_flag_and_the_unread_dot(
    studio,
) -> None:  # noqa: ANN001
    sid = studio.make(SCROLL_PAGE)
    show_comments(studio, sid, MIXED)
    comment_mode(studio)
    filter_button(studio, "all").click()
    chips = {
        e.locator(".cn").inner_text(): e.locator(".chip") for e in entries(studio).all()
    }
    assert {n: c.inner_text() for n, c in chips.items()} == {
        "1": "draft",
        "2": "sent · next msg",
        "3": "seen",
        "4": "answered",
        "5": "lost",
        "6": "✓ done",
    }
    unread = {n: "unread" in (c.get_attribute("class") or "") for n, c in chips.items()}
    assert [n for n, flag in unread.items() if flag] == ["4"]
    dot = chips["4"].evaluate("e => getComputedStyle(e, '::before').content")
    assert dot not in ("none", "normal")
    plain = chips["3"].evaluate("e => getComputedStyle(e, '::before').content")
    assert plain in ("none", "normal")
    # an open circle for a draft, a filled one otherwise
    circles = [e.locator(".cn").get_attribute("class") for e in entries(studio).all()]
    assert "draft" in circles[0] and all("draft" not in c for c in circles[1:])


def test_com_06_an_entry_shows_icon_quote_text_replies_and_its_buttons(
    studio,
) -> None:  # noqa: ANN001
    sid = studio.make(SCROLL_PAGE)
    show_comments(studio, sid, MIXED)
    comment_mode(studio)
    filter_button(studio, "all").click()
    one, two, _, four, six, _ = entries(studio).all()
    assert (
        one.locator(".kd svg").count() == 1
        and one.locator(".tg").inner_text() == "Target 1"
    )
    assert one.locator("button").all_inner_texts() == ["Edit", "Delete"]
    assert two.locator("button").all_inner_texts() == ["Mark done", "Reply"]
    assert six.locator("button").all_inner_texts() == ["Reopen"]
    assert four.locator(".q").inner_text() == "“damping ratios between 0.8 and 1.9”"
    assert four.locator(".q").evaluate("e => getComputedStyle(e).fontStyle") == "italic"
    assert four.locator(".tx").inner_text() == "text 4"
    agent, owner = four.locator(".rp").all()
    assert agent.locator(".who").inner_text() == "claude-code · 14:06"
    assert owner.locator(".who").inner_text() == "you · 14:09"
    assert agent.locator(".rt").inner_text() == "Added the % sign."
    rule = agent.evaluate("e => parseFloat(getComputedStyle(e).borderLeftWidth)")
    assert rule >= 2
    assert two.locator(".q").count() == 0  # only a text comment shows a quote
    # text of the comment and the agent is shown as text, never as markup (6.34)
    hostile = record(8, "sent", text="<img src=x onerror=alert(1)> **bold**")
    show_comments(studio, sid, [hostile])
    assert entries(studio).first.locator(".tx").inner_text() == hostile["text"]
    assert entries(studio).first.locator("img").count() == 0


def test_com_06_the_selected_entry_has_a_frame_and_no_text_is_under_12_px(
    studio,
) -> None:  # noqa: ANN001
    sid = studio.make(SCROLL_PAGE)
    show_comments(studio, sid, MIXED)
    comment_mode(studio)
    filter_button(studio, "all").click()
    plain = entries(studio).nth(1).evaluate("e => getComputedStyle(e).boxShadow")
    entries(studio).nth(1).click()
    assert "sel" in entries(studio).nth(1).get_attribute("class")
    framed = entries(studio).nth(1).evaluate("e => getComputedStyle(e).boxShadow")
    assert plain == "none" and framed != "none"
    assert studio.page.locator("#comment-panel .sel").count() == 1
    small = studio.page.evaluate(
        """() => {
          const found = [];
          const root = document.querySelector('#comment-panel');
          const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
          for (let n = walker.nextNode(); n; n = walker.nextNode()) {
            if (!n.textContent.trim()) continue;
            const size = parseFloat(getComputedStyle(n.parentElement).fontSize);
            if (size < 12) found.push([n.textContent.trim(), size]);
          }
          return found;
        }"""
    )
    assert small == []
    studio.frame.evaluate("1")  # the frame is still alive


def test_com_06_the_strip_shows_the_open_count_and_gives_way_to_the_panel(
    studio,
) -> None:  # noqa: ANN001
    sid = studio.make(SCROLL_PAGE)
    panel = studio.page.locator("#comment-panel")
    wide = studio.page.locator("#frame").bounding_box()["width"]
    show_comments(studio, sid, [record(1, "done")])  # mode off, nothing open
    assert "strip" in panel.get_attribute("class")
    assert panel.inner_text().replace("\n", "").startswith("0")
    assert panel.bounding_box()["width"] == pytest.approx(30, abs=1)
    assert studio.page.locator("#frame").bounding_box()["width"] == pytest.approx(
        wide - 30, abs=1
    )  # without comments there is no panel at all
    show_comments(
        studio, sid, [record(1, "done"), record(2, "sent"), record(3, "seen")]
    )
    assert "strip" not in (
        panel.get_attribute("class") or ""
    )  # open comments: the panel
    assert panel.bounding_box()["width"] == pytest.approx(320, abs=1)
    show_comments(studio, sid, [record(1, "done"), record(2, "done")])
    assert "strip" in panel.get_attribute("class")
    comment_mode(studio)  # mode on: the panel, whatever is open
    assert "strip" not in panel.get_attribute("class")
    comment_mode(studio, False)
    assert "strip" in panel.get_attribute("class")
    studio.page.locator("#comment-panel .stripbutton").click()
    assert "strip" not in panel.get_attribute("class")


def test_com_06_the_strip_counts_what_is_open(studio) -> None:  # noqa: ANN001
    sid = studio.make(SCROLL_PAGE)
    show_comments(studio, sid, [record(1, "done")])
    assert studio.page.locator("#comment-panel .stripbutton .cn").inner_text() == "0"
    # the strip is only drawn when nothing is open, so its count is 0; a lost
    # comment that is not done still counts as open and keeps the panel
    show_comments(studio, sid, [record(1, "sent", lost=True)])
    assert studio.page.locator(".filters button").first.inner_text() == "Open 1"


def test_com_06_the_panel_keeps_its_scroll_position_when_a_message_redraws_it(
    studio,
) -> None:  # noqa: ANN001
    sid = studio.make(SCROLL_PAGE)
    many = [record(n, "sent") for n in range(1, 31)]
    show_comments(studio, sid, many)
    comment_mode(studio)
    studio.page.evaluate(
        "document.querySelector('#comment-panel .plist').scrollTop = 400"
    )
    show_comments(studio, sid, many)
    top = studio.page.evaluate(
        "document.querySelector('#comment-panel .plist').scrollTop"
    )
    assert top == 400


# ---- COM-07: hover and select, both ways -----------------------------------


RECORDER = """() => {
  window.__got = [];
  window.addEventListener('message',
    (e) => window.__got.push({at: Date.now(), ...e.data}));
}"""


def frame_log(studio, kind: str) -> list[dict]:  # noqa: ANN001
    return studio.frame.evaluate(
        "(k) => window.__got.filter((m) => m.type === k)", kind
    )


def marker_report(studio, token: str, action: str) -> int:  # noqa: ANN001
    """Post a marker report from the frame; return the time it was sent."""
    return studio.frame.evaluate(
        "([t, a]) => { const at = Date.now();"
        " parent.postMessage({type: 'comment-marker', token: t, action: a}, '*');"
        " return at; }",
        [token, action],
    )


def prepare_links(studio, sid: str, records: list[dict]) -> dict:  # noqa: ANN001
    """Show ``records`` and return the token the frame was given for each number."""
    studio.frame.evaluate(RECORDER)
    comment_mode(studio)
    show_comments(studio, sid, records)
    studio.frame.wait_for_function(
        "window.__got.some((m) => m.type === 'comment-markers' && m.markers.length)"
    )
    last = frame_log(studio, "comment-markers")[-1]
    return {m["n"]: m["token"] for m in last["markers"]}


@pytest.mark.timing
def test_com_07_pointing_at_an_entry_names_its_marker_to_the_frame_within_100_ms(
    studio,
) -> None:  # noqa: ANN001
    sid = studio.make(SCROLL_PAGE)
    tokens = prepare_links(studio, sid, [record(1, "sent"), record(2, "draft")])
    entry = entries(studio).nth(1)
    started = studio.page.evaluate(
        "() => { const t = Date.now();"
        " document.querySelector('#comment-panel .ent[data-n=\"2\"]')"
        ".dispatchEvent(new MouseEvent('mouseenter')); return t; }"
    )
    studio.frame.wait_for_function(
        "window.__got.some((m) => m.type === 'comment-hover')"
    )
    [hover] = frame_log(studio, "comment-hover")
    assert hover["token"] == tokens[2] and hover["at"] - started < 100
    assert set(hover) == {"at", "type", "token"}  # no text goes to the frame (COM-15)
    entry.dispatch_event("mouseleave")
    studio.frame.wait_for_function(
        "window.__got.filter((m) => m.type === 'comment-hover').length === 2"
    )
    assert frame_log(studio, "comment-hover")[-1]["token"] is None


def test_com_07_a_lost_entry_highlights_nothing(studio) -> None:  # noqa: ANN001
    sid = studio.make(SCROLL_PAGE)
    prepare_links(studio, sid, [record(1, "sent"), record(2, "sent", lost=True)])
    lost = entries(studio).nth(1)
    assert lost.locator(".chip").inner_text() == "lost"
    lost.hover()
    studio.page.wait_for_timeout(200)
    assert frame_log(studio, "comment-hover") == []
    lost.click()  # selecting it is allowed, but the frame is not asked to scroll
    studio.page.wait_for_timeout(200)
    assert frame_log(studio, "comment-scroll") == []
    assert "sel" in lost.get_attribute("class")


@pytest.mark.timing
def test_com_07_pointing_at_a_marker_highlights_its_entry_within_100_ms(
    studio,
) -> None:  # noqa: ANN001
    sid = studio.make(SCROLL_PAGE)
    tokens = prepare_links(studio, sid, [record(1, "sent"), record(2, "sent")])
    sent = marker_report(studio, tokens[2], "hover")
    studio.page.wait_for_selector("#comment-panel .ent.hot")
    seen = studio.page.evaluate("Date.now()")
    assert seen - sent < 100 + 100  # the poll interval of the wait is part of it
    assert [
        e.get_attribute("data-n") for e in studio.page.locator(".ent.hot").all()
    ] == ["2"]
    marker_report(studio, tokens[2], "leave")
    studio.page.wait_for_selector("#comment-panel .ent.hot", state="detached")
    # a token the shell never gave out highlights nothing
    marker_report(studio, "nope", "hover")
    studio.page.wait_for_timeout(200)
    assert studio.page.locator(".ent.hot").count() == 0


def test_com_07_a_click_or_enter_on_an_entry_selects_it_and_asks_the_frame_to_scroll(
    studio,
) -> None:  # noqa: ANN001
    sid = studio.make(SCROLL_PAGE)
    tokens = prepare_links(studio, sid, [record(1, "sent"), record(2, "sent")])
    entries(studio).nth(1).click()
    studio.frame.wait_for_function(
        "window.__got.some((m) => m.type === 'comment-scroll')"
    )
    assert frame_log(studio, "comment-scroll")[-1]["token"] == tokens[2]
    assert frame_log(studio, "comment-markers")[-1]["selected"] == tokens[2]
    entries(studio).nth(0).focus()
    studio.page.keyboard.press("Enter")
    studio.frame.wait_for_function(
        "window.__got.filter((m) => m.type === 'comment-scroll').length === 2"
    )
    assert frame_log(studio, "comment-scroll")[-1]["token"] == tokens[1]
    assert [
        e.get_attribute("data-n") for e in studio.page.locator(".ent.sel").all()
    ] == ["1"]
    assert all(
        set(m) == {"at", "type", "token"} for m in frame_log(studio, "comment-scroll")
    )


def test_com_07_a_click_on_a_markers_number_selects_its_entry_and_scrolls_the_panel(
    studio,
) -> None:  # noqa: ANN001
    sid = studio.make(SCROLL_PAGE)
    many = [record(n, "sent") for n in range(1, 31)]
    tokens = prepare_links(studio, sid, many)
    plist = studio.page.locator("#comment-panel .plist")
    assert plist.evaluate("e => e.scrollTop") == 0
    marker_report(studio, tokens[28], "click")
    studio.page.wait_for_selector('#comment-panel .ent.sel[data-n="28"]')
    inside = studio.page.evaluate(
        """() => {
          const panel = document.querySelector('#comment-panel');
          const box = panel.querySelector('.plist').getBoundingClientRect();
          const row = panel.querySelector('.ent.sel').getBoundingClientRect();
          return row.top >= box.top - 1 && row.bottom <= box.bottom + 1;
        }"""
    )
    assert inside
    assert studio.page.locator(".ent.sel").count() == 1


# ---- COM-09: edit and delete of drafts --------------------------------------


def save_one(studio, text: str = "units?") -> None:  # noqa: ANN001
    comment_mode(studio)
    write_comment(studio, (120, 100), (260, 180), text)
    studio.page.wait_for_selector("#comment-panel .ent")
    studio.page.wait_for_selector(".cbox", state="detached")


def test_com_09_edit_opens_the_box_with_the_text_enter_saves(studio) -> None:  # noqa: ANN001
    studio.make(SCROLL_PAGE)
    save_one(studio)
    entries(studio).first.locator("button", has_text="Edit").click()
    field = studio.page.locator(".cbox textarea")
    field.wait_for()
    assert field.input_value() == "units?"
    assert "#1" in studio.page.locator(".cbox .h").inner_text()
    box = studio.page.locator(".cbox").bounding_box()
    frame = studio.page.locator("#frame").bounding_box()
    assert (
        box["x"] >= frame["x"]
        and box["x"] + box["width"] <= frame["x"] + frame["width"] + 1
    )
    field.fill("units in Hz?")
    field.press("Enter")
    studio.page.wait_for_selector(".cbox", state="detached")
    studio.page.wait_for_function(
        "document.querySelector('#comment-panel .ent .tx').textContent"
        " === 'units in Hz?'"
    )
    [stored] = comment_file(studio)["comments"]
    assert (
        stored["text"] == "units in Hz?" and stored["edited"] and stored["sent"] is None
    )
    assert entries(studio).count() == 1


def test_com_09_esc_closes_the_edit_box_keeps_the_text(studio) -> None:  # noqa: ANN001
    studio.make(SCROLL_PAGE)
    save_one(studio)
    entries(studio).first.locator("button", has_text="Edit").click()
    field = studio.page.locator(".cbox textarea")
    field.fill("something else")
    field.press("Escape")
    studio.page.wait_for_selector(".cbox", state="detached")
    assert comment_file(studio)["comments"][0]["text"] == "units?"
    assert studio.page.evaluate("document.body.classList.contains('commenting')")


def test_com_09_an_edit_of_a_comment_sent_meanwhile_is_refused_in_the_box(
    studio,
) -> None:  # noqa: ANN001
    studio.make(SCROLL_PAGE)
    save_one(studio)
    entries(studio).first.locator("button", has_text="Edit").click()
    studio.page.wait_for_selector(".cbox textarea")
    comments.take_unsent(studio.folder, "page.html", "now", "evt_x")  # the stale panel
    studio.page.fill(".cbox textarea", "too late")
    studio.page.press(".cbox textarea", "Enter")
    studio.page.wait_for_function(
        "document.querySelector('.cbox .note').textContent !== ''"
    )
    assert "sent" in studio.page.locator(".cbox .note").inner_text()
    assert comment_file(studio)["comments"][0]["text"] == "units?"


def test_com_09_a_sent_comment_has_no_edit_or_delete(studio) -> None:  # noqa: ANN001
    sid = studio.make(SCROLL_PAGE)
    save_one(studio)
    studio.page.click("#send-button")
    studio.wait_events(sid, 1)
    studio.page.wait_for_function(
        "document.querySelector('#comment-panel .ent .chip').textContent !== 'draft'"
    )
    buttons = entries(studio).first.locator("button").all_inner_texts()
    assert "Edit" not in buttons and "Delete" not in buttons
    assert buttons == ["Mark done", "Reply"]
    assert [b.is_enabled() for b in entries(studio).first.locator("button").all()] == [
        True,
        True,
    ]


def test_com_09_delete_removes_entry_marker_and_picture(studio) -> None:  # noqa: ANN001
    studio.make(SCROLL_PAGE)
    save_one(studio)
    [stored] = comment_file(studio)["comments"]
    picture = Path(studio.folder / stored["picture"])
    assert picture.is_file()
    entries(studio).first.locator("button", has_text="Delete").click()
    studio.page.locator("#comment-panel").wait_for(state="hidden")  # no comment left
    studio.frame.locator('[data-ac-comment-host] .box[data-n="1"]').wait_for(
        state="detached"
    )
    assert comment_file(studio)["comments"] == [] and not picture.exists()


# ---- the layout against variant A -------------------------------------------


def test_com_06_the_panel_at_the_mockup_size_is_saved_for_comparison(
    studio, tmp_path
) -> None:  # noqa: ANN001
    sid = studio.make(SCROLL_PAGE)
    studio.page.set_viewport_size({"width": 1181, "height": 840})
    show_comments(
        studio,
        sid,
        [
            record(
                1,
                "answered",
                kind="text",
                anchor={
                    "space": "page-px",
                    "quote": "damping ratios between 0.8 % and 1.9 %",
                },
                text="1.9 % looks high for a clamped PETG beam. Check mode 2.",
                target={"text": "Results paragraph"},
                unread=True,
                replies=[
                    {
                        "from": "claude",
                        "at": "2026-11-09T14:06:00",
                        "sent": None,
                        "text": "Re-fitted: mode 2 is 1.2 %. It came from run 12.",
                    }
                ],
            ),
            record(
                2,
                "seen",
                text="Is this a double peak? Zoom to 255-280 Hz.",
                target={"text": "Figure 2 (FRF)"},
            ),
            record(
                3,
                "sent",
                kind="point",
                delivery=NEXT_MESSAGE,
                text="Units: dB re 1 (m/s2)/N.",
                target={"text": "Figure 2 (FRF), y axis"},
            ),
            record(
                4,
                "draft",
                kind="lasso",
                text="Mode 4 has MAC 0.71 against the FE shape.",
                target={"text": "Table 1 (modes)"},
            ),
            record(
                5,
                "sent",
                lost=True,
                text="Fix the caption.",
                target={"text": "Caption"},
            ),
            record(
                6, "done", text="Label the peaks.", target={"text": "Figure 2 (FRF)"}
            ),
        ],
    )
    comment_mode(studio)
    entries(studio).nth(1).click()
    target = Path(os.environ.get("AC_SHOT_DIR", tmp_path))
    target.mkdir(parents=True, exist_ok=True)
    path = target / "panel-1181x840.png"
    studio.page.screenshot(path=str(path))
    studio.page.locator("#comment-panel").screenshot(
        path=str(target / "panel-only.png")
    )
    assert path.stat().st_size > 10_000


# ---- COM-07: the frame's half, with the real layer --------------------------


FAR_PAGE = SCROLL_PAGE.replace(
    '<div id="tail"></div>',
    '<div id="tail"><div id="far" style="margin-top:1200px;width:200px;height:60px">'
    "</div>"
    '<div style="height:900px"></div></div>',
)


def layer_marker(studio, n: int):  # noqa: ANN001, ANN201
    return studio.frame.locator(f'[data-ac-comment-host] >> .badge:text-is("{n}")')


def marker_hot(studio, n: int) -> bool:  # noqa: ANN001
    return studio.frame.evaluate(
        "(n) => document.querySelector('[data-ac-comment-host]').shadowRoot"
        ".querySelector(`[data-mk][data-n='${n}']`)"
        ".classList.contains('hot')",
        n,
    )


def show_real(studio, sid: str, records: list[dict]) -> None:  # noqa: ANN001
    comment_mode(studio)
    show_comments(studio, sid, records)
    layer_marker(studio, 1).wait_for()


def test_com_07_hovering_an_entry_makes_its_marker_hot_in_the_real_layer(
    studio,
) -> None:  # noqa: ANN001
    sid = studio.make(SCROLL_PAGE)
    show_real(studio, sid, [record(1, "sent"), record(2, "sent")])
    assert not marker_hot(studio, 1) and not marker_hot(studio, 2)
    entries(studio).nth(1).hover()
    studio.frame.wait_for_function(
        "document.querySelector('[data-ac-comment-host]').shadowRoot"
        ".querySelectorAll('.hot').length > 0"
    )
    assert marker_hot(studio, 2) and not marker_hot(studio, 1)
    studio.page.mouse.move(5, 5)
    studio.frame.wait_for_function(
        "document.querySelector('[data-ac-comment-host]').shadowRoot"
        ".querySelectorAll('.hot').length === 0"
    )


def test_com_07_selecting_an_entry_scrolls_a_far_marker_fully_into_view(
    studio,
) -> None:  # noqa: ANN001
    sid = studio.make(FAR_PAGE)
    far = {"target": {"canvas_id": None, "selector": "#far", "text": "far"}}
    show_real(studio, sid, [record(1, "sent"), record(2, "sent", **far)])
    assert studio.frame.evaluate("window.scrollY") == 0
    entries(studio).nth(1).click()
    studio.frame.wait_for_function("window.scrollY > 500")
    top, bottom, height = studio.frame.evaluate(
        "(() => { const r = document.querySelector('[data-ac-comment-host]').shadowRoot"
        ".querySelector(`[data-mk][data-n='2']`).getBoundingClientRect();"
        " return [r.top, r.bottom, window.innerHeight]; })()"
    )
    assert top >= 0 and bottom <= height


def test_com_07_hovering_a_marker_number_highlights_its_entry(
    studio,
) -> None:  # noqa: ANN001
    sid = studio.make(SCROLL_PAGE)
    show_real(studio, sid, [record(1, "sent"), record(2, "sent")])
    assert studio.page.locator(".ent.hot").count() == 0
    layer_marker(studio, 2).hover()
    studio.page.wait_for_selector("#comment-panel .ent.hot")
    assert [
        e.get_attribute("data-n") for e in studio.page.locator(".ent.hot").all()
    ] == ["2"]
    studio.page.mouse.move(5, 5, steps=20)
    studio.page.wait_for_selector("#comment-panel .ent.hot", state="detached")


def test_com_07_a_lost_entry_sends_nothing_to_the_real_layer(
    studio,
) -> None:  # noqa: ANN001
    sid = studio.make(SCROLL_PAGE)
    show_real(studio, sid, [record(1, "sent"), record(2, "sent", lost=True)])
    studio.frame.evaluate(RECORDER)
    lost = entries(studio).nth(1)
    lost.hover()
    lost.click()
    studio.page.wait_for_timeout(200)
    assert studio.frame.evaluate("window.scrollY") == 0
    assert frame_log(studio, "comment-hover") == []
    assert frame_log(studio, "comment-scroll") == []
    assert not marker_hot(studio, 1)
