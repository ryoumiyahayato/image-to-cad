"""One authorized, SHA-pinned cleanup. Archive all tips before deleting branches.

Run only in the repository's authenticated Actions checkout after tests pass.
No main rewrite, no tag overwrite, no branch deletion without a verified tag.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
from urllib.request import Request, urlopen

REPOSITORY = 'ryoumiyahayato/image-to-cad'


def git(*args: str) -> str:
    return subprocess.check_output(['git', *args], text=True).strip()


def remote_refs() -> dict[str, str]:
    return {ref: sha for sha, ref in (line.split() for line in git('ls-remote', '--refs', 'origin').splitlines())}


def api(method: str, path: str, body: dict | None = None):
    request = Request('https://api.github.com/repos/' + REPOSITORY + '/' + path,
                      data=None if body is None else json.dumps(body).encode(), method=method,
                      headers={'Authorization': 'Bearer ' + os.environ['GH_TOKEN'],
                               'Accept': 'application/vnd.github+json', 'Content-Type': 'application/json'})
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-main', required=True)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if os.environ.get('GITHUB_REPOSITORY') != REPOSITORY:
        raise SystemExit('Wrong repository; refusing')
    plan = json.loads(Path('docs/project/BRANCH_ARCHIVE_20261024.json').read_text())
    refs = remote_refs()
    if refs.get('refs/heads/main') != args.expected_main:
        raise SystemExit('main changed; refusing cleanup')
    planned = {row['branch']: row['sha'] for row in plan['retired_branches']}
    planned['maintenance/native-first-20261024'] = args.expected_main
    live = {key.removeprefix('refs/heads/'): value for key, value in refs.items() if key.startswith('refs/heads/')}
    unplanned = set(live) - set(planned) - {'main'}
    if unplanned:
        raise SystemExit('Unplanned live branches; inspect: ' + repr(sorted(unplanned)))
    for branch, sha in planned.items():
        if branch in live and live[branch] != sha:
            raise SystemExit('Branch changed: ' + branch)
    selected = {branch: sha for branch, sha in planned.items() if branch in live}
    tags = {'archive/20261024/' + branch: sha for branch, sha in selected.items()}
    tags['archive/20261024/main-before-native-first'] = plan['main_before']
    for tag, sha in tags.items():
        existing = refs.get('refs/tags/' + tag)
        if existing is not None and existing != sha:
            raise SystemExit('Existing archive tag differs: ' + tag)
        git('cat-file', '-e', sha + '^{commit}')
    print(json.dumps({'mode': 'EXECUTE' if args.execute else 'DRY_RUN', 'branches': selected, 'archive_tags': tags}, indent=2))
    if not args.execute:
        return
    missing_tags = [f'{sha}:refs/tags/{name}' for name, sha in tags.items() if 'refs/tags/' + name not in refs]
    if missing_tags:
        git('push', '--atomic', 'origin', *missing_tags)
    refs = remote_refs()
    if any(refs.get('refs/tags/' + name) != sha for name, sha in tags.items()):
        raise SystemExit('Archive verification failed; no branches deleted')
    # PR33 is an obsolete, unmerged code-only publication snapshot; its tip is archived.
    for page in range(1, 101):
        pulls = api('GET', f'pulls?state=open&per_page=100&page={page}')
        for pull in pulls:
            head = pull['head']
            if head['repo']['full_name'] == REPOSITORY and head['ref'] in selected:
                if pull['number'] != 33 or head['sha'] != selected[head['ref']]:
                    raise SystemExit('Unplanned active PR; branch archive retained, deletion stopped')
                api('PATCH', 'pulls/33', {'state': 'closed'})
                print('Closed superseded PR33 after verifying its archive tag')
        if len(pulls) < 100:
            break
    if remote_refs().get('refs/heads/main') != args.expected_main:
        raise SystemExit('main changed during archival; no branches deleted')
    if selected:
        # Leases prevent deletion if another writer advanced a branch after inspection.
        # These delete only the explicitly named old branch refs; main is never a refspec.
        leases = [f'--force-with-lease=refs/heads/{branch}:{sha}' for branch, sha in selected.items()]
        deletions = [f':refs/heads/{branch}' for branch in selected]
        git('push', '--atomic', *leases, 'origin', *deletions)
    after = remote_refs()
    if any('refs/heads/' + branch in after for branch in selected):
        raise SystemExit('Unexpected remaining retired branch')
    if any(after.get('refs/tags/' + name) != sha for name, sha in tags.items()):
        raise SystemExit('Post-cleanup archive mismatch')
    print(json.dumps({'cleanup': 'COMPLETE', 'deleted_branches': list(selected),
                      'remaining_branches': {k: v for k, v in after.items() if k.startswith('refs/heads/')},
                      'archive_tags_verified': len(tags)}, indent=2))


if __name__ == '__main__':
    main()
