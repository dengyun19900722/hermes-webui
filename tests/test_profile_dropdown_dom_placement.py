from html.parser import HTMLParser
from pathlib import Path


INDEX_HTML = Path(__file__).parents[1] / "static" / "index.html"


class _ParentRecorder(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack = []
        self.parents = {}

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        element_id = attributes.get("id")
        if element_id:
            self.parents[element_id] = self.stack[-1][1] if self.stack else None
        self.stack.append((tag, element_id))

    def handle_startendtag(self, tag, attrs):
        attributes = dict(attrs)
        element_id = attributes.get("id")
        if element_id:
            self.parents[element_id] = self.stack[-1][1] if self.stack else None

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                return


def test_profile_dropdown_is_not_nested_in_the_hidden_kanban_modal():
    parser = _ParentRecorder()
    parser.feed(INDEX_HTML.read_text())

    assert parser.parents["profileDropdown"] != "kanbanBoardModal"
