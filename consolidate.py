#!/usr/bin/env python3
"""
Consolidate the OTA70 EPUB from 241 split HTML files into one file per biblical book.

Usage:
    python3 consolidate.py

This script:
1. Reads all index_split_*.html files in spine order
2. Identifies book boundaries by <h1 class="book-title"> tags
3. Merges content across file splits into one HTML per book
4. Assigns stable chapter IDs (ch1, ch2, ...)
5. Cleans up Calibre conversion artifacts (<div _="" body="">)
6. Generates new content.opf and toc.ncx
"""

import os
import re
import glob
import xml.etree.ElementTree as ET
from collections import OrderedDict
from bs4 import BeautifulSoup, NavigableString, Tag

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# Book definitions: ordered list of (title_text_match, output_filename)
# title_text_match is compared case-insensitively to the stripped text of
# <h1 class="book-title"> elements.
#
# "Front-matter" items are merged into front-matter.html.
# "Structural" headings (APPENDIX A, APPENDIX B, ORTHODOX ENGLAND,
#  THE OLD TESTAMENT...) are absorbed into their adjacent book.
# ---------------------------------------------------------------------------

FRONT_MATTER_TITLES = {
    "THE OLD TESTAMENT ACCORDING TO THE SEVENTY",
    "ORTHODOX ENGLAND",
    "ACKNOWLEDGEMENTS",
    "PREFACE",
    "INTRODUCTION",
}

# Titles that are structural headings (not standalone books).
# Their content is prepended to the next real book that follows.
STRUCTURAL_TITLES = {
    "APPENDIX A",
    "APPENDIX B",
}

# Ordered mapping: normalized title -> output filename
# We match against .strip().upper() of the h1 text.
BOOK_ORDER = OrderedDict([
    ("GENESIS", "01-genesis.html"),
    ("EXODUS", "02-exodus.html"),
    ("LEVITICUS", "03-leviticus.html"),
    ("NUMBERS", "04-numbers.html"),
    ("DEUTERONOMY", "05-deuteronomy.html"),
    ("JOSHUA SON OF NUN", "06-joshua.html"),
    ("JUDGES", "07-judges.html"),
    ("RUTH", "08-ruth.html"),
    ("1 KINGDOMS", "09-1-kingdoms.html"),
    ("2 KINGDOMS", "10-2-kingdoms.html"),
    ("3 KINGDOMS (1 KINGS)", "11-3-kingdoms.html"),
    ("4 KINGDOMS (2 KINGS)", "12-4-kingdoms.html"),
    ("1 PARALEIPOMENON (CHRONICLES)", "13-1-paraleipomenon.html"),
    ("2 PARALEIPOMENON (CHRONICLES)", "14-2-paraleipomenon.html"),
    ("1 ESDRAS (EZRA)", "15-1-esdras.html"),
    ("2 ESDRAS (EZRA)", "16-2-esdras.html"),
    ("NEHEMIAH", "17-nehemiah.html"),
    ("TOBIT", "18-tobit.html"),
    ("JUDITH", "19-judith.html"),
    ("ESTHER", "20-esther.html"),
    ("1 MACCABEES", "21-1-maccabees.html"),
    ("2 MACCABEES", "22-2-maccabees.html"),
    ("3 MACCABEES", "23-3-maccabees.html"),
    ("PSALMS", "24-psalms.html"),
    ("JOB", "25-job.html"),
    ("PROVERBS OF SOLOMON", "26-proverbs.html"),
    ("ECCLESIASTES", "27-ecclesiastes.html"),
    ("SONG OF SONGS", "28-song-of-songs.html"),
    ("WISDOM OF SOLOMON", "29-wisdom-of-solomon.html"),
    ("THE WISDOM OF SIRACH", "30-wisdom-of-sirach.html"),
    ("HOSEA", "31-hosea.html"),
    ("AMOS", "32-amos.html"),
    ("MICAH", "33-micah.html"),
    ("JOEL", "34-joel.html"),
    ("OBADIAH", "35-obadiah.html"),
    ("JONAH", "36-jonah.html"),
    ("NAHUM", "37-nahum.html"),
    ("HABBAKUK", "38-habbakuk.html"),
    ("ZEPHANIAH", "39-zephaniah.html"),
    ("HAGGAI", "40-haggai.html"),
    ("ZECHARIAH", "41-zechariah.html"),
    ("MALACHI", "42-malachi.html"),
    ("ISAIAH", "43-isaiah.html"),
    ("JEREMIAH", "44-jeremiah.html"),
    ("BARUCH", "45-baruch.html"),
    ("AN EPISTLE OF JEREMIAH", "46-epistle-of-jeremiah.html"),
    ("LAMENTATIONS OF JEREMIAH", "47-lamentations.html"),
    ("EZEKIEL", "48-ezekiel.html"),
    ("DANIEL", "49-daniel.html"),
    ("4 MACCABEES", "50-4-maccabees.html"),
    ("THE PRAYER OF MANASSEH KING OF JUDEA, WHILE BEING HELD IN THE CAPTIVITY OF BABYLON",
     "51-prayer-of-manasseh.html"),
    ("1 ESDRA", "52-1-esdra.html"),
    # The appendix Nehemiah is a distinct entry; we give it a different filename
    ("NEHEMIAH_APPENDIX", "53-nehemiah-appendix.html"),
    ("2 ESDRA", "54-2-esdra.html"),
])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def slugify(title):
    """Convert a book title to a lookup key."""
    return title.strip().upper()


def get_split_files():
    """Return sorted list of index_split_*.html files."""
    pattern = os.path.join(BASE_DIR, "index_split_*.html")
    files = sorted(glob.glob(pattern))
    return files


def parse_html(filepath):
    """Parse an HTML file and return a BeautifulSoup object."""
    with open(filepath, "r", encoding="utf-8") as f:
        return BeautifulSoup(f.read(), "lxml")


def extract_body_children(soup):
    """Return a list of direct children of <body>, excluding junk divs."""
    body = soup.find("body")
    if not body:
        return []
    children = []
    for child in body.children:
        if isinstance(child, NavigableString):
            if child.strip():
                children.append(child)
            continue
        if isinstance(child, Tag):
            # Skip junk <div _="" body=""> artifacts
            if child.name == "div" and child.has_attr("_"):
                continue
            children.append(child)
    return children


def is_book_title(tag):
    """Check if a tag is an <h1 class="book-title">."""
    return (isinstance(tag, Tag) and
            tag.name == "h1" and
            "book-title" in tag.get("class", []))


def get_book_key(title_text):
    """Map an h1 book-title text to its BOOK_ORDER key, or a special category."""
    norm = title_text.strip().upper()
    if norm in FRONT_MATTER_TITLES:
        return ("front-matter", norm)
    if norm in STRUCTURAL_TITLES:
        return ("structural", norm)
    if norm in BOOK_ORDER:
        return ("book", norm)
    # Fuzzy: check startswith for minor variations
    for key in BOOK_ORDER:
        if norm.startswith(key) or key.startswith(norm):
            return ("book", key)
    print(f"  WARNING: Unrecognized book title: '{title_text.strip()}'")
    return ("unknown", norm)


# ---------------------------------------------------------------------------
# Phase 1: Scan all files and build book segments
# ---------------------------------------------------------------------------

def scan_all_files():
    """
    Walk through all split files in order. Return a list of segments:
    [
      {
        "type": "front-matter" | "structural" | "book",
        "key": normalized title string,
        "elements": [list of BeautifulSoup Tag/NavigableString objects],
      },
      ...
    ]
    """
    files = get_split_files()
    segments = []
    current_segment = None

    for filepath in files:
        fname = os.path.basename(filepath)
        soup = parse_html(filepath)
        children = extract_body_children(soup)

        for child in children:
            if is_book_title(child):
                title_text = child.get_text()
                cat, key = get_book_key(title_text)

                # Special handling: the second "NEHEMIAH" in appendix B
                # (file index_split_238.html) needs disambiguation
                if key == "NEHEMIAH" and current_segment and (
                    current_segment["key"] in ("1 ESDRA",) or
                    (current_segment["type"] == "structural" and
                     current_segment["key"] == "APPENDIX B")):
                    key = "NEHEMIAH_APPENDIX"

                # Also handle: if we already have a NEHEMIAH segment and
                # encounter another one in the appendix region (file >= 238)
                if key == "NEHEMIAH" and any(
                    s["key"] == "NEHEMIAH" for s in segments
                ) and "238" in fname:
                    key = "NEHEMIAH_APPENDIX"

                if current_segment is not None:
                    segments.append(current_segment)

                current_segment = {
                    "type": cat,
                    "key": key,
                    "elements": [child],
                }
            else:
                if current_segment is None:
                    # Content before any book title — treat as front matter
                    current_segment = {
                        "type": "front-matter",
                        "key": "PRE-CONTENT",
                        "elements": [],
                    }
                current_segment["elements"].append(child)

    if current_segment is not None:
        segments.append(current_segment)

    return segments


# ---------------------------------------------------------------------------
# Phase 2: Merge segments into output books
# ---------------------------------------------------------------------------

def merge_segments(segments):
    """
    Merge segments into output books.
    - Front-matter segments -> single "front-matter.html"
    - Structural segments -> prepend to the next real book
    - Book segments -> one file each

    Returns OrderedDict: filename -> {
        "title": display title,
        "elements": [list of elements],
    }
    """
    books = OrderedDict()
    pending_structural = []

    for seg in segments:
        if seg["type"] == "front-matter":
            if "front-matter.html" not in books:
                books["front-matter.html"] = {
                    "title": "Front Matter",
                    "elements": [],
                }
            books["front-matter.html"]["elements"].extend(seg["elements"])

        elif seg["type"] == "structural":
            # Buffer structural headings to prepend to next book
            pending_structural.extend(seg["elements"])

        elif seg["type"] == "book":
            key = seg["key"]
            filename = BOOK_ORDER.get(key, key.lower().replace(" ", "-") + ".html")
            display_title = seg["elements"][0].get_text().strip() if seg["elements"] else key

            if filename not in books:
                books[filename] = {
                    "title": display_title,
                    "elements": [],
                }
            # Prepend any pending structural content
            if pending_structural:
                books[filename]["elements"].extend(pending_structural)
                pending_structural = []
            books[filename]["elements"].extend(seg["elements"])

        else:
            # Unknown — append to front matter
            if "front-matter.html" not in books:
                books["front-matter.html"] = {
                    "title": "Front Matter",
                    "elements": [],
                }
            books["front-matter.html"]["elements"].extend(seg["elements"])

    return books


# ---------------------------------------------------------------------------
# Phase 3: Re-number chapter IDs and write HTML files
# ---------------------------------------------------------------------------

def renumber_ids(elements):
    """
    Walk through elements, find <h2 class="chapter-num"> tags and assign
    sequential IDs: ch1, ch2, ch3, ...
    Also returns a list of (chapter_label, anchor_id) for TOC generation.
    """
    chapters = []
    ch_counter = 0

    for el in elements:
        if not isinstance(el, Tag):
            continue
        # Find all chapter-num headings in this element and its descendants
        if el.name == "h2" and "chapter-num" in el.get("class", []):
            ch_counter += 1
            new_id = f"ch{ch_counter}"
            el["id"] = new_id
            chapters.append((el.get_text().strip(), new_id))
        else:
            for h2 in el.find_all("h2", class_="chapter-num"):
                ch_counter += 1
                new_id = f"ch{ch_counter}"
                h2["id"] = new_id
                chapters.append((h2.get_text().strip(), new_id))

    return chapters


def find_sub_sections(elements):
    """
    Find non-chapter sub-sections within a book (e.g., Susanna, Bel and the Dragon).
    These are typically h2 or h3 headings that aren't chapter-num class.
    Returns list of (label, anchor_id).
    """
    sections = []
    sec_counter = 0

    for el in elements:
        if not isinstance(el, Tag):
            continue
        # Check for h2/h3 that aren't chapter-num (like "Susanna", "Bel and the Dragon")
        candidates = []
        if el.name in ("h2", "h3") and "chapter-num" not in el.get("class", []):
            candidates.append(el)
        if isinstance(el, Tag):
            for h in el.find_all(["h2", "h3"]):
                if "chapter-num" not in h.get("class", []):
                    candidates.append(h)

        for h in candidates:
            text = h.get_text().strip()
            # Skip empty or generic headings
            if not text or text.upper().startswith("CHAPTER"):
                continue
            sec_counter += 1
            new_id = f"sec{sec_counter}"
            h["id"] = new_id
            sections.append((text, new_id))

    return sections


def write_book_html(filepath, title, elements):
    """Write a consolidated book HTML file."""
    # Build inner HTML from elements
    inner_parts = []
    for el in elements:
        if isinstance(el, NavigableString):
            inner_parts.append(str(el))
        else:
            inner_parts.append(str(el))

    inner_html = "\n".join(inner_parts)

    html = f"""<?xml version='1.0' encoding='utf-8'?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
  <title>{title}</title>
  <link rel="stylesheet" type="text/css" href="stylesheet.css"/>
</head>
<body>
{inner_html}
</body>
</html>"""

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)


# ---------------------------------------------------------------------------
# Phase 4: Generate content.opf
# ---------------------------------------------------------------------------

def generate_content_opf(book_files):
    """
    Generate a new content.opf with the correct manifest and spine.
    book_files: OrderedDict of filename -> {"title": ..., "chapters": ...}
    """
    manifest_items = []
    spine_items = []

    # Fixed items
    manifest_items.append('    <item id="titlepage" href="titlepage.xhtml" media-type="application/xhtml+xml"/>')
    manifest_items.append('    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>')
    manifest_items.append('    <item id="css" href="stylesheet.css" media-type="text/css"/>')
    manifest_items.append('    <item id="cover" href="cover.jpeg" media-type="image/jpeg"/>')

    spine_items.append('    <itemref idref="titlepage"/>')

    for i, filename in enumerate(book_files):
        item_id = f"book-{i}"
        manifest_items.append(
            f'    <item id="{item_id}" href="{filename}" media-type="application/xhtml+xml"/>'
        )
        spine_items.append(f'    <itemref idref="{item_id}"/>')

    opf = f"""<?xml version='1.0' encoding='utf-8'?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="uuid_id">
  <metadata xmlns:opf="http://www.idpf.org/2007/opf" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:calibre="http://calibre.kovidgoyal.net/2009/metadata">
    <dc:title>THE OLD TESTAMENT ACCORDING TO THE SEVENTY</dc:title>
    <dc:creator opf:role="aut" opf:file-as="Asser, Michael">Michael Asser</dc:creator>
    <dc:description>This English version of the Septuagint is based upon the text of the Authorized Version of the Bible (the King James Version) and the Apocrypha; the rights of which are vested in the Crown; and whose permission to make use of them is gratefully acknowledged.</dc:description>
    <dc:date>2023-12-22T21:03:05+00:00</dc:date>
    <dc:identifier id="uuid_id" opf:scheme="uuid">e1f64b9c-d5ce-4103-9685-e45e97c5cef9</dc:identifier>
    <dc:language>en</dc:language>
    <meta name="cover" content="cover"/>
  </metadata>
  <manifest>
{chr(10).join(manifest_items)}
  </manifest>
  <spine toc="ncx">
{chr(10).join(spine_items)}
  </spine>
</package>"""

    opf_path = os.path.join(BASE_DIR, "content.opf")
    with open(opf_path, "w", encoding="utf-8") as f:
        f.write(opf)
    print(f"  Written: content.opf")


# ---------------------------------------------------------------------------
# Phase 5: Generate toc.ncx
# ---------------------------------------------------------------------------

def generate_toc_ncx(book_data):
    """
    Generate a new toc.ncx.
    book_data: OrderedDict of filename -> {
        "title": str,
        "chapters": [(label, anchor_id), ...],
        "sections": [(label, anchor_id), ...],
    }
    """
    nav_points = []
    play_order = 1

    # Title page
    nav_points.append(f"""    <navPoint id="num_{play_order}" playOrder="{play_order}">
      <navLabel>
        <text>TITLE PAGE</text>
      </navLabel>
      <content src="titlepage.xhtml"/>
    </navPoint>""")
    play_order += 1

    for filename, data in book_data.items():
        title = data["title"]
        chapters = data.get("chapters", [])
        sections = data.get("sections", [])

        if chapters or sections:
            # Book with sub-navigation
            nav_points.append(f"""    <navPoint id="num_{play_order}" playOrder="{play_order}">
      <navLabel>
        <text>{title}</text>
      </navLabel>
      <content src="{filename}"/>""")
            play_order += 1

            # Add sections first (like Susanna before chapters in Daniel)
            for label, anchor in sections:
                nav_points.append(f"""      <navPoint id="num_{play_order}" playOrder="{play_order}">
        <navLabel>
          <text>{label}</text>
        </navLabel>
        <content src="{filename}#{anchor}"/>
      </navPoint>""")
                play_order += 1

            # Then chapters
            for label, anchor in chapters:
                nav_points.append(f"""      <navPoint id="num_{play_order}" playOrder="{play_order}">
        <navLabel>
          <text>{label}</text>
        </navLabel>
        <content src="{filename}#{anchor}"/>
      </navPoint>""")
                play_order += 1

            nav_points.append("    </navPoint>")
        else:
            # Simple entry (no chapters — like front matter or short books)
            nav_points.append(f"""    <navPoint id="num_{play_order}" playOrder="{play_order}">
      <navLabel>
        <text>{title}</text>
      </navLabel>
      <content src="{filename}"/>
    </navPoint>""")
            play_order += 1

    ncx = f"""<?xml version='1.0' encoding='utf-8'?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1" xml:lang="en">
  <head>
    <meta name="dtb:uid" content="e1f64b9c-d5ce-4103-9685-e45e97c5cef9"/>
    <meta name="dtb:depth" content="2"/>
    <meta name="dtb:totalPageCount" content="0"/>
    <meta name="dtb:maxPageNumber" content="0"/>
  </head>
  <docTitle>
    <text>THE OLD TESTAMENT ACCORDING TO THE SEVENTY</text>
  </docTitle>
  <navMap>
{chr(10).join(nav_points)}
  </navMap>
</ncx>"""

    ncx_path = os.path.join(BASE_DIR, "toc.ncx")
    with open(ncx_path, "w", encoding="utf-8") as f:
        f.write(ncx)
    print(f"  Written: toc.ncx")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("Phase 1: Scanning all split files...")
    segments = scan_all_files()
    print(f"  Found {len(segments)} segments")

    # Count by type
    type_counts = {}
    for s in segments:
        type_counts[s["type"]] = type_counts.get(s["type"], 0) + 1
    for t, c in type_counts.items():
        print(f"    {t}: {c}")

    print("\nPhase 2: Merging segments into books...")
    books = merge_segments(segments)
    print(f"  Merged into {len(books)} output files")

    print("\nPhase 3: Re-numbering IDs and writing HTML files...")
    book_data = OrderedDict()
    for filename, data in books.items():
        filepath = os.path.join(BASE_DIR, filename)
        title = data["title"]
        elements = data["elements"]

        # Re-number chapter IDs
        chapters = renumber_ids(elements)
        sections = find_sub_sections(elements)

        write_book_html(filepath, title, elements)
        print(f"  Written: {filename} ({len(chapters)} chapters, {len(sections)} sections)")

        book_data[filename] = {
            "title": title,
            "chapters": chapters,
            "sections": sections,
        }

    print("\nPhase 4: Generating content.opf...")
    generate_content_opf(book_data)

    print("\nPhase 5: Generating toc.ncx...")
    generate_toc_ncx(book_data)

    print(f"\nDone! Created {len(book_data)} consolidated files.")
    print("Old index_split_*.html files can now be deleted.")


if __name__ == "__main__":
    main()
