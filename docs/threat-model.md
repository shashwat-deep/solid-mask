# Threat model

Draft for M0. Owner: Shashwat Deep; reviewer: Pratyush. Section III of the paper is written from this file, and every check named here (E1 to E3, part B) is defined in `docs/eval-protocol.md`.

## Who uses the tool, and what they protect

The tool is for people who want to share a photo without being identified from it. Examples: someone sending an intimate photo to a partner, someone posting a photo from a protest, a parent sharing a picture of their child, someone sending evidence of harassment. They want to protect:

- who is in the photo, above all their face;
- where and when the photo was taken, and with which phone;
- links between this photo and other photos of them.

## Assumptions

- The phone, the browser and its extensions are not compromised. An extension allowed to read pages can read the photos too, and no web page can prevent that.
- The page reaches the user intact over HTTPS from our host, GitHub Pages. Anyone who would rather not trust the host can run a copy of a tagged release (README, "Run your own copy").
- The user looks over every photo before saving it. The detector misses faces; the review step is how those faces get covered.
- The attacker knows exactly how the tool works and has its source code.

## A1. Someone holding the leaked photo

Who: the person it was sent to, anyone they pass it on to, or anyone who obtains it from a breached platform. They have the saved file, every byte of it, and unlimited time and software.

Goal: work out who is in the photo, where it was taken, or which phone took it.

The tool protects:
- the faces it covers (A3 explains why the block can't be lifted);
- the file's metadata, which the tool drops by writing a new file from the pixels alone: GPS position, date and time, phone make, model and serial numbers, lens and software, maker notes, XMP edit history, IPTC captions, embedded previews and thumbnails, and C2PA content credentials;
- the original file name, which often encodes the date and time, replaced by `masked-N.jpg`.

It does not protect:
- faces it missed that the user did not cover. This is the main risk, and part B of the protocol measures it;
- anything else in the picture: body, tattoos, hair, clothes, jewellery, the room, the view, reflections, text such as a name on a badge or a letter, and other people. Oh et al. recognised people in social-media photos from body and context even with their heads blacked out;
- places that can be recognised from what the picture shows.

Checks: E1 (metadata audit) and E2 (file structure); the missed-face rates of part B.

## A2. Someone running a reverse image search

Who: anyone holding the photo who uploads it to a general image search (Google Lens, Bing, Yandex, TinEye) or a face search engine (PimEyes and similar).

Goal: find other copies of the photo, or other photos of the same person or place, that reveal who the person is.

The tool protects:
- against face search: a covered face can't be searched for.

It does not protect:
- against a match with an uncovered copy of the same photo posted anywhere, or with near-identical photos taken at the same moment. Search engines match the whole picture, and the blocks change only part of it;
- against matches on the place or on other people in the photo.

Check: E3 (perceptual-hash distance between each saved copy and its original). A match means hash-based search could link the covered copy to an uncovered original. Optionally, the authors also search Google Lens and TinEye for covered copies of their own photos that are already online; no one else's photo is uploaded anywhere.

## A3. A model trying to undo the block

Who: anyone who can run or train machine-learning models.

Goal: recover the covered face, or recognise the person behind the block.

Why blur and pixelation fail: they keep information about the face, only less of it, and a model trained on obfuscated images learns to use what is left. McPherson et al. recognised YouTube-blurred faces 57.75% of the time among 40 people, where guessing gets 2.5%. Deep found that a small CNN trained on obfuscated MNIST digits still read 89.28% of digits blurred with σ = 4 and 51.15% of digits pixelated with 14 × 14 blocks, where guessing gets 10%. Hill et al. recovered words from pixelated and blurred text.

Why the block holds: the pixels under a block are replaced by one constant colour before the file is written, so the saved file holds no information about the covered face, and every covered face looks the same. A recogniser trained on covered images can use only what lies outside the blocks: in Deep's replication, models trained on solid-masked digits scored 11.35% in all ten seeds, exactly the share of the most common digit. A model that "restores" the face, by inpainting for example, invents one from the hair, skin, outline and pose around the block. It may share those broad features with the real face, but nothing that the block removed.

This holds only if the face is kept out of every byte of the saved file. The privacy suite (`tests/privacy/`) checks each condition:
- the block is opaque and painted into the pixel buffer before encoding: decoded pixels inside it equal the block colour, exactly in PNG and within ±2 in JPEG blocks that lie wholly inside the mask;
- the file is encoded from the masked pixels alone, with no thumbnail or preview of the original. Image editors that change a JPEG but leave its EXIF thumbnail untouched leak what they removed through it (CVE-2005-0406), and in a 2004 web crawl Murdoch and Dornseif found that almost 1% of JPEG files had an incorrect EXIF thumbnail;
- nothing of the original file survives after the end of the new one. In 2023, Google Pixel's Markup editor (CVE-2023-21036) and the Windows Snipping Tool (CVE-2023-28303) wrote edited images over the original file without cutting it short, so cropped-out parts could be recovered ("aCropalypse");
- each block covers its padded box completely.

What remains is A1's problem: identifying the person from whatever the blocks do not cover.

Checks: E2 and the privacy suite, together with the argument above.

## Out of scope

- The original photo, which stays in the user's gallery and cloud backups.
- A compromised phone, browser or browser extension.
- An altered copy of the page served by a compromised host; the mitigation is running your own copy.
- The camera's sensor fingerprint (photo-response non-uniformity, PRNU), which can link photos to the phone that took them even without metadata. Covering faces does not remove it.
- Video, voice and gait; the tool handles still photos only.
- Copies or screenshots that a recipient makes.

## Summary

| Threat | Protected | Not protected | Checks | Paper |
|---|---|---|---|---|
| A1 leaked photo | covered faces, metadata, file name | missed faces, body, context, place | E1, E2, part B | V-B, V-C |
| A2 reverse image search | face search | uncovered copies elsewhere, place | E3 | V-C |
| A3 model undoing the block | covered faces | what lies outside the blocks | E2, privacy suite, argument | III, V-C |

## Sources to cite

- R. McPherson, R. Shokri and V. Shmatikov, "Defeating image obfuscation with deep learning," arXiv:1609.00408, 2016.
- S. Deep, "Can a small convolutional network still read blurred and pixelated digits? A replication of McPherson et al. (2016)," Zenodo, 2026, doi:10.5281/zenodo.23692156.
- S. Hill, Z. Zhou, L. Saul and H. Shacham, "On the (in)effectiveness of mosaicing and blurring as tools for document redaction," Proc. Priv. Enhanc. Technol., vol. 2016, no. 4, pp. 403–417, doi:10.1515/popets-2016-0047.
- S. J. Oh, R. Benenson, M. Fritz and B. Schiele, "Faceless person recognition: Privacy implications in social media," ECCV 2016, doi:10.1007/978-3-319-46487-9_2.
- Y. Li, N. Vishwamitra, B. P. Knijnenburg, H. Hu and K. Caine, "Blur vs. block: Investigating the effectiveness of privacy-enhancing obfuscation for images," CVPRW 2017, doi:10.1109/CVPRW.2017.176. Among 53 viewers, a solid block hid identity better than blurring, though they liked it least.
- CVE-2023-21036 (Pixel Markup) and CVE-2023-28303 (Windows Snipping Tool).
- CVE-2005-0406, published 14 February 2005: software that modifies a JPEG may leave the original EXIF thumbnail, leaking what was removed from the main image.
- S. J. Murdoch and M. Dornseif, "Hidden data in Internet published documents," 21st Chaos Communication Congress (21C3), Berlin, Dec. 2004.
- Meta, PDQ perceptual hash, ThreatExchange repository (cite the version used).
- J. Lukáš, J. Fridrich and M. Goljan, "Digital camera identification from sensor pattern noise," IEEE Trans. Inf. Forensics Security, 2006 (check the volume and pages).
