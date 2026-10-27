"""Download the images listed in a manifest and check their SHA-256s.

    python eval/download.py [eval/manifest/images.csv] [--out data/openimages/images] [--jobs 8]

Each image is saved as <out>/<imageId><extension of its URL>. A file that is already there is checked and
downloaded again only if its SHA-256 differs from the manifest. The script ends with an error that lists every
image it could not download or whose SHA-256 still differs. Nothing it downloads is committed: data/ is in
.gitignore.
"""
import argparse, concurrent.futures, csv, hashlib, http.client, os, sys, time, urllib.error, urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
USER_AGENT = 'solid-mask-eval (+https://github.com/shashwat-deep/solid-mask)'


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def fetch(url, dest, sha256=None, tries=3, timeout=60):
    """Make dest a copy of url and return its SHA-256.

    An existing file is kept when sha256 is None or matches. A download is written to dest + '.part' and renamed,
    so an interrupted download never leaves a partial file at dest. Raises ValueError when the downloaded file's
    SHA-256 differs from sha256, and OSError or http.client.HTTPException when all tries fail (OSError at once on
    HTTP 404)."""
    dest = Path(dest)
    if dest.exists():
        got = sha256_file(dest)
        if sha256 is None or got == sha256:
            return got
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = response.read()
            break
        except (OSError, http.client.HTTPException) as e:
            if attempt == tries - 1 or (isinstance(e, urllib.error.HTTPError) and e.code == 404):
                raise
            time.sleep(2 ** attempt)
    got = hashlib.sha256(data).hexdigest()
    if sha256 is not None and got != sha256:
        raise ValueError(f'SHA-256 of {url} is {got}, expected {sha256}')
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + '.part')
    part.write_bytes(data)
    os.replace(part, dest)
    return got


def fetch_all(items, jobs=8):
    """Fetch (key, url, dest, sha256) items in parallel. Returns ({key: sha256}, {key: error message})."""
    done, failed = {}, {}
    with concurrent.futures.ThreadPoolExecutor(jobs) as pool:
        futures = {pool.submit(fetch, url, dest, sha): key for key, url, dest, sha in items}
        for future in concurrent.futures.as_completed(futures):
            try:
                done[futures[future]] = future.result()
            except (OSError, ValueError, http.client.HTTPException) as e:
                failed[futures[future]] = f'{type(e).__name__}: {e}'
    return done, failed


def image_path(out, image_id, url):
    return Path(out) / (image_id + (Path(urllib.parse.urlparse(url).path).suffix or '.jpg'))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('manifest', nargs='?', default=ROOT / 'eval/manifest/images.csv')
    ap.add_argument('--out', default=ROOT / 'data/openimages/images')
    ap.add_argument('--jobs', type=int, default=8)
    args = ap.parse_args(argv)
    with open(args.manifest, newline='', encoding='utf-8') as fh:
        rows = list(csv.DictReader(fh))
    missing = [r['imageId'] for r in rows if not r['sha256']]
    if missing:
        sys.exit(f'{args.manifest} has no SHA-256 for {len(missing)} images, for example {missing[0]}')
    done, failed = fetch_all([(r['imageId'], r['url'], image_path(args.out, r['imageId'], r['url']), r['sha256'])
                              for r in rows], args.jobs)
    print(f'{len(done)} of {len(rows)} images in {args.out} match the SHA-256s in {args.manifest}')
    if failed:
        for key in sorted(failed):
            print(f'  {key}: {failed[key]}', file=sys.stderr)
        sys.exit(f'{len(failed)} images failed')


if __name__ == '__main__':
    main()
