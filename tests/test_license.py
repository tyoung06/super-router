"""Build brief 25, B2 (decision 4): LICENSE is MIT, with one copyright line, `Copyright (c) 2026 <handle>`: the GitHub
handle, never a full name. The handle is read at run time (the inbox repo's owner in this Mac's local settings), so this
file spells it nowhere; without the local value that check skips."""
import re
from pathlib import Path

import pytest

from tests.test_inbox_setting import real_inbox

ROOT = Path(__file__).resolve().parent.parent
LICENSE = ROOT / "LICENSE"
COPYRIGHT = re.compile(r"^Copyright \(c\) 2026 (\S+)$", re.M)


def test_license_is_mit_with_one_copyright_line():
    text = LICENSE.read_text()
    assert text.startswith("MIT License\n\n")
    assert len(COPYRIGHT.findall(text)) == 1
    assert "Permission is hereby granted, free of charge, to any person obtaining a copy" in text
    assert 'THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND' in text


@pytest.mark.skipif(real_inbox() is None, reason="no grok_inbox_repo in this Mac's config/settings.local.json")
def test_the_copyright_holder_is_the_github_handle():
    holder = COPYRIGHT.search(LICENSE.read_text()).group(1)
    assert holder.lower() == real_inbox().split("/", 1)[0].lower()
