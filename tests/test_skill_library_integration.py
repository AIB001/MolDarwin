"""Original MolOrigin sources join the public catalog without a second copy."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from moldarwin import skills


def test_every_existing_product_bundle_is_registered_once():
    repo = Path(__file__).resolve().parents[1]
    # The authoring helper ships like every other bundle; the MolOrigin entries in
    # .claude/skills are host-discovery symlinks onto the pinned asset originals,
    # so both spellings have to be resolved before a bundle can be counted once.
    originals = list((repo / '.claude/skills').glob('*/SKILL.md'))
    originals += list((repo / 'asset/molorigin/skills').glob('*/SKILL.md'))
    resolved = [skills.bundle_root(slug).resolve() / 'SKILL.md' for slug in skills.WORKFLOWS]
    assert set(resolved) == {path.resolve() for path in originals}
    assert len(resolved) == len(set(resolved))
    assert all('life-healthy-' not in str(path) for path in resolved)
    # A bundle is registered by being present, so nothing may sit out silently:
    # the only way out of the catalog is a named validation failure.
    assert skills.UNREGISTERED == {}


def test_a_present_bundle_is_registered_without_being_listed_anywhere():
    """The registration check a written-out table cannot pass: add a directory, get a skill."""
    text = Path(skills.__file__).resolve().read_text(encoding='utf-8')
    # The catalog is assigned from the discovery pass rather than written out. That is the
    # whole of what a source-text check may honestly hold here; that discovery actually
    # registers a bundle no list mentions is held by consequence, over a real directory, in
    # test_a_new_bundle_directory_joins_the_catalog_and_a_broken_one_is_named below.
    #
    # An earlier version of this test instead asserted that no registered name appears
    # anywhere in the module except the two legacy aliases. It was the wrong instrument
    # twice over, and both ways are worth recording because the repository has met this
    # shape before (docs/thin-harness/RSI_ARCHITECTURE.md section 7): a substring match
    # reported `moldarwin-campaign` purely because `moldarwin-campaign-monitoring` is in the
    # text, and the premise was too strong anyway -- the `rsi` group at skills.py names its
    # own members, which answers *which skills form a group*, not *which skills exist*.
    # Grouping is a different question from registration and naming members there is not a
    # registration list. Policing the source text for names would have had to keep
    # exempting legitimate mentions, which is prose policing prose.
    assert 'WORKFLOWS, UNREGISTERED = discover_bundles()' in text
    for slug in ('step-corpus', 'recomputability-audit', 'assessment-regime',
                 'evaluation-contract', 'stochastic-oracle'):
        assert skills.canonical_slug(slug) == slug
        assert skills.canonical_slug(skills.WORKFLOWS[slug]) == slug
        assert skills.read_member(slug)['content'].startswith('---')


def test_a_new_bundle_directory_joins_the_catalog_and_a_broken_one_is_named(tmp_path):
    (tmp_path / 'moldarwin-new-regime').mkdir()
    (tmp_path / 'moldarwin-new-regime' / 'SKILL.md').write_text(
        '---\nname: moldarwin-new-regime\ndescription: Fixture.\n---\nBody.\n', encoding='utf-8')
    (tmp_path / 'moldarwin-undeclared').mkdir()
    (tmp_path / 'moldarwin-undeclared' / 'SKILL.md').write_text(
        '---\ndescription: Fixture.\n---\nBody.\n', encoding='utf-8')
    (tmp_path / 'moldarwin-unframed').mkdir()
    (tmp_path / 'moldarwin-unframed' / 'SKILL.md').write_text('no frontmatter\n', encoding='utf-8')
    # A wheel names each bundle directory for its slug, a checkout for the skill;
    # the bundle declares the same name in both, so both layouts register it once.
    wheel = tmp_path / 'wheel'
    (wheel / 'new-regime').mkdir(parents=True)
    (wheel / 'new-regime' / 'SKILL.md').write_text(
        '---\nname: moldarwin-new-regime\ndescription: Fixture.\n---\nBody.\n', encoding='utf-8')
    assert skills.discover_bundles((wheel,))[0] == {'new-regime': 'moldarwin-new-regime'}
    registered, unregistered = skills.discover_bundles((tmp_path,))
    assert registered == {'new-regime': 'moldarwin-new-regime'}
    assert 'name: <skill>' in unregistered['moldarwin-undeclared']
    assert 'frontmatter' in unregistered['moldarwin-unframed']
    assert sorted(unregistered) == ['moldarwin-undeclared', 'moldarwin-unframed']


def test_a_symlinked_bundle_directory_is_named_rather_than_registered_unreadably(tmp_path):
    """snapshot reads original bytes only, so a symlink must not enter the catalog silently."""
    original = tmp_path / 'elsewhere' / 'moldarwin-linked'
    original.mkdir(parents=True)
    (original / 'SKILL.md').write_text(
        '---\nname: moldarwin-linked\ndescription: Fixture.\n---\nBody.\n', encoding='utf-8')
    library = tmp_path / 'skills'
    library.mkdir()
    (library / 'moldarwin-linked').symlink_to(original)
    registered, unregistered = skills.discover_bundles((library,))
    assert registered == {}
    assert 'symlink' in unregistered['moldarwin-linked']
    # The same symlink beside the directory it points at is the MolOrigin layout:
    # the original registers once and the host-discovery link is not a second bundle.
    both = skills.discover_bundles((library, original.parent))
    assert both == ({'linked': 'moldarwin-linked'}, {})


def test_an_unregistered_but_present_bundle_is_refused_with_its_route(monkeypatch):
    monkeypatch.setattr(skills, 'UNREGISTERED',
                        {'moldarwin-undeclared': 'SKILL.md frontmatter must declare `name: <skill>`'})
    with pytest.raises(KeyError) as absent:
        skills.canonical_slug('moldarwin-not-on-disk')
    assert 'present on disk' not in str(absent.value)
    assert 'moldarwin_capabilities' in str(absent.value)
    with pytest.raises(KeyError) as present:
        skills.canonical_slug('moldarwin-undeclared')
    message = str(present.value)
    assert 'unknown skill' in message and 'bundle present on disk, not registered' in message
    assert 'name: <skill>' in message and 'moldarwin_capabilities' in message


def test_a_bundle_added_after_startup_is_refused_as_present_and_not_as_unknown(tmp_path, monkeypatch):
    (tmp_path / 'moldarwin-late-arrival').mkdir()
    (tmp_path / 'moldarwin-late-arrival' / 'SKILL.md').write_text(
        '---\nname: moldarwin-late-arrival\ndescription: Fixture.\n---\nBody.\n', encoding='utf-8')
    monkeypatch.setattr(skills, '_bundle_sources', lambda: (tmp_path,))
    for identifier in ('moldarwin-late-arrival', 'late-arrival', 'moldarwin://skills/late-arrival'):
        with pytest.raises(KeyError) as refusal:
            skills.canonical_slug(identifier)
        assert 'bundle present on disk, not registered' in str(refusal.value)
        assert 'restart' in str(refusal.value)
    with pytest.raises(KeyError) as traversal:
        skills.canonical_slug('../../etc/passwd')
    assert 'present on disk' not in str(traversal.value)


def test_the_recomputability_audit_refusals_point_at_a_deliverable_skill(tmp_path):
    """Governance refuses and names this skill; a named skill a host cannot read is a wall."""
    slug = skills.canonical_slug('moldarwin-recomputability-audit')
    assert skills.skill_reference('moldarwin-recomputability-audit')['read'] == {
        'tool': 'moldarwin_skill_read', 'arguments': {'slug': slug}}
    from moldarwin import host
    report = host.export(tmp_path / 'host', 'claude', selected_skills=[slug])
    assert (tmp_path / 'host/.claude/skills/moldarwin-recomputability-audit/SKILL.md').is_file()
    assert [row['slug'] for row in report['skills']] == [slug]


def test_discovery_groups_stay_inside_the_derived_catalog():
    libraries = skills.library_catalog()['libraries']
    grouped = [slug for group in libraries.values() for slug in group]
    assert set(grouped) == set(skills.WORKFLOWS)
    assert len(grouped) == len(set(grouped))


def test_molorigin_summary_reads_only_selected_source_and_versions_all_members(monkeypatch):
    slug = 'molorigin-target-modulators'
    original = skills.bundle_root
    seen = []
    def selected(value):
        seen.append(value)
        assert value == slug
        return original(value)
    monkeypatch.setattr(skills, 'bundle_root', selected)
    summary = skills.catalog(detail='summary', skills=[slug])
    assert seen == [slug]
    manifest, contents = skills.snapshot(slug)
    assert summary['skills'][0]['manifest_sha256'] == manifest['manifest_sha256']
    assert 'references/workflow.md' in contents and 'agents/openai.yaml' in contents
    assert 'files' not in summary['skills'][0]
    assert skills.read_member(slug, 'references/workflow.md')['content'].encode() == contents['references/workflow.md']


def test_molorigin_discovery_uses_standard_library_without_loading_acquisition(tmp_path):
    environment = {**os.environ, 'PYTHONPATH': str(Path(skills.__file__).parents[1])}
    code = "from moldarwin.skills import catalog; import json,sys; print(json.dumps(catalog(skills=['molorigin-target-modulators']))); assert 'molorigin' not in sys.modules"
    run = subprocess.run([sys.executable, '-S', '-c', code], cwd=tmp_path,
                         env=environment, capture_output=True, text=True,
                         encoding='utf8', timeout=30, check=True)
    assert json.loads(run.stdout)['skills'][0]['slug'] == 'molorigin-target-modulators'


def test_legacy_molorigin_uris_and_new_skill_tool_return_identical_original_bytes():
    pytest.importorskip('mcp')
    from moldarwin.mcp.server import build
    server = build()
    async def read(uri):
        result = await server.read_resource(uri)
        return next(iter(result)).content
    async def exercise():
        listing = json.loads(await read('moldarwin://skills/molorigin'))
        expected = {slug for slug in skills.WORKFLOWS if slug.startswith('molorigin-')}
        assert {row['name'] for row in listing['skills']} == expected
        for row in listing['skills']:
            slug = row['name']
            manifest, contents = skills.snapshot(slug)
            assert await read(row['uri']) == contents['SKILL.md'].decode()
            assert await read('moldarwin://skills/' + slug) == contents['SKILL.md'].decode()
            assert set(row['resources']) == set(contents)
            for member in row['resources']:
                if member.startswith('references/'):
                    assert await read(row['uri'] + '/' + member) == contents[member].decode()
            assert manifest['name'] == row['name']
    asyncio.run(exercise())
