from pathlib import Path
from xml.etree import ElementTree as ET

from valbot.schedule import cron_block, merge_crontab, windows_xml


def test_cron_is_idempotent_and_preserves_other_tasks():
    root = Path("/home/player/project with 10% space")
    block = cron_block(root, root / ".venv/bin/python", root / "data")
    existing = "# my backup\n0 1 * * * /usr/bin/backup\n"
    once = merge_crontab(existing, root, block)
    twice = merge_crontab(once, root, block)
    assert once == twice
    assert existing in twice
    assert "5 8 * * *" in twice
    assert "\\%" in twice
    assert "'" in twice


def test_windows_hidden_schedule_quotes_paths():
    root = Path("C:/Users/player/My Project")
    xml = windows_xml(root, root / ".venv/Scripts/python.exe", root / "data", "S-1-5-21-123")
    tree = ET.fromstring(xml)
    ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    assert tree.find(".//t:Hidden", ns).text == "true"
    assert tree.find(".//t:Command", ns).text.endswith("pythonw.exe")
    assert '"' in tree.find(".//t:Arguments", ns).text
    assert "T08:05:00" in tree.find(".//t:StartBoundary", ns).text
    assert tree.find(".//t:LogonType", ns).text == "InteractiveToken"
