"""Check saved files segment by segment: check E2 of docs/eval-protocol.md, part E.

    python eval/check_files.py FILE_OR_FOLDER ... [--out results/privacy/e2.json]

Reads every JPEG and PNG given (folders are searched for .jpg, .jpeg and .png files), parses it from its own bytes,
independently of the app and of the privacy suite, and applies the protocol's pass rule. A JPEG fails if it has

- an APP1 segment (EXIF or XMP), an APP11 segment (C2PA and other JUMBF boxes) or an APP13 segment (IPTC);
- a thumbnail (in the JFIF segment, or a JFXX extension);
- an ICC profile, unless every file checked in the same run has the very same one (the protocol allows only the
  browser's own profile, identical in every saved file whatever the input, so a profile that only some files
  carry, or that differs between them, came from the input);
- any byte after the end-of-image marker; or
- a structure the parser cannot follow.

A PNG fails if it has an eXIf chunk (EXIF), a tEXt, zTXt or iTXt chunk (text, which is where PNG keeps XMP), a tIME
chunk, a caBX chunk (C2PA), an iCCP chunk under the same rule as the JPEG's ICC profile, any byte after the IEND
chunk, or a structure the parser cannot follow (a chunk's CRC included). Segments and chunks that the rule does not name but that are not needed to show the picture (a
comment, an Adobe or MPF segment, for example) are listed under "other", for the authors to judge. The report gives
each file's segments in order. It never includes pixels or metadata values, only segment names and sizes.

Exits with an error when any file fails.
"""
import argparse, hashlib, json, sys, zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CODING = {0xC4: 'DHT', 0xCC: 'DAC', 0xDB: 'DQT', 0xDD: 'DRI', 0xDA: 'SOS', 0xDC: 'DNL'}
SOF = {m for m in range(0xC0, 0xD0)} - {0xC4, 0xC8, 0xCC}
PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'
PNG_PICTURE = {b'IHDR', b'PLTE', b'IDAT', b'IEND', b'tRNS', b'gAMA', b'cHRM', b'sRGB', b'sBIT', b'pHYs', b'bKGD'}
PNG_FORBIDDEN = {b'eXIf': 'EXIF (eXIf)', b'tEXt': 'text (tEXt)', b'zTXt': 'text (zTXt)', b'iTXt': 'text or XMP (iTXt)',
                 b'tIME': 'time (tIME)', b'caBX': 'C2PA (caBX)'}


def jpeg_segments(data):
    """[(marker, payload)] of every segment in order, and the offset just after the end-of-image marker. The
    entropy-coded data after each SOS segment is skipped. Raises ValueError if the structure is broken."""
    if data[:2] != b'\xff\xd8':
        raise ValueError('no start-of-image marker')
    pos, segments = 2, []
    while True:
        if pos + 1 >= len(data) or data[pos] != 0xFF:
            raise ValueError(f'no marker at byte {pos}')
        while pos + 2 < len(data) and data[pos + 1] == 0xFF:  # fill bytes before a marker
            pos += 1
        marker = data[pos + 1]
        if marker == 0xD9:
            return segments, pos + 2
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:  # markers without a length
            pos += 2
            continue
        if marker == 0xD8:
            raise ValueError(f'a second start-of-image marker at byte {pos}')
        length = int.from_bytes(data[pos + 2:pos + 4], 'big')
        if length < 2 or pos + 2 + length > len(data):
            raise ValueError(f'the segment at byte {pos} runs past the end of the file')
        segments.append((marker, data[pos + 4:pos + 2 + length]))
        pos += 2 + length
        if marker == 0xDA:
            while pos + 1 < len(data) and not (data[pos] == 0xFF and data[pos + 1] != 0x00
                                                and not 0xD0 <= data[pos + 1] <= 0xD7):
                pos += 1


def jpeg_name(marker, payload):
    """(name, kind): kind is 'picture', 'icc', 'forbidden' or 'other'."""
    if marker in SOF:
        return f'SOF{marker - 0xC0}', 'picture'
    if marker in CODING:
        return CODING[marker], 'picture'
    if marker == 0xE0:
        if payload[:5] == b'JFIF\x00':
            thumbnail = len(payload) >= 14 and payload[12] * payload[13] > 0
            return ('JFIF with a thumbnail', 'forbidden') if thumbnail else ('JFIF', 'picture')
        if payload[:5] == b'JFXX\x00':
            return 'JFXX (a thumbnail)', 'forbidden'
    if marker == 0xE1:
        kind = 'EXIF' if payload[:6] == b'Exif\x00\x00' else 'XMP' if payload.startswith(b'http://ns.adobe.com/xap') else 'APP1'
        return f'APP1 ({kind})', 'forbidden'
    if marker == 0xE2 and payload[:12] == b'ICC_PROFILE\x00':
        return 'APP2 (ICC profile)', 'icc'
    if marker == 0xEB:
        return 'APP11 (C2PA or other JUMBF)', 'forbidden'
    if marker == 0xED:
        return 'APP13 (IPTC)', 'forbidden'
    if marker == 0xFE:
        return 'COM (comment)', 'other'
    if 0xE0 <= marker <= 0xEF:
        label = payload.split(b'\x00', 1)[0][:16].decode('ascii', 'replace')
        return f'APP{marker - 0xE0} ({label})', 'other'
    return f'marker FF{marker:02X}', 'other'


def check_jpeg(data):
    """(segment names, problems, other segments, ICC profile bytes or None, trailing byte count)."""
    segments, end = jpeg_segments(data)
    names, problems, other, icc = [], [], [], []
    for marker, payload in segments:
        name, kind = jpeg_name(marker, payload)
        names.append(name)
        if kind == 'forbidden':
            problems.append(name)
        elif kind == 'other':
            other.append(name)
        elif kind == 'icc':
            icc.append(payload[14:])  # after the identifier and the chunk's sequence number and count
    return names, problems, other, b''.join(icc) or None, len(data) - end


def png_chunks(data):
    """[(type, payload)] of every chunk up to IEND, and the offset just after IEND."""
    if data[:8] != PNG_SIGNATURE:
        raise ValueError('no PNG signature')
    pos, chunks = 8, []
    while True:
        if pos + 12 > len(data):
            raise ValueError(f'the chunk at byte {pos} runs past the end of the file')
        length = int.from_bytes(data[pos:pos + 4], 'big')
        kind = data[pos + 4:pos + 8]
        if pos + 12 + length > len(data):
            raise ValueError(f'the chunk at byte {pos} runs past the end of the file')
        payload = data[pos + 8:pos + 8 + length]
        if zlib.crc32(kind + payload) != int.from_bytes(data[pos + 8 + length:pos + 12 + length], 'big'):
            raise ValueError(f'the CRC of the chunk at byte {pos} is wrong')
        chunks.append((kind, payload))
        pos += 12 + length
        if kind == b'IEND':
            return chunks, pos


def check_png(data):
    chunks, end = png_chunks(data)
    names, problems, other, icc = [], [], [], None
    for kind, payload in chunks:
        name = kind.decode('ascii', 'replace')
        names.append(name)
        if kind in PNG_FORBIDDEN:
            problems.append(PNG_FORBIDDEN[kind])
        elif kind == b'iCCP':
            icc = payload
        elif kind not in PNG_PICTURE:
            other.append(name)
    return names, problems, other, icc, len(data) - end


def check(paths):
    """The report for the files at paths, checked together (the ICC rule compares them with each other)."""
    files, profiles = [], {}
    for path in paths:
        data = Path(path).read_bytes()
        entry = {'file': str(path), 'bytes': len(data)}
        try:
            if data[:8] == PNG_SIGNATURE:
                entry['format'] = 'PNG'
                names, problems, other, icc, trailing = check_png(data)
            else:
                entry['format'] = 'JPEG'
                names, problems, other, icc, trailing = check_jpeg(data)
        except ValueError as e:
            entry.update({'pass': False, 'problems': [f'not a well-formed {entry["format"]}: {e}']})
            files.append(entry)
            continue
        if trailing:
            problems.append(f'{trailing} bytes after the end of the image')
        if icc is not None:
            entry['icc'] = hashlib.sha256(icc).hexdigest()
            profiles.setdefault(entry['icc'], []).append(entry)
        entry.update({'segments': names, 'problems': problems, 'other': other})
        files.append(entry)
    without = sum('segments' in e and 'icc' not in e for e in files)
    if len(profiles) > 1 or (profiles and without):
        for digest, entries in profiles.items():
            for entry in entries:
                entry['problems'].append(f'its ICC profile ({digest[:12]}) is not the same in every saved file: '
                                         + ('another file has a different one' if len(profiles) > 1
                                            else f'{without} files have none'))
    for entry in files:
        entry['pass'] = not entry['problems']
    return {'files': files, 'passed': sum(e['pass'] for e in files), 'failed': sum(not e['pass'] for e in files),
            'iccProfiles': {digest: len(entries) for digest, entries in profiles.items()}}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('paths', nargs='+', type=Path, help='saved files, or folders to search for .jpg, .jpeg and .png')
    ap.add_argument('--out', type=Path, help='write the report as JSON here')
    args = ap.parse_args(argv)
    paths = []
    for p in args.paths:
        if p.is_dir():
            paths += sorted(f for f in p.rglob('*') if f.suffix.lower() in ('.jpg', '.jpeg', '.png') and f.is_file())
        elif p.is_file():
            paths.append(p)
        else:
            ap.error(f'{p} does not exist')
    if not paths:
        ap.error('no .jpg, .jpeg or .png files found')
    report = check(paths)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=1) + '\n', encoding='utf-8')
    for entry in report['files']:
        if not entry['pass'] or entry.get('other'):
            print(f'{"FAIL" if not entry["pass"] else "note"} {entry["file"]}: '
                  + '; '.join(entry['problems'] + [f'other: {o}' for o in entry.get('other', [])]))
    print(f'{report["passed"]} of {len(report["files"])} files pass; ICC profiles: {len(report["iccProfiles"])}')
    if report['failed']:
        sys.exit(1)


if __name__ == '__main__':
    main()
