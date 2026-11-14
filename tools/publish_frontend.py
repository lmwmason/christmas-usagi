"""Build and fast-forward the generated frontend branch without touching main."""
from pathlib import Path
import argparse
import os
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def git(*args, cwd=ROOT, check=True):
    return subprocess.run(['git', *args], cwd=cwd, text=True, capture_output=True, check=check)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api-base', required=True, help='Public API origin; validated by the frontend builder')
    args = parser.parse_args()
    source = git('rev-parse', 'HEAD').stdout.strip()
    subprocess.run(['npm', 'run', 'build'], cwd=ROOT, env={**os.environ, 'USAGI_API_BASE_URL':args.api_base}, check=True)
    git('fetch', 'origin', 'frontend')
    with tempfile.TemporaryDirectory(prefix='usagi-publish-') as temp:
        worktree = Path(temp) / 'site'
        git('worktree', 'add', '--detach', str(worktree), 'origin/frontend')
        try:
            git('rm', '-r', '--quiet', '--', '.', cwd=worktree)
            shutil.copytree(ROOT / 'dist', worktree, dirs_exist_ok=True)
            for name in ('LICENSE', 'NOTICE', 'THIRD_PARTY_NOTICES.md'):
                shutil.copyfile(ROOT / name, worktree / name)
            (worktree / 'README.md').write_text(
                '# Christmas Usagi — Frontend\n\n'
                'Generated static frontend for [Christmas Usagi](https://github.com/lmwmason/christmas-usagi/tree/main).\n\n'
                f'Source commit: `{source}`. API origin: `{args.api_base}`.\n\n'
                'This branch contains the prebuilt site and public assets only. Original code is Apache-2.0; '
                'third-party artwork and audio retain their own rights. See LICENSE, NOTICE, and THIRD_PARTY_NOTICES.md.\n')
            git('add', '--all', cwd=worktree)
            if git('diff', '--cached', '--quiet', cwd=worktree, check=False).returncode == 0:
                print('Frontend branch already matches this build.')
                return
            git('commit', '-m', f'Publish frontend from {source[:8]}', cwd=worktree)
            git('push', 'origin', 'HEAD:refs/heads/frontend', cwd=worktree)
            print('Published frontend branch. Request a CBGPU frontend redeployment to promote it.')
        finally:
            git('worktree', 'remove', '--force', str(worktree))


if __name__ == '__main__':
    main()
