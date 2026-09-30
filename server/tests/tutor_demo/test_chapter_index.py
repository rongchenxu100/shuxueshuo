"""Chapter /1/ index: the type directory matches the groups below it."""

import re

from .test_local_practice import ROOT


def test_directory_matches_groups():
    home = (ROOT / "site/1/index.html").read_text()
    toc = re.search(r'<nav class="toc" id="toc".*?</nav>', home, re.S)[0]
    entries = re.findall(
        r'href="#(group-[a-z]+)"><span class="toc-index" aria-hidden="true">(\d\d)</span>'
        r'<span class="toc-name">(.*?)</span>.*?<span class="toc-count">(\d+) 题</span>',
        toc,
    )
    groups = []
    for block in re.split(r'(?=<section class="type-group")', home)[1:]:
        block = block.split("</section>")[0]
        groups.append((
            re.search(r'id="(group-[a-z]+)"', block)[1],
            re.search(r'class="type-index" aria-hidden="true">(\d\d)<', block)[1],
            re.search(r"<h3 [^>]*>(.*?)</h3>", block)[1],
            str(len(re.findall(r'class="problem-card" href="/1/q\d+/"', block))),
        ))
        assert f'<span class="type-count">{groups[-1][3]} 题</span>' in block
    assert entries == groups
    assert [g[1] for g in groups] == [f"{i:02d}" for i in range(1, len(groups) + 1)]
    for number in re.findall(r"第 (\d\d) 组", home):
        assert 1 <= int(number) <= len(groups)
