"""Chapter indexes: the type directory matches the groups below it."""

import re

import pytest

from .test_local_practice import ROOT

CHAPTERS = ["1", "2"]


@pytest.mark.parametrize("chapter", CHAPTERS)
def test_directory_matches_groups(chapter):
    home = (ROOT / f"site/{chapter}/index.html").read_text()
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
            str(len(re.findall(rf'class="problem-card" href="/{chapter}/q\d+/"', block))),
        ))
        assert f'<span class="type-count">{groups[-1][3]} 题</span>' in block
    assert entries == groups
    assert [g[1] for g in groups] == [f"{i:02d}" for i in range(1, len(groups) + 1)]
    for number in re.findall(r"第 (\d\d) 组", home):
        assert 1 <= int(number) <= len(groups)


def method_dialogs(home):
    return dict(re.findall(
        r'<dialog class="method-sheet" id="(method-[a-z]+)".*?>(.*?)</dialog>', home, re.S,
    ))


@pytest.mark.parametrize("chapter", CHAPTERS)
def test_method_dialogs_belong_to_their_group(chapter):
    home = (ROOT / f"site/{chapter}/index.html").read_text()
    blocks = [
        block.split("</section>")[0]
        for block in re.split(r'(?=<section class="type-group")', home)[1:]
    ]
    dialogs = method_dialogs(home)
    chips = []
    for block in blocks:
        for dialog_id in re.findall(r'data-method-dialog="(method-[a-z]+)"', block):
            chips.append(dialog_id)
            content = dialogs[dialog_id]
            group_index = re.search(r'class="type-index" aria-hidden="true">(\d\d)<', block)[1]
            assert f'<span class="type-index" aria-hidden="true">{group_index}</span>' in content
            title = re.search(r"<h3 [^>]*>(.*?)</h3>", block)[1]
            assert re.search(rf'id="{dialog_id}-title"[^>]*>{re.escape(title)} · 图解</h2>', content)
            problems = set(re.findall(rf'class="problem-card" href="(/{chapter}/q\d+/)"', block))
            examples = re.findall(rf'<a href="(/{chapter}/q\d+/)"', content)
            assert examples and set(examples) <= problems
            for href, number in re.findall(rf'<a href="/{chapter}/q(\d+)/">.*?第 (\d+) 题', content):
                assert href == number
    assert sorted(chips) == sorted(dialogs)


def test_always_true_dialogs_teach_when_to_use_the_method():
    home = (ROOT / "site/2/index.html").read_text()
    dialogs = method_dialogs(home)
    assert len(dialogs) == 4
    problems = set(re.findall(r'class="problem-card" href="/2/q(\d+)/"', home))
    for dialog_id, content in dialogs.items():
        judge = re.search(r'<section class="method-judge".*?</section>', content, re.S)
        assert judge, dialog_id
        judge = judge[0]
        signal = re.search(r"读题信号 · 第 (\d\d) 题", judge)
        assert signal and signal[1] in problems
        assert "<mark>" in judge
        assert re.findall(r'class="method-check-no"', judge)
        targets = re.findall(r'data-method-switch="(method-[a-z]+)"', judge)
        assert targets and dialog_id not in targets and set(targets) <= set(dialogs)
        assert re.search(r'class="method-figure">.*?<svg', content, re.S)
